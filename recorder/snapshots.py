"""스냅샷 버퍼 — 최근 프레임을 메모리에 들고 있는다. FN-REC-03 (기능명세서 §4.4)

**키프레임은 세그먼트 파일에서 뽑지 않는다.** 확정 시점의 프레임은 아직 어떤 파일에도
기록되지 않았고, 세그먼트에서 뽑으려면 최대 세그먼트 길이만큼 기다려야 한다. 그동안
이벤트 상세 화면(FN-UI-03)에 보여줄 그림이 없다. 실측으로도 1초 전 프레임을 요청하면
`GET /keyframe` 이 500 을 냈다.

그래서 REC 이 메인 스트림에서 **초당 1장**(`rec_snapshot_fps`)을 따로 뽑아 **최근
60초**(`rec_snapshot_window_s`)만 메모리에 들고 있는다. 확정 직후의 요청은 여기서
즉시 답하고, 그보다 오래된 시각만 세그먼트에서 추출한다.

초당 1장 JPEG 인코딩은 리먹스 부하에 비해 무시할 수준이고, 확정 시각과 최대 0.5초
차이는 안전 사건 판별에 영향을 주지 않는다(§4.4).

**녹화 프로세스와 분리한다.** 녹화 ffmpeg 은 `-c copy` 리먹스라 디코딩하지 않으므로
같은 프로세스에서 JPEG 을 뽑을 수 없다. 스냅샷용 ffmpeg 을 따로 띄우고, 그것이 죽어도
녹화는 멈추지 않는다 — 그림을 잃는 것과 증거 영상을 잃는 것은 무게가 다르다.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections import deque
from datetime import datetime, timedelta

from aegis_vision.clock import Clock
from recorder.config import RecSettings
from recorder.ffmpeg import require_ffmpeg

__all__ = ["SnapshotBuffer", "SnapshotSampler"]

log = logging.getLogger("recorder.snapshots")

#: JPEG 시작·끝 표식. `image2pipe` 는 프레임을 이어 붙여 흘려보내므로 직접 잘라야 한다.
_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"

#: 한 번에 읽는 크기. 1080p JPEG 이 대략 100~300KB 다.
_CHUNK = 65536

#: 스냅샷 프로세스 재시작 백오프.
_BACKOFF_START_S = 1.0
_BACKOFF_MAX_S = 30.0


class SnapshotBuffer:
    """카메라 한 대의 최근 스냅샷들. **순수 자료구조 — I/O 가 없다.**

    시각은 넣는 쪽이 `Clock` 에서 얻어 함께 넘긴다(CLAUDE.md 절대규칙 1).
    """

    def __init__(self, *, window_s: float, fps: float) -> None:
        if window_s <= 0 or fps <= 0:
            msg = f"window_s 와 fps 는 0보다 커야 한다: window_s={window_s!r} fps={fps!r}"
            raise ValueError(msg)
        self._window_s = window_s
        self._tolerance = timedelta(seconds=1.0 / fps)
        self._frames: deque[tuple[datetime, bytes]] = deque()

    @property
    def count(self) -> int:
        return len(self._frames)

    @property
    def oldest_at(self) -> datetime | None:
        return self._frames[0][0] if self._frames else None

    @property
    def newest_at(self) -> datetime | None:
        return self._frames[-1][0] if self._frames else None

    def add(self, at: datetime, payload: bytes) -> None:
        """스냅샷 한 장. 창을 넘어선 것은 그때 버린다."""
        self._frames.append((at, payload))
        cutoff = at - timedelta(seconds=self._window_s)
        while self._frames and self._frames[0][0] < cutoff:
            self._frames.popleft()

    def nearest(self, at: datetime) -> tuple[datetime, bytes] | None:
        """요청 시각에 가장 가까운 스냅샷. 샘플 간격 밖이면 `None`.

        **없는 것을 있는 척하지 않는다.** 간격(기본 1초)보다 멀면 그 시각은 버퍼가
        담고 있는 구간이 아니므로, 부르는 쪽이 세그먼트에서 뽑아야 한다. 가장 가까운
        것을 무조건 돌려주면 30초 전 사건의 그림으로 지금을 설명하게 된다.
        """
        if not self._frames:
            return None
        best = min(self._frames, key=lambda item: abs(item[0] - at))
        return best if abs(best[0] - at) <= self._tolerance else None


class SnapshotSampler:
    """카메라 한 대의 스냅샷 ffmpeg 을 살려두고 버퍼를 채운다."""

    def __init__(self, cam_id: int, settings: RecSettings, clock: Clock) -> None:
        self._cam_id = cam_id
        self._settings = settings
        self._clock = clock
        self._buffer = SnapshotBuffer(
            window_s=float(settings.rec_snapshot_window_s),
            fps=float(settings.rec_snapshot_fps),
        )
        self._process: asyncio.subprocess.Process | None = None
        self._stopping = False

    @property
    def buffer(self) -> SnapshotBuffer:
        return self._buffer

    def _argv(self, ffmpeg: str) -> list[str]:
        # **비용은 인코딩이 아니라 디코딩이다.** 초당 1장을 뽑아도 `fps` 필터에 넣으려면
        # 모든 프레임을 풀어야 한다(실측: 1080p 한 대에 코어 33%). 젯슨은 NVDEC 이
        # 받아주지만 소프트웨어 디코딩을 쓰는 개발 기계에서는 그대로 CPU 다.
        # `REC_SNAPSHOT_KEYFRAMES_ONLY` 를 켜면 키프레임만 풀어 코어 7% 로 내려간다
        # (대신 샘플 간격이 GOP 를 따른다 — `recorder/config.py` 참고).
        decode = ["-skip_frame", "nokey"] if self._settings.rec_snapshot_keyframes_only else []
        return [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "warning",
            "-rtsp_transport", "tcp",
            *decode,
            "-i", self._settings.main_stream_url(self._cam_id),
            "-an",
            # 초당 `rec_snapshot_fps` 장. 그 이상 디코딩하지 않는다.
            "-vf", f"fps={self._settings.rec_snapshot_fps}",
            "-q:v", "2",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "pipe:1",
        ]  # fmt: skip

    def _keep_running(self) -> bool:
        return not self._stopping

    async def run(self) -> None:
        """죽으면 백오프를 두고 다시 띄운다. 취소될 때까지 돈다."""
        ffmpeg = require_ffmpeg()
        backoff = _BACKOFF_START_S
        while self._keep_running():
            try:
                await self._run_once(ffmpeg)
            except asyncio.CancelledError:
                await self._terminate()
                raise
            if not self._keep_running():
                return
            # 스냅샷이 끊긴 것은 녹화가 끊긴 것과 다르다 — 경고로 남기되 녹화 감독
            # 루프처럼 시끄럽게 굴지 않는다.
            log.warning(
                "cam%d 스냅샷 프로세스가 끝났다. %.1f초 뒤 재시도한다.", self._cam_id, backoff
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_S)

    async def _run_once(self, ffmpeg: str) -> None:
        self._process = await asyncio.create_subprocess_exec(
            *self._argv(ffmpeg),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=dict(os.environ),
        )
        log.info(
            "cam%d 스냅샷 시작 — 초당 %d장 · 최근 %d초",
            self._cam_id,
            self._settings.rec_snapshot_fps,
            self._settings.rec_snapshot_window_s,
        )
        if self._process.stdout is not None:
            await self._consume(self._process.stdout)
        await self._process.wait()

    async def _consume(self, stream: asyncio.StreamReader) -> None:
        """`image2pipe` 스트림을 JPEG 단위로 잘라 버퍼에 넣는다.

        **시각은 읽은 순간의 `Clock` 값이다.** ffmpeg 은 프레임의 촬영 시각을 파이프에
        실어주지 않으므로 도착 시각으로 대신하며, 그 오차는 §4.4 가 허용한 0.5초 안이다.
        """
        pending = bytearray()
        while True:
            chunk = await stream.read(_CHUNK)
            if not chunk:
                return
            pending += chunk
            while True:
                start = pending.find(_SOI)
                if start < 0:
                    pending.clear()
                    break
                end = pending.find(_EOI, start + 2)
                if end < 0:
                    del pending[:start]
                    break
                frame = bytes(pending[start : end + 2])
                del pending[: end + 2]
                self._buffer.add(self._clock.now(), frame)

    async def stop(self) -> None:
        self._stopping = True
        await self._terminate()

    async def _terminate(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        process.kill()
        with contextlib.suppress(ProcessLookupError):
            await process.wait()
