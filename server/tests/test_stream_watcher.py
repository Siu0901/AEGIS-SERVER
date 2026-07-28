"""메인 스트림 상태 전이와 `system` 발행 (FN-SYS-01 · API명세서 §5.3).

시간은 전부 `FakeClock` 으로 감는다 — `down_after_seconds` 를 실제로 기다리면
테스트가 느려지고, 느린 테스트는 결국 안 돌리게 된다(CLAUDE.md 절대규칙 1).
"""

from __future__ import annotations

import asyncio

from aegis_contracts import CameraSystemMsg
from aegis_vision.clock import FakeClock
from server.infra.stream.mediamtx import MediaMtxUnavailableError, PathState
from server.infra.stream.watcher import StreamWatcher, main_path


class FakePaths:
    """`MediaMtxClient` 대역. `ready` 인 카메라 집합을 바꿔가며 관측을 흉내 낸다."""

    def __init__(self, ready: set[int]) -> None:
        self.ready = set(ready)
        self.available = True

    async def paths(self) -> dict[str, PathState]:
        if not self.available:
            msg = "mediamtx 제어 API 실패 (테스트)"
            raise MediaMtxUnavailableError(msg)
        return {
            main_path(cam_id): PathState(name=main_path(cam_id), ready=True)
            for cam_id in self.ready
        }

    async def aclose(self) -> None:
        return None


def _watcher(
    paths: FakePaths, clock: FakeClock, sink: list[CameraSystemMsg]
) -> tuple[StreamWatcher, FakePaths]:
    async def publish(message: CameraSystemMsg) -> None:
        sink.append(message)

    watcher = StreamWatcher(
        client=paths,  # type: ignore[arg-type]
        cam_ids=[1, 2],
        clock=clock,
        publish=publish,
        poll_seconds=1.0,
        down_after_seconds=5.0,
    )
    return watcher, paths


async def _poll(watcher: StreamWatcher, paths: FakePaths) -> None:
    """폴링 1회분. `run()` 의 루프 대신 관측만 한 번 밀어 넣는다."""
    try:
        found = await paths.paths()
    except MediaMtxUnavailableError:
        observed = dict.fromkeys([1, 2], False)
    else:
        observed = {cam_id: main_path(cam_id) in found for cam_id in (1, 2)}
    await watcher.observe(observed)


def test_first_observation_of_a_live_stream_publishes_ok() -> None:
    sink: list[CameraSystemMsg] = []
    clock = FakeClock()
    watcher, paths = _watcher(FakePaths({1, 2}), clock, sink)

    asyncio.run(_poll(watcher, paths))

    assert watcher.states() == {1: "ok", 2: "ok"}
    assert {message.cam_id for message in sink} == {1, 2}
    assert all(message.stream == "main" for message in sink)
    assert all(message.state == "ok" for message in sink)


def test_unchanged_state_publishes_nothing() -> None:
    """§5.3 — 변화한 구성요소 하나만 보낸다. 매 폴링마다 보내면 대시보드가 묻힌다."""
    sink: list[CameraSystemMsg] = []
    clock = FakeClock()
    watcher, paths = _watcher(FakePaths({1, 2}), clock, sink)

    asyncio.run(_poll(watcher, paths))
    sink.clear()
    clock.advance(1.0)
    asyncio.run(_poll(watcher, paths))

    assert sink == []


def test_loss_goes_reconnecting_then_down() -> None:
    sink: list[CameraSystemMsg] = []
    clock = FakeClock()
    watcher, paths = _watcher(FakePaths({1, 2}), clock, sink)
    asyncio.run(_poll(watcher, paths))
    sink.clear()

    # cam2 송출만 중단.
    paths.ready = {1}
    clock.advance(1.0)
    asyncio.run(_poll(watcher, paths))

    assert watcher.states() == {1: "ok", 2: "reconnecting"}
    assert [(message.cam_id, message.state) for message in sink] == [(2, "reconnecting")]

    # 유예를 넘기면 down 으로 내린다.
    sink.clear()
    clock.advance(6.0)
    asyncio.run(_poll(watcher, paths))

    assert watcher.states()[2] == "down"
    assert [(message.cam_id, message.state) for message in sink] == [(2, "down")]


def test_stream_recovers_on_its_own() -> None:
    sink: list[CameraSystemMsg] = []
    clock = FakeClock()
    watcher, paths = _watcher(FakePaths({1, 2}), clock, sink)
    asyncio.run(_poll(watcher, paths))

    paths.ready = {1}
    clock.advance(1.0)
    asyncio.run(_poll(watcher, paths))
    clock.advance(6.0)
    asyncio.run(_poll(watcher, paths))
    assert watcher.states()[2] == "down"

    paths.ready = {1, 2}
    sink.clear()
    clock.advance(1.0)
    asyncio.run(_poll(watcher, paths))

    assert watcher.states() == {1: "ok", 2: "ok"}
    assert [(message.cam_id, message.state) for message in sink] == [(2, "ok")]


def test_control_api_failure_does_not_leave_cameras_reported_as_ok() -> None:
    """mediamtx 가 죽으면 카메라 상태를 알 수 없다.

    마지막으로 본 `ok` 를 계속 들고 있으면 대시보드가 죽은 카메라를 정상으로 그린다.
    """
    sink: list[CameraSystemMsg] = []
    clock = FakeClock()
    watcher, paths = _watcher(FakePaths({1, 2}), clock, sink)
    asyncio.run(_poll(watcher, paths))

    paths.available = False
    clock.advance(1.0)
    asyncio.run(_poll(watcher, paths))

    assert set(watcher.states().values()) == {"reconnecting"}


def test_initial_state_is_down_before_the_first_poll() -> None:
    """폴링 전에 `GET /system/status` 가 오면 없는 확신을 팔지 않는다."""
    sink: list[CameraSystemMsg] = []
    watcher, _ = _watcher(FakePaths({1, 2}), FakeClock(), sink)

    assert watcher.states() == {1: "down", 2: "down"}
