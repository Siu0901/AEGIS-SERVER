"""메인 스트림 구독과 세그먼트 녹화 (FN-REC-02).

카메라 하나당 ffmpeg 하나가 RTSP **메인 스트림만** 구독해 10초 세그먼트로 쌓는다.
서브는 추론 전용이므로 녹화하지 않는다(API명세서 §4.7 녹화 규격).

**디코딩하지 않는다.** `-c copy` 리먹스여야 GPU 추론 예산에 영향이 없고, 그것이 녹화를
엣지 SSD 로 분리한 근거 자체다(기능명세서 §4.4).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import datetime, timedelta

from aegis_vision.clock import Clock
from recorder.config import RecSettings
from recorder.ffmpeg import require_ffmpeg
from recorder.segments import day_dir, ffmpeg_output_pattern

__all__ = ["CameraRecorder"]

log = logging.getLogger("recorder.capture")

#: 재연결 백오프. 카메라가 잠깐 끊긴 것과 영영 없는 것을 같은 속도로 두드리지 않는다.
_BACKOFF_START_S = 1.0
_BACKOFF_MAX_S = 30.0

#: 이만큼 버텨낸 실행은 "성공한 연결"로 보고 백오프를 되돌린다.
_BACKOFF_RESET_AFTER_S = 60.0


class CameraRecorder:
    """카메라 한 대의 ffmpeg 녹화 프로세스를 살려두는 감독자."""

    def __init__(self, cam_id: int, settings: RecSettings, clock: Clock) -> None:
        self._cam_id = cam_id
        self._settings = settings
        self._clock = clock
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: datetime | None = None
        self._stopping = False

    @property
    def cam_id(self) -> int:
        return self._cam_id

    @property
    def started_at(self) -> datetime | None:
        """현재 ffmpeg 프로세스가 뜬 시각. 죽어 있으면 `None`."""
        return self._started_at

    def is_alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def is_recording(self, last_segment_at: datetime | None) -> bool:
        """§4.7 `cameras[].recording`.

        프로세스가 살아 있는 것만으로는 부족하다. RTSP 가 끊겨도 ffmpeg 이 곧바로
        죽지 않고 매달려 있는 경우가 있어서, **세그먼트가 실제로 갱신되고 있는지**까지
        본다. 녹화가 멈춘 것을 녹화 중이라고 보고하면 그 시간대의 클립이 존재한다고
        믿게 되고, 이벤트 증거가 없다는 사실이 나중에야 드러난다.
        """
        if not self.is_alive() or self._started_at is None:
            return False
        grace = timedelta(seconds=self._settings.rec_segment_seconds * 3)
        newest = max(filter(None, (self._started_at, last_segment_at)))
        return self._clock.now() - newest <= grace

    # -- 실행 --------------------------------------------------------------

    def ensure_day_dirs(self) -> None:
        """오늘·내일(UTC) 날짜 디렉토리를 미리 만든다.

        ffmpeg 8.1 의 `segment` muxer 에는 `strftime_mkdir` 이 없다. 디렉토리가 없으면
        `Failed to open segment` 로 즉사하므로, 자정 롤오버 직전에 녹화가 통째로 끊기지
        않게 하루치를 앞서 만들어 둔다. 감독 루프와 보존 스윕 양쪽에서 호출한다.
        """
        now = self._clock.now()
        root = self._settings.rec_media_root
        for moment in (now, now + timedelta(days=1)):
            day_dir(root, self._cam_id, moment).mkdir(parents=True, exist_ok=True)

    def _argv(self, ffmpeg: str) -> list[str]:
        settings = self._settings
        return [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "warning",
            # RTSP 는 UDP 기본이라 1080p 에서 패킷 유실이 쉽게 난다. TCP 로 고정한다.
            "-rtsp_transport", "tcp",
            "-i", settings.main_stream_url(self._cam_id),
            "-an",
            # **리먹스.** 재인코딩하면 GPU 예산이 녹화로 새어 나간다.
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(settings.rec_segment_seconds),
            # 세그먼트 경계를 벽시계의 10초 배수에 맞춘다. 파일명이 곧 시각이므로
            # 구간 추출 계산이 단순해지고, 재시작해도 격자가 어긋나지 않는다.
            "-segment_atclocktime", "1",
            "-reset_timestamps", "1",
            "-segment_format", "mp4",
            "-strftime", "1",
            ffmpeg_output_pattern(settings.rec_media_root, self._cam_id),
        ]  # fmt: skip

    def _keep_running(self) -> bool:
        """`stop()` 이 불렸는지. 메서드로 감싼 이유는 `self._stopping` 을 직접 보면
        타입 검사기가 await 를 건너뛰고 값이 안 변한다고 좁혀 버리기 때문이다."""
        return not self._stopping

    async def run(self) -> None:
        """ffmpeg 이 죽으면 백오프를 두고 다시 띄운다. 취소될 때까지 돈다."""
        ffmpeg = require_ffmpeg()
        backoff = _BACKOFF_START_S
        while self._keep_running():
            self.ensure_day_dirs()
            started = self._clock.monotonic()
            try:
                await self._run_once(ffmpeg)
            except asyncio.CancelledError:
                await self._terminate()
                raise
            if not self._keep_running():
                return
            lasted = self._clock.monotonic() - started
            if lasted >= _BACKOFF_RESET_AFTER_S:
                backoff = _BACKOFF_START_S
            log.warning(
                "cam%d 녹화 프로세스가 %.1f초 만에 끝났다. %.1f초 뒤 재시도한다.",
                self._cam_id,
                lasted,
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_S)

    async def _run_once(self, ffmpeg: str) -> None:
        argv = self._argv(ffmpeg)
        log.info("cam%d 녹화 시작 — %s", self._cam_id, self._settings.main_stream_url(self._cam_id))
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            # `-nostdin` 을 쓰지 않고 파이프를 열어둔다. 종료할 때 'q' 를 보내야
            # ffmpeg 이 마지막 세그먼트의 moov 를 써넣고 정상적으로 닫는다.
            # 강제 종료하면 그 파일은 재생 불가가 되고, 하필 그 10초가 이벤트
            # 구간일 수 있다.
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=_utc_env(),
        )
        self._started_at = self._clock.now()
        stderr = await self._drain_stderr(self._process)
        await self._process.wait()
        self._started_at = None
        if self._process.returncode != 0 and stderr:
            log.warning("cam%d ffmpeg stderr: %s", self._cam_id, stderr)

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> str:
        """ffmpeg 의 stderr 를 끝까지 읽는다.

        읽지 않으면 파이프 버퍼가 차서 ffmpeg 이 멈춘다 — 녹화가 조용히 정지하는 가장
        흔한 원인이다. 마지막 몇 줄만 남겨 로그로 올린다.
        """
        if process.stderr is None:
            return ""
        tail: list[str] = []
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                tail.append(text)
                del tail[:-8]
        return "\n".join(tail)

    async def stop(self) -> None:
        self._stopping = True
        await self._terminate()

    async def _terminate(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        if process.stdin is not None and not process.stdin.is_closing():
            with contextlib.suppress(OSError, BrokenPipeError):
                process.stdin.write(b"q")
                await process.stdin.drain()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            log.warning("cam%d ffmpeg 가 'q' 에 응답하지 않는다. 강제 종료한다.", self._cam_id)
            process.kill()
            await process.wait()


def _utc_env() -> dict[str, str]:
    """자식 ffmpeg 의 `-strftime` 이 **UTC** 로 파일명을 찍게 만든다.

    ffmpeg 의 strftime 은 로컬 시각을 쓴다. 저장은 UTC 라는 §1.2 규약을 파일명에도
    적용해야 하고, 그러지 않으면 서머타임이나 시간대가 다른 현장에서 파일명이 겹치거나
    되감긴다. 그때 지워지는 것은 남의 녹화다.
    """
    env = dict(os.environ)
    env["TZ"] = "UTC0"
    return env
