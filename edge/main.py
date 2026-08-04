"""엣지 러너 진입점.

    uv run tasks.py edge                    # edge/config.yaml 의 모든 카메라
    uv run tasks.py edge --cam 1            # 한 대만
    uv run tasks.py edge --log-level DEBUG

**영상은 RTSP 로만 받는다.** 로컬 테스트에서도 파일을 직접 열지 않는다 — 가짜 카메라가
송출하는 것을 본다(`uv run tasks.py cams --source media/lego_sample_1.mp4`). 그래야
엣지가 보는 것이 실물과 같아지고, 재연결·프레임 드랍 같은 스트림 경로의 문제가 M9 까지
숨지 않는다.

**시각은 `Clock` 에서만 얻는다**(CLAUDE.md 절대규칙 1). 시스템 시계를 직접 읽지 않고
진입점에서 `RealClock()` 을 만들어 주입한다.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import sys
import threading
from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from aegis_contracts.edge import CameraHealth, EdgeClock, EdgeMessage, HeartbeatMsg
from aegis_vision.clock import Clock, RealClock

from .classify import HelmetClassifier
from .client import EdgeSocket, Setup, fetch_setup
from .config import ConfigError, EdgeConfig, StreamConfig, load_config
from .depth import DepthEstimator
from .detect import Detector
from .letterbox import Letterbox
from .pipeline import CameraPipeline
from .sysinfo import memory_used_mb

__all__ = ["main", "run"]

log = logging.getLogger("edge")

# `uv run` 으로 돌리면 출력이 파이프가 되고, 한글 Windows 는 그때 cp949 를 쓴다.
# '—' 하나에 UnicodeEncodeError 로 죽지 않게 한다(tasks.py · sim 과 같은 처리).
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 설정 재조회 주기(초). 캘리브레이션·구역·정책이 화면에서 바뀌면 여기서 따라잡는다.
_SETUP_REFRESH_S = 30.0

#: 스트림이 끊겼을 때 재연결 간격(초).
_RECONNECT_S = 2.0


class _LatestFrame:
    """RTSP 를 계속 읽어 **가장 최근 프레임 하나만** 남긴다.

    ★ 이 스레드가 없으면 안 된다. 추론이 스트림보다 느리면(노트북 실측 2~3fps 대
    15fps) `VideoCapture.read()` 가 디코더 큐에 쌓인 **과거 프레임**을 하나씩 꺼내
    주므로, 시간이 갈수록 좌표가 영상보다 뒤처진다. 오버레이 정합(±100ms)이 무너지는
    것은 물론이고 이벤트 시각 자체가 틀어진다.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._frame: npt.NDArray[np.uint8] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="rtsp", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3.0)

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def take(self) -> npt.NDArray[np.uint8] | None:
        """최근 프레임을 가져가고 자리를 비운다. 같은 프레임을 두 번 처리하지 않는다."""
        with self._lock:
            frame, self._frame = self._frame, None
            return frame

    def _loop(self) -> None:
        while not self._stop.is_set():
            capture = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
            if not capture.isOpened():
                self._connected.clear()
                log.warning("스트림을 열지 못했다 — %s (재시도)", self._url)
                capture.release()
                self._stop.wait(_RECONNECT_S)
                continue
            self._connected.set()
            log.info("스트림 연결 — %s", self._url)
            while not self._stop.is_set():
                ok, frame = capture.read()
                if not ok:
                    break
                with self._lock:
                    self._frame = np.asarray(frame, dtype=np.uint8)
            self._connected.clear()
            capture.release()
            log.warning("스트림이 끊겼다 — %s (재연결)", self._url)
            self._stop.wait(_RECONNECT_S)


@dataclass(slots=True)
class _Camera:
    """카메라 한 대의 실행 단위."""

    stream: StreamConfig
    reader: _LatestFrame
    pipeline: CameraPipeline
    frames: int = 0
    window_started_s: float = 0.0
    fps: float = 0.0

    def observe(self, at_s: float) -> None:
        """실측 처리율을 1초 창으로 갱신한다.

        **목표값(`decode.target_fps`)을 보고하지 않는다.** 노트북이 못 따라가고 있다는
        사실이 화면에서 사라지면 안 된다(§2.4 — 8 미만이면 대시보드 경고).
        """
        self.frames += 1
        elapsed = at_s - self.window_started_s
        if elapsed >= 1.0:
            self.fps = self.frames / elapsed
            self.frames = 0
            self.window_started_s = at_s


