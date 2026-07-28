"""메인 스트림 상태 감시와 변화 통지 (FN-SYS-01 · API명세서 §5.3).

mediamtx 를 폴링해 `cam{N}/main` 이 살아 있는지 보고, **변화가 있을 때만**
`system` 메시지를 발행한다. 매 폴링마다 보내면 대시보드가 의미 없는 메시지에 묻힌다
(§5.3 "변화한 구성요소 하나만 보낸다").

`StreamState` 세 값의 뜻을 그대로 지킨다(§4.6).

| 값 | 언제 |
|---|---|
| `ok` | 퍼블리셔가 붙어 있고 재송출 중 |
| `reconnecting` | 끊겼고 아직 `stream_down_after_seconds` 가 지나지 않았다 |
| `down` | 그 시간이 지나도록 돌아오지 않았다 |

끊기자마자 `down` 으로 내리지 않는 이유: 카메라 재시작이나 순간 패킷 유실로 1~2초
끊기는 일은 흔하고, 그때마다 `down` 을 띄우면 화면이 늑대소년이 된다. 반대로 계속
`reconnecting` 으로만 두면 진짜 장애를 못 알아본다.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aegis_contracts import CameraSystemMsg
from aegis_contracts.enums import StreamState
from aegis_vision.clock import Clock
from server.infra.stream.mediamtx import MediaMtxClient, MediaMtxUnavailableError

__all__ = ["StreamWatcher", "main_path"]

log = logging.getLogger("server.stream.watcher")

#: 제어 API 가 죽었을 때의 재시도 백오프. 카메라 끊김(경로가 not ready)과는 다른 사건이라
#: 폴링 주기를 늦춰도 카메라 감지가 느려지지 않는다.
_BACKOFF_START_S = 1.0
_BACKOFF_MAX_S = 15.0

Publish = Callable[[CameraSystemMsg], Awaitable[None]]


def main_path(cam_id: int) -> str:
    """mediamtx 경로명. `deploy/mediamtx.yml` 과 `deploy/fake_cams.py` 가 쓰는 것과 같다."""
    return f"cam{cam_id}/main"


@dataclass
class _Track:
    """카메라 하나의 관측 상태."""

    state: StreamState = "down"
    """아직 한 번도 관측하지 못한 상태를 `ok` 로 시작하지 않는다 —
    폴링 전에 `GET /system/status` 가 오면 없는 확신을 파는 셈이 된다."""

    lost_at: float | None = None
    """`reconnecting` 이 시작된 단조 시각."""

    attempts: int = 0
    """끊긴 뒤 다시 확인한 횟수. `detail` 에 실어 사람이 상황을 가늠하게 한다."""


class StreamWatcher:
    """mediamtx 를 폴링해 카메라 메인 스트림 상태를 관측한다."""

    def __init__(
        self,
        *,
        client: MediaMtxClient,
        cam_ids: list[int],
        clock: Clock,
        publish: Publish,
        poll_seconds: float = 1.0,
        down_after_seconds: float = 5.0,
    ) -> None:
        self._client = client
        self._clock = clock
        self._publish = publish
        self._poll_seconds = poll_seconds
        self._down_after_seconds = down_after_seconds
        self._tracks = {cam_id: _Track() for cam_id in cam_ids}
        self._task: asyncio.Task[None] | None = None

    def states(self) -> dict[int, StreamState]:
        """`GET /system/status` 의 `cameras[].main_state` 원천."""
        return {cam_id: track.state for cam_id, track in self._tracks.items()}

    async def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="stream-watcher")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        await self._client.aclose()

    async def run(self) -> None:
        backoff = _BACKOFF_START_S
        while True:
            try:
                paths = await self._client.paths()
            except MediaMtxUnavailableError as exc:
                # 제어 API 가 죽었으면 카메라 상태를 알 수 없다. **모른다는 사실을
                # 그대로 반영한다** — 마지막으로 본 값을 계속 ok 로 들고 있으면
                # 대시보드가 죽은 카메라를 정상으로 그린다.
                log.warning("%s (%.1f초 뒤 재시도)", exc, backoff)
                await self.observe(dict.fromkeys(self._tracks, False))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX_S)
                continue

            backoff = _BACKOFF_START_S
            observed = {
                cam_id: main_path(cam_id) in paths and paths[main_path(cam_id)].ready
                for cam_id in self._tracks
            }
            await self.observe(observed)
            await asyncio.sleep(self._poll_seconds)

    async def observe(self, observed: dict[int, bool]) -> None:
        """관측 1회분을 반영하고 변화분만 발행한다.

        폴링 루프(`run`)와 분리해 둔 이유는 검증 때문이다. `down_after_seconds` 를
        실제로 기다리는 테스트는 느려서 결국 안 돌리게 되고, 그러면 상태 전이가
        검증되지 않은 채 남는다.
        """
        for cam_id, ready in observed.items():
            track = self._tracks[cam_id]
            previous = track.state
            detail = self._advance(track, ready=ready)
            if track.state != previous:
                log.info("cam%d main %s -> %s (%s)", cam_id, previous, track.state, detail)
                await self._publish(
                    CameraSystemMsg(
                        cam_id=cam_id,
                        stream="main",
                        state=track.state,
                        detail=detail,
                        at=self._clock.now(),
                    )
                )

    def _advance(self, track: _Track, *, ready: bool) -> str:
        """상태 전이. `detail` 문구를 돌려준다."""
        if ready:
            track.lost_at = None
            track.attempts = 0
            track.state = "ok"
            return "메인 스트림 정상"

        now = self._clock.monotonic()
        if track.lost_at is None:
            track.lost_at = now
            track.attempts = 0
        track.attempts += 1

        elapsed = now - track.lost_at
        if elapsed >= self._down_after_seconds:
            track.state = "down"
            return f"메인 스트림 끊김 {elapsed:.0f}초 경과 (재연결 시도 {track.attempts}회)"
        track.state = "reconnecting"
        return f"RTSP 재연결 시도 {track.attempts}회"
