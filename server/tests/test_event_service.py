"""상태 전이가 **화면까지** 도달하는지 (API명세서 §5.1 · §5.2).

상태머신이 옳게 판정해도 오버레이가 그것을 반영하지 않으면 관제 화면은 시정된
사람을 계속 적색으로 그린다. 여기서 보는 것은 그 연결이다 —
`alert_state` 가 `candidate` → `alerted` → (이벤트 없음)`null` 로 흐르는가.

재시작 복구도 함께 본다. 복구하지 않으면 열려 있던 이벤트가 어떤 전이도 받지 못해
시정률 분모에 영원히 미해소로 남는다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from aegis_contracts import (
    CandidateMsg,
    EventStatus,
    FrameMsg,
    Policies,
    SpecModel,
)
from aegis_vision.clock import FakeClock
from server.app.event_service import EventService
from server.domain.event_machine import EventMachine
from server.domain.overlay import LiveTracks, compose_overlay

from .conftest import FakeEventStore

START = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)

#: 엣지가 카메라당 올리는 프레임 간격 (FN-DET-01 — 8fps 이상).
STEP_S = 0.125


def person(at_s: float, helmet: str) -> FrameMsg:
    body: dict[str, Any] = {
        "type": "frame",
        "cam_id": 1,
        "ts": START + timedelta(seconds=at_s),
        "objects": [
            {
                "class": "person",
                "track_id": 3,
                "conf": 0.91,
                "bbox": [0.197, 0.364, 0.273, 0.764],
                "helmet": helmet,
                "helmet_conf": 0.88,
                "foot_point": [0.235, 0.762],
                "foot_point_m": [4.21, 7.85],
                "foot_conf": 0.88,
                "posture": "standing",
                "height_ratio": 0.97,
                "axis_angle_deg": 8.2,
                "stillness_s": 0.4,
                "in_zone": "forklift_lane",
            }
        ],
    }
    return FrameMsg.model_validate(body)


def candidate(at_s: float) -> CandidateMsg:
    body: dict[str, Any] = {
        "type": "candidate",
        "cam_id": 1,
        "ts": START + timedelta(seconds=at_s),
        "track_id": 3,
        "violation_type": "no_helmet",
        "zone_id": "forklift_lane",
        "bbox": [0.197, 0.364, 0.273, 0.764],
        "conf": 0.91,
        "foot_point_m": [4.21, 7.85],
        "foot_conf": 0.88,
        "helmet": "off",
        "helmet_conf": 0.88,
        "posture": "standing",
        "observed_ms": 500,
        "nearby": [],
    }
    return CandidateMsg.model_validate(body)


class Harness:
    """상태머신 + 저장소 + 오버레이 트랙을 한 벌로 묶은 것."""

    def __init__(self, store: FakeEventStore | None = None) -> None:
        self.clock = FakeClock(START)
        self.tracks = LiveTracks()
        self.store = store or FakeEventStore()
        self.published: list[SpecModel] = []
        self.machine = EventMachine(clock=self.clock, policies=Policies())
        self.service = EventService(
            machine=self.machine,
            tracks=self.tracks,
            publish=self._publish,
            clock=self.clock,
            store=self.store,
        )

    async def _publish(self, message: SpecModel) -> None:
        self.published.append(message)

    def alert_state(self, at_s: float, helmet: str) -> str | None:
        """프레임 한 장을 흘리고, 그 프레임으로 그린 오버레이의 `alert_state` 를 본다."""
        frame = person(at_s, helmet)
        self.clock.set(frame.ts)
        asyncio.run(self.service.on_frame(frame))
        overlay = compose_overlay(frame, self.tracks)
        obj = overlay.objects[0]
        return obj.alert_state

    def run_until(self, start_s: float, end_s: float, helmet: str) -> None:
        at_s = start_s
        while at_s <= end_s + 1e-9:
            self.alert_state(at_s, helmet)
            at_s = round(at_s + STEP_S, 6)


def status_of(harness: Harness) -> EventStatus:
    """저장된 첫 이벤트의 현재 상태. 매번 새로 읽어 좁혀진 타입에 걸리지 않게 한다."""
    return harness.store.items[0].status


def test_alert_state_walks_from_candidate_to_alerted_to_nothing() -> None:
    """FN-UI-02 가 화면에서 보여줘야 하는 흐름 그대로다."""
    harness = Harness()

    assert harness.alert_state(0.0, "off") is None
    asyncio.run(harness.service.on_candidate(candidate(0.5)))

    # 확정 전 — 적색이 아니라 「확정 중」이다(§5.1).
    assert harness.alert_state(0.625, "off") == "candidate"
    harness.run_until(0.75, 3.375, "off")
    assert harness.alert_state(3.5, "off") == "alerted"

    # 안전모 착용 → 해소 타이머 10초.
    harness.run_until(3.625, 13.375, "on")
    assert harness.alert_state(13.5, "on") == "alerted"

    # 해소되면 진행 중 이벤트가 없어지므로 `null` 이다 — 박스가 정상 색으로 돌아간다.
    assert harness.alert_state(13.625, "on") is None
    assert harness.store.items[0].status is EventStatus.RESOLVED


def test_resolved_event_lets_the_same_track_start_a_new_event() -> None:
    """종결된 이벤트가 병합 키를 붙잡고 있으면 다음 위반이 기록되지 않는다."""
    harness = Harness()
    asyncio.run(harness.service.on_candidate(candidate(0.5)))
    harness.run_until(0.625, 13.625, "off")
    harness.run_until(13.75, 24.0, "on")
    assert harness.store.items[0].status is EventStatus.RESOLVED

    asyncio.run(harness.service.on_candidate(candidate(24.5)))
    assert len(harness.store.created) == 2
    assert harness.store.created[1].event_id != harness.store.created[0].event_id


def test_restart_recovers_open_events_so_they_can_still_be_closed() -> None:
    """복구하지 않으면 재시작 한 번이 그 이벤트들을 영원히 미해소로 남긴다."""
    first = Harness()
    asyncio.run(first.service.on_candidate(candidate(0.5)))
    first.run_until(0.625, 4.0, "off")
    assert first.store.items[0].status is EventStatus.ALERTED

    # 같은 저장소를 물린 새 프로세스.
    second = Harness(store=first.store)
    second.clock.set(START + timedelta(seconds=4.0))
    asyncio.run(second.service.start())
    assert [event.status for event in second.machine.snapshot()] == [EventStatus.ALERTED]

    # 타이머는 0부터 다시 센다 — 복구 직후 10초를 채워야 해소된다.
    second.run_until(4.125, 14.0, "on")
    assert status_of(second) is EventStatus.ALERTED
    second.run_until(14.125, 14.25, "on")
    assert status_of(second) is EventStatus.RESOLVED
