"""`/ws/edge` — 수신 · 검증 · 이벤트 생성 (API명세서 §2 · FN-EVT-01 · FN-SYS-06).

가장 중요한 검사는 **거부된 메시지가 소리 없이 사라지지 않는가**다. 감지된 위반이
검증 단계에서 조용히 없어지는 것은 오탐보다 위험하다(§2.2).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from aegis_contracts import OverlayMsg, SystemStatus
from aegis_vision.clock import FakeClock
from server.app.main import create_app

from .conftest import FakeEventStore, FakeRecClient, FakeWatcher, make_settings

TS = "2026-08-14T05:37:02.183Z"

FRAME: dict[str, Any] = {
    "type": "frame",
    "cam_id": 1,
    "ts": TS,
    "objects": [
        {
            "class": "person",
            "track_id": 3,
            "conf": 0.91,
            "bbox": [0.197, 0.364, 0.273, 0.764],
            "helmet": "off",
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

CANDIDATE: dict[str, Any] = {
    "type": "candidate",
    "cam_id": 1,
    "ts": TS,
    "track_id": 3,
    "violations": ["no_helmet", "zone_intrusion"],
    "zone_id": "forklift_lane",
    "bbox": [0.197, 0.364, 0.273, 0.764],
    "conf": 0.91,
    "foot_point_m": [4.21, 7.85],
    "foot_conf": 0.88,
    "helmet": "off",
    "helmet_conf": 0.88,
    "posture": "standing",
    "observed_ms": 3200,
    "nearby": [],
}

HEARTBEAT: dict[str, Any] = {
    "type": "heartbeat",
    "ts": TS,
    "cameras": [
        {"cam_id": 1, "sub_state": "ok", "fps": 8.2},
        {"cam_id": 2, "sub_state": "reconnecting", "fps": 3.4},
    ],
    "gpu_util": 0.41,
    "mem_used_mb": 3820,
    "cls_calls_per_min": 96,
    "cls_cache_hit_rate": 0.87,
    "depth_calls_per_min": 14,
}

TRACK_LOST: dict[str, Any] = {
    "type": "track_lost",
    "cam_id": 1,
    "track_id": 3,
    "class": "person",
    "last_ts": TS,
    "last_foot_point_m": [4.55, 7.90],
    "last_helmet": "off",
    "reason": "occluded",
}


def build(store: FakeEventStore | None = None) -> tuple[TestClient, FakeEventStore]:
    events = store or FakeEventStore()
    app = create_app(
        make_settings(),
        FakeClock(datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)),
        rec_client=FakeRecClient(),
        stream_watcher=FakeWatcher({1: "ok", 2: "ok"}),
        events=events,
    )
    return TestClient(app), events


def drain(dashboard: Any, expected: int) -> list[dict[str, Any]]:
    """대시보드로 나간 메시지 `expected` 건을 받아온다."""
    return [dashboard.receive_json() for _ in range(expected)]


# --------------------------------------------------------------------------
# FN-SYS-06 — 거부된 메시지를 조용히 버리지 않는다
# --------------------------------------------------------------------------


def test_broken_json_is_counted_and_surfaced() -> None:
    client, _ = build()
    with (
        client,
        client.websocket_connect("/ws/dashboard") as dashboard,
        client.websocket_connect("/ws/edge") as edge,
    ):
        drain(dashboard, 1)  # 엣지 접속 통지
        edge.send_text("{ this is not json")
        rejected = dashboard.receive_json()
        status = SystemStatus.model_validate(client.get("/api/v1/system/status").json())

    assert rejected["component"] == "edge"
    assert rejected["state"] == "degraded"
    assert "1건" in rejected["detail"]
    assert status.edge.msg_rejected_total == 1


def test_rejection_logs_the_original_payload(caplog: Any) -> None:
    """무엇이 거부됐는지 남지 않으면 "즉시 드러나야 한다"(§2.2)가 성립하지 않는다."""
    client, _ = build()
    with (
        caplog.at_level("WARNING", logger="server.ws.edge"),
        client,
        client.websocket_connect("/ws/edge") as edge,
    ):
        edge.send_text(json.dumps({"type": "candidate", "cam_id": 1}))

    record = next(r for r in caplog.records if r.name == "server.ws.edge")
    assert record.levelname == "WARNING"
    message = record.getMessage()
    assert "reason=missing" in message
    assert '{"type": "candidate", "cam_id": 1}' in message


def test_unknown_message_type_is_rejected_not_ignored() -> None:
    client, _ = build()
    with client:
        with client.websocket_connect("/ws/edge") as edge:
            edge.send_text(json.dumps({"type": "nonsense"}))
        status = SystemStatus.model_validate(client.get("/api/v1/system/status").json())
    assert status.edge.msg_rejected_total == 1


def test_a_rejection_does_not_kill_the_socket() -> None:
    """한 건이 깨졌다고 연결을 끊으면 그 뒤의 정상 후보까지 전부 잃는다."""
    client, events = build()
    with client:
        with client.websocket_connect("/ws/edge") as edge:
            edge.send_text("{}")
            edge.send_json(CANDIDATE)
        status = SystemStatus.model_validate(client.get("/api/v1/system/status").json())

    assert status.edge.msg_rejected_total == 1
    assert len(events.created) == 2


# --------------------------------------------------------------------------
# FN-SYS-01 — heartbeat 가 채우는 값들
# --------------------------------------------------------------------------


def test_heartbeat_fills_sub_state_and_fps() -> None:
    """엣지가 붙기 전에는 `sub_state = down` · `fps = null` 이다(§4.6 null 규약)."""
    client, _ = build()
    with client:
        before = SystemStatus.model_validate(client.get("/api/v1/system/status").json())
        assert [c.fps for c in before.cameras] == [None, None]
        assert {c.sub_state for c in before.cameras} == {"down"}

        with client.websocket_connect("/ws/edge") as edge:
            edge.send_json(HEARTBEAT)
            after = SystemStatus.model_validate(client.get("/api/v1/system/status").json())

    states = {c.cam_id: (c.sub_state, c.fps) for c in after.cameras}
    assert states == {1: ("ok", 8.2), 2: ("reconnecting", 3.4)}
    assert after.edge.online is True
    assert after.edge.gpu_util == 0.41
    assert after.edge.cls_cache_hit_rate == 0.87


def test_sub_state_falls_back_to_down_when_the_edge_disconnects() -> None:
    """엣지가 없으면 서브 스트림을 관측하는 주체가 없다. 마지막 값을 붙들지 않는다."""
    client, _ = build()
    with client:
        with client.websocket_connect("/ws/edge") as edge:
            edge.send_json(HEARTBEAT)
        after = SystemStatus.model_validate(client.get("/api/v1/system/status").json())

    assert after.edge.online is False
    assert {c.sub_state for c in after.cameras} == {"down"}
    assert [c.fps for c in after.cameras] == [None, None]


def test_heartbeat_publishes_only_changed_cameras() -> None:
    """5초마다 같은 내용을 방송하면 실제 변화가 묻힌다(§5.3)."""
    client, _ = build()
    with (
        client,
        client.websocket_connect("/ws/dashboard") as dashboard,
        client.websocket_connect("/ws/edge") as edge,
    ):
        drain(dashboard, 1)
        edge.send_json(HEARTBEAT)
        first = drain(dashboard, 3)  # edge ok + camera 1 + camera 2
        edge.send_json(HEARTBEAT)
        edge.send_json(FRAME)
        after_second = dashboard.receive_json()

    assert [m["component"] for m in first] == ["edge", "camera", "camera"]
    # 두 번째 하트비트는 아무것도 바꾸지 않았으므로 다음에 오는 것은 오버레이다.
    assert after_second["type"] == "overlay"


# --------------------------------------------------------------------------
# §5.1 overlay
# --------------------------------------------------------------------------


def test_frame_is_published_as_overlay_not_forwarded() -> None:
    client, _ = build()
    with (
        client,
        client.websocket_connect("/ws/dashboard") as dashboard,
        client.websocket_connect("/ws/edge") as edge,
    ):
        drain(dashboard, 1)
        edge.send_json(FRAME)
        payload = dashboard.receive_json()

    overlay = OverlayMsg.model_validate(payload)
    assert overlay.cam_id == 1
    assert overlay.objects[0].violations == []
    # 엣지 전용 필드는 오버레이에 없다 — `extra="forbid"` 가 이것을 보장한다.
    assert "foot_conf" not in payload["objects"][0]


def test_overlay_shows_violations_after_a_candidate() -> None:
    client, _ = build()
    with (
        client,
        client.websocket_connect("/ws/dashboard") as dashboard,
        client.websocket_connect("/ws/edge") as edge,
    ):
        drain(dashboard, 1)
        edge.send_json(CANDIDATE)
        edge.send_json(FRAME)
        payload = dashboard.receive_json()

    person = payload["objects"][0]
    assert person["violations"] == ["no_helmet", "zone_intrusion"]
    assert len(person["event_ids"]) == 2
    assert person["alert_state"] is None


def test_track_lost_takes_the_box_state_down() -> None:
    client, _ = build()
    with (
        client,
        client.websocket_connect("/ws/dashboard") as dashboard,
        client.websocket_connect("/ws/edge") as edge,
    ):
        drain(dashboard, 1)
        edge.send_json(CANDIDATE)
        edge.send_json(TRACK_LOST)
        edge.send_json(FRAME)
        payload = dashboard.receive_json()

    assert payload["objects"][0]["violations"] == []


def test_track_lost_does_not_transition_the_event() -> None:
    """소실 유예(FN-EVT-07 ①)는 상태머신과 함께 M3 다. 전이만 흉내 내면 `expired` 로
    끝나는 길이 없어 판정 불가율이 왜곡된다."""
    client, events = build()
    with client, client.websocket_connect("/ws/edge") as edge:
        edge.send_json(CANDIDATE)
        edge.send_json(TRACK_LOST)
    assert events.updates == []
    assert {e.status for e in events.items} == {"candidate"}


# --------------------------------------------------------------------------
# FN-EVT-01 — 중복 병합
# --------------------------------------------------------------------------


def test_one_candidate_creates_one_event_per_violation() -> None:
    client, events = build()
    with client, client.websocket_connect("/ws/edge") as edge:
        edge.send_json(CANDIDATE)

    assert [e.violation_type for e in events.created] == ["no_helmet", "zone_intrusion"]
    assert {e.status for e in events.created} == {"candidate"}


def test_repeated_candidates_do_not_duplicate_events() -> None:
    """이게 깨지면 같은 위반이 후보 빈도만큼 이벤트로 불어난다."""
    client, events = build()
    with client, client.websocket_connect("/ws/edge") as edge:
        for _ in range(5):
            edge.send_json(CANDIDATE)

    assert len(events.created) == 2


def test_a_different_track_gets_its_own_events() -> None:
    client, events = build()
    with client, client.websocket_connect("/ws/edge") as edge:
        edge.send_json(CANDIDATE)
        edge.send_json({**CANDIDATE, "track_id": 9})

    assert len(events.created) == 4
    assert {e.track_id for e in events.created} == {3, 9}


def test_the_same_track_on_another_camera_is_a_different_event() -> None:
    """`track_id` 는 카메라 안에서만 유효하다(기능명세서 §4.2)."""
    client, events = build()
    with client, client.websocket_connect("/ws/edge") as edge:
        edge.send_json(CANDIDATE)
        edge.send_json({**CANDIDATE, "cam_id": 2})

    assert len(events.created) == 4
