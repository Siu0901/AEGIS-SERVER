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
    EventPatchRequest,
    EventStatus,
    FrameMsg,
    Policies,
    SpecModel,
    ViolationType,
)
from aegis_contracts.enums import AlertLevel
from aegis_vision.clock import FakeClock
from server.app.alert_service import AlertSink
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
                "nearby": [],
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

    def __init__(
        self,
        store: FakeEventStore | None = None,
        alerts: AlertSink | None = None,
    ) -> None:
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
            alerts=alerts,
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


def test_re_alert_updates_last_alerted_at_and_never_the_first_one() -> None:
    """§5.2 · §6 — `alerted_at` 은 최초로 고정, `last_alerted_at` 만 갱신된다.

    재경고마다 `alerted_at` 을 덮으면 `resolution_sec`(= `alerted_at → resolved_at`)이
    마지막 방송 기준으로 줄어 **시정률이 부풀려진다.** 두 컬럼이 분리된 이유다.
    """
    harness = Harness()
    asyncio.run(harness.service.on_candidate(candidate(0.5)))
    harness.run_until(0.625, 3.5, "off")
    first_alert = harness.store.items[0].alerted_at
    assert first_alert is not None

    # 쿨다운 30초 → 재경고.
    harness.run_until(3.625, 34.0, "off")
    assert status_of(harness) is EventStatus.RE_ALERTED

    stamps = [changes for _, changes in harness.store.updates if "last_alerted_at" in changes]
    assert len(stamps) == 2, "확정과 재경고 두 번 모두 최근 경고 시각을 남겨야 한다"
    assert stamps[0]["last_alerted_at"] < stamps[1]["last_alerted_at"]

    # 재경고 갱신에는 `alerted_at` 이 아예 실리지 않는다.
    assert "alerted_at" not in stamps[1]
    assert harness.store.items[0].alerted_at == first_alert


def test_manual_note_is_stored_not_only_logged() -> None:
    """§4.1 `PATCH` 의 `note` 는 §6 `events.note` 에 남는다.

    저장하지 않으면 오탐 판단의 근거가 다시 조회했을 때 사라진다.
    """
    harness = Harness()
    asyncio.run(harness.service.on_candidate(candidate(0.5)))
    harness.run_until(0.625, 3.5, "off")
    event_id = harness.store.items[0].event_id

    asyncio.run(
        harness.service.patch(
            event_id,
            EventPatchRequest(is_false_positive=True, note="허리 굽혀 작업 중이었음"),
        )
    )
    assert harness.store.notes[event_id] == "허리 굽혀 작업 중이었음"


def test_candidate_that_disappears_is_kept_as_dropped() -> None:
    """§4.2 — 확정 전 소멸은 **레코드를 남긴다.** 지우면 튜닝 근거가 사라진다."""
    harness = Harness()
    asyncio.run(harness.service.on_candidate(candidate(0.5)))
    # 확정(3초)에 닿기 전에 위반이 사라지고, 소멸이 3초 이어진다.
    harness.run_until(0.625, 2.0, "off")
    harness.run_until(2.125, 5.5, "on")

    assert status_of(harness) is EventStatus.DROPPED
    assert harness.store.items[0].alert_count == 0
    # 종결됐으므로 병합 키가 풀린다 — 같은 트랙의 다음 위반이 새 이벤트를 만든다.
    assert harness.machine.open_events(1, 3) == {}
    asyncio.run(harness.service.on_candidate(candidate(6.0)))
    assert len(harness.store.created) == 2


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


# --- §4.8 방송 없이 확정된 이벤트 -------------------------------------------


class SilentSink:
    """일시중지 중인 경고 집행자 대역 — `fire` 가 `False` 를 돌려준다.

    `AlertService` 를 통째로 끼우지 않는 이유: 여기서 보는 것은 **집행 계층이 그
    반환값을 기록하는가**이고, 무엇이 소리를 냈는지는 `test_alert_service.py` 의 일이다.
    """

    def __init__(self, *, dispatched: bool) -> None:
        self.dispatched = dispatched
        self.calls = 0

    async def fire(self, intent: object) -> bool:
        del intent
        self.calls += 1
        return self.dispatched

    def severity_map(self) -> dict[ViolationType, AlertLevel]:
        return {}


def confirm(harness: Harness) -> None:
    """후보 하나를 올리고 확정(3초)까지 프레임을 흘린다."""
    asyncio.run(harness.service.on_candidate(candidate(0.5)))
    harness.run_until(0.0, 4.0, "off")


def test_a_muted_alert_marks_the_event_as_suppressed() -> None:
    """★ §4.8 — 방송이 나가지 않았다는 사실이 **DB 에 남아야** 한다.

    남지 않으면 그 이벤트가 미시정으로 집계되어 시정률이 부당하게 낮아진다.
    화면도 "왜 이 이벤트가 지표에 없나"를 설명할 수 없다.
    """
    sink = SilentSink(dispatched=False)
    harness = Harness(alerts=sink)

    confirm(harness)

    assert sink.calls == 1
    assert status_of(harness) is EventStatus.ALERTED
    assert harness.store.items[0].alert_suppressed is True