def _limit_threads(config: EdgeConfig) -> None:
    """OpenCV 도 같은 상한에 묶는다.

    `cv2` 는 자체 스레드 풀을 쓰며 기본값이 **논리 코어 전부**다. onnxruntime 만
    제한하면 레터박스·리사이즈·윤곽 추출이 나머지 코어를 다시 채워서 ffmpeg 송출이
    굶는다 — 상한을 한쪽에만 걸면 의미가 없다.
    """
    if config.runtime.intra_op_threads:
        cv2.setNumThreads(config.runtime.intra_op_threads)
        log.info("스레드 상한 %d (onnxruntime · OpenCV)", config.runtime.intra_op_threads)


def _build(config: EdgeConfig, stream: StreamConfig) -> CameraPipeline:
    letterbox = Letterbox(
        source_width=stream.width,
        source_height=stream.height,
        model_width=config.detect.imgsz[1],
        model_height=config.detect.imgsz[0],
    )
    depth: DepthEstimator | None = None
    if config.depth.model_path is not None:
        depth = DepthEstimator(
            config.depth,
            config.runtime,
            separation_max=config.depth.separation_max,
            variance_scale=config.depth.variance_scale,
        )
    else:
        log.warning("뎁스 모델이 없다 — FN-DET-11 검증이 돌지 않고 depth_verified 는 계속 false 다")
    return CameraPipeline(
        cam_id=stream.cam_id,
        config=config,
        letterbox=letterbox,
        detector=Detector(config.detect, config.runtime, letterbox),
        classifier=HelmetClassifier(config.classify, config.runtime),
        depth=depth,
    )


async def _load_setup(rest_url: str) -> Setup | None:
    try:
        return await fetch_setup(rest_url)
    except Exception:
        log.exception("서버 설정을 읽지 못했다 — %s", rest_url)
        return None


async def run(config: EdgeConfig, *, cam_ids: set[int] | None, clock: Clock) -> int:
    streams = [stream for stream in config.streams if cam_ids is None or stream.cam_id in cam_ids]
    if not streams:
        log.error("실행할 카메라가 없다 — --cam 값을 확인해라")
        return 1

    # 모델을 만들기 **전에** 건다. 세션이 만들어진 뒤에는 스레드 풀이 이미 잡혀 있다.
    _limit_threads(config)

    cameras = [
        _Camera(
            stream=stream,
            reader=_LatestFrame(stream.rtsp_sub),
            pipeline=_build(config, stream),
        )
        for stream in streams
    ]
    socket = EdgeSocket(config.server.ws_url)

    for camera in cameras:
        camera.reader.start()
    try:
        await _pump(config, cameras, socket, clock=clock)
    finally:
        for camera in cameras:
            camera.reader.stop()
        await socket.close()
    return 0


async def _pump(
    config: EdgeConfig,
    cameras: list[_Camera],
    socket: EdgeSocket,
    *,
    clock: Clock,
) -> None:
    """카메라들을 한 루프에서 돌린다.

    ★ **프레임을 기다리지 않는다.** 추론이 스트림보다 느리므로 큐가 아니라 최신
    프레임 하나를 가져다 쓰고, 없으면 잠깐 쉰다. 처리율은 곧 이 루프의 속도이며
    `heartbeat` 에 실측값 그대로 실린다.
    """
    connected = False
    setup: Setup | None = None
    setup_at = -_SETUP_REFRESH_S
    heartbeat_at = 0.0
    rates = _Rates()
    origin = clock.monotonic()
    idle_s = 1.0 / max(config.decode.target_fps, 1.0)

    while True:
        at_s = clock.monotonic() - origin

        if at_s - setup_at >= _SETUP_REFRESH_S:
            setup_at = at_s
            fresh = await _load_setup(config.server.rest_url)
            if fresh is not None:
                setup = fresh
                for camera in cameras:
                    camera.pipeline.apply(fresh)
                    if not camera.pipeline.ready:
                        log.warning(
                            "cam%d 에 캘리브레이션이 없다 — 좌표를 낼 수 없어 건너뛴다",
                            camera.stream.cam_id,
                        )

        if not connected:
            connected = await _connect(socket)

        worked = False
        for camera in cameras:
            frame = camera.reader.take()
            if frame is None or not camera.pipeline.ready:
                continue
            worked = True
            camera.observe(at_s)
            # ★ **추론을 이벤트 루프에서 직접 돌리지 않는다.**
            # `process()` 는 CPU 로 수 초가 걸리는 동기 함수다. 루프 안에서 부르면 그
            # 시간 동안 루프가 멎어 WebSocket 이 핑에 응답하지 못하고 서버가 연결을
            # 끊는다 — 실측으로 10초마다 끊겼다 붙기를 반복했고, 그 사이 heartbeat 가
            # 유실되어 대시보드에는 카메라가 `down` 으로 보였다.
            output = await asyncio.to_thread(
                camera.pipeline.process, frame, ts=clock.now(), at_s=at_s
            )
            outgoing: list[EdgeMessage] = [
                *([output.frame] if output.frame is not None else []),
                *output.candidates,
                *output.lost,
            ]
            for message in outgoing:
                if not await socket.send(message):
                    connected = False

        if setup is not None and at_s - heartbeat_at >= config.server.heartbeat_interval_s:
            heartbeat_at = at_s
            if not await socket.send(_heartbeat(cameras, rates, at_s=at_s, clock=clock)):
                connected = False

        if not worked:
            await asyncio.sleep(idle_s)
        else:
            # 다른 태스크(재연결·설정 조회)에 자리를 준다. 추론 자체가 수백 ms 라
            # 여기서 더 쉬면 처리율만 떨어진다.
            await asyncio.sleep(0)


async def _connect(socket: EdgeSocket) -> bool:
    try:
        await socket.connect()
    except OSError:
        log.warning("서버에 연결하지 못했다 — 다음 주기에 다시 시도한다")
        return False
    except Exception:
        log.exception("서버 연결 실패")
        return False
    return True


@dataclass(slots=True)
class _Rates:
    """`*_per_min` 을 **진짜 분당 비율**로 만든다.

    ★ 파이프라인이 세는 것은 시작 이후 누적이다. 그 값을 그대로 `cls_calls_per_min`
    에 실으면 시간이 갈수록 커지기만 해서, 대시보드의 「분당」이라는 이름이 거짓이 된다.
    직전 보고와의 차이를 경과 시간으로 나눈다.
    """

    at_s: float = 0.0
    cls_calls: int = 0
    depth_calls: int = 0

    def per_min(self, at_s: float, cls_calls: int, depth_calls: int) -> tuple[int, int]:
        elapsed = at_s - self.at_s
        if elapsed <= 0.0:
            return 0, 0
        rates = (
            round((cls_calls - self.cls_calls) * 60.0 / elapsed),
            round((depth_calls - self.depth_calls) * 60.0 / elapsed),
        )
        self.at_s, self.cls_calls, self.depth_calls = at_s, cls_calls, depth_calls
        return rates


def _heartbeat(cameras: list[_Camera], rates: _Rates, *, at_s: float, clock: Clock) -> HeartbeatMsg:
    """상태 보고(§2.4).

    ★ **시계 오차를 자기 신고하지 않는다.** 엣지에 NTP 측정 경로가 없으므로
    `synced=False` 로 보낸다 — 그러면 서버는 `edge_offset_ms` 를 `null` 로 둔다(§2.4).
    측정하지 않은 값을 0으로 보고하면 동기화된 적 없는 엣지가 완벽한 것으로 보인다.
    """
    stats = [camera.pipeline.stats() for camera in cameras]
    cls_per_min, depth_per_min = rates.per_min(
        at_s,
        sum(item.cls_calls for item in stats),
        sum(item.depth_calls for item in stats),
    )
    gated = sum(item.cls_gated_small for item in stats)
    if gated:
        # 크기 게이트에 걸려 안전모 판정을 못 한 횟수. 계약에 실을 자리가 없으므로
        # 로그로 드러낸다 — 조용하면 「위반이 없다」로 읽힌다(FN-DET-04).
        log.info("안전모 판정 불가(크롭 < cls_min_crop_px) 누적 %d회", gated)
    return HeartbeatMsg(
        # `type` 을 명시한다 — `exclude_unset` 이 설정하지 않은 필드를 빼기 때문이다.
        type="heartbeat",
        ts=clock.now(),
        cameras=[
            CameraHealth(
                cam_id=camera.stream.cam_id,
                sub_state="ok" if camera.reader.connected else "reconnecting",
                fps=round(camera.fps, 2),
            )
            for camera in cameras
        ],
        gpu_util=0.0,
        mem_used_mb=memory_used_mb(),
        cls_calls_per_min=cls_per_min,
        cls_cache_hit_rate=round(sum(item.cls_cache_hit_rate for item in stats) / len(stats), 3)
        if stats
        else 0.0,
        depth_calls_per_min=depth_per_min,
        clock=EdgeClock(offset_ms=0.0, synced=False),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS 엣지 러너 — 감지 후보를 서버로 올린다")
    parser.add_argument("--config", default=None, help="기본 edge/config.yaml")
    parser.add_argument("--cam", type=int, action="append", help="이 카메라만 (여러 번 가능)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.error("%s", exc)
        return 1

    try:
        return asyncio.run(
            run(config, cam_ids=set(args.cam) if args.cam else None, clock=RealClock())
        )
    except KeyboardInterrupt:
        log.info("중단")
        return 130


if __name__ == "__main__":
    sys.exit(main())