def test_a_dispatched_alert_leaves_the_event_in_the_population() -> None:
    """정상 경로에서는 이 칸을 건드리지 않는다 — 기본값이 「방송이 나갔다」다."""
    sink = SilentSink(dispatched=True)
    harness = Harness(alerts=sink)

    confirm(harness)

    assert sink.calls == 1
    assert harness.store.items[0].alert_suppressed is False


# --------------------------------------------------------------------------
# ★ §2.1 — 근접 해소는 `frame.nearby[].dist_m` 을 본다
# --------------------------------------------------------------------------


def proximity_frame(at_s: float, dist_m: float | None) -> FrameMsg:
    """지게차가 `dist_m` 만큼 떨어져 있는 프레임. `None` 이면 화면에 지게차가 없다.

    `foot_point_m` 과 `anchor_m` 은 **일부러 멀게** 잡았다(약 3.6m). 서버가 §2.1 의
    `nearby` 를 쓰지 않고 접지점↔앵커로 다시 계산하면 언제나 해소로 판정하게 되고,
    그러면 이 테스트가 깨진다 — 그것이 여기서 잠그려는 회귀다.
    """
    nearby = (
        []
        if dist_m is None
        else [
            {
                "track_id": 11,
                "class": "vehicle",
                "dist_m": dist_m,
                "basis": "mask_nearest",
                "in_danger_zone": dist_m <= 3.0,
            }
        ]
    )
    objects: list[dict[str, Any]] = [
        {
            "class": "person",
            "track_id": 3,
            "conf": 0.91,
            "bbox": [0.197, 0.364, 0.273, 0.764],
            "helmet": "on",
            "helmet_conf": 0.88,
            "foot_point": [0.235, 0.762],
            "foot_point_m": [4.21, 7.85],
            "foot_conf": 0.88,
            "posture": "standing",
            "height_ratio": 0.97,
            "axis_angle_deg": 8.2,
            "stillness_s": 0.4,
            "in_zone": "forklift_lane",
            "nearby": nearby,
        }
    ]
    if dist_m is not None:
        objects.append(
            {
                "class": "vehicle",
                "track_id": 11,
                "conf": 0.87,
                "bbox": [0.591, 0.389, 0.838, 0.756],
                "anchor": [0.702, 0.771],
                # 접지점(4.21, 7.85)에서 3.63m — 경고 임계(2.0m) 밖이다.
                "anchor_m": [7.02, 8.90],
                "moving": True,
                "danger_radius_m": 3.0,
            }
        )
    return FrameMsg.model_validate(
        {"type": "frame", "cam_id": 1, "ts": START + timedelta(seconds=at_s), "objects": objects}
    )


def proximity_candidate(at_s: float) -> CandidateMsg:
    return CandidateMsg.model_validate(
        {
            "type": "candidate",
            "cam_id": 1,
            "ts": START + timedelta(seconds=at_s),
            "track_id": 3,
            "violation_type": "proximity",
            "zone_id": "forklift_lane",
            "bbox": [0.197, 0.364, 0.273, 0.764],
            "conf": 0.91,
            "foot_point_m": [4.21, 7.85],
            "foot_conf": 0.88,
            "posture": "standing",
            "observed_ms": 500,
            "nearby": [
                {
                    "class": "vehicle",
                    "track_id": 11,
                    "dist_m": 1.55,
                    "method": "mask_nearest",
                    "depth_verified": False,
                    "moving": True,
                    "within_danger_radius": True,
                }
            ],
        }
    )


def _flow(harness: Harness, start_s: float, end_s: float, dist_m: float | None) -> None:
    at_s = start_s
    while at_s <= end_s + 1e-9:
        frame = proximity_frame(at_s, dist_m)
        harness.clock.set(frame.ts)
        asyncio.run(harness.service.on_frame(frame))
        at_s = round(at_s + STEP_S, 6)


def test_proximity_confirms_on_the_distance_the_edge_measured() -> None:
    """★ 확정과 해소는 같은 양을 본다 (§2.1).

    마스크 최근접 1.55m 는 경고 임계(2.0m) **안**이고 접지점↔앵커 3.63m 는 **밖**이다.
    서버가 뒤쪽으로 재던 시절에는 엣지가 후보를 올리는 매 프레임마다 「이미 해소」로
    보아 이벤트가 3초 확정에 도달하지 못했다.
    """
    harness = Harness()
    asyncio.run(harness.service.on_candidate(proximity_candidate(0.5)))
    _flow(harness, 0.625, 4.0, 1.55)
    assert status_of(harness) is EventStatus.ALERTED


def test_proximity_resolves_when_the_measured_distance_grows() -> None:
    """멀어지면 해소된다 — 같은 값이 반대 방향으로도 일해야 한다."""
    harness = Harness()
    asyncio.run(harness.service.on_candidate(proximity_candidate(0.5)))
    _flow(harness, 0.625, 4.0, 1.55)
    assert status_of(harness) is EventStatus.ALERTED

    _flow(harness, 4.125, 15.0, 4.2)
    assert status_of(harness) is EventStatus.RESOLVED
