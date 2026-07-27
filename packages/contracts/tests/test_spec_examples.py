"""API명세서에 실린 예시 JSON이 계약 모델로 그대로 파싱되는지 검증한다.

여기 있는 딕셔너리는 `docs/AEGIS_API명세서.md` 에서 문자 그대로 옮긴 것이다.
명세서가 SSOT이므로, 이 테스트가 깨지면 **모델이 틀린 것**이다.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter

from aegis_contracts import (
    AlertCommand,
    CandidateMsg,
    DashboardMessage,
    DetectedPerson,
    DetectedVehicle,
    DeviceStatus,
    EdgeMessage,
    EventStatus,
    EventUpdatedMsg,
    FrameMsg,
    HeartbeatMsg,
    Policies,
    TrackLostMsg,
    ViolationType,
)

_edge_adapter: TypeAdapter[Any] = TypeAdapter(EdgeMessage)
_dashboard_adapter: TypeAdapter[Any] = TypeAdapter(DashboardMessage)


# --- §2.1 frame -----------------------------------------------------------

FRAME_EXAMPLE: dict[str, Any] = {
    "type": "frame",
    "cam_id": 1,
    "ts": "2026-08-14T05:37:02.183Z",
    "objects": [
        {
            "class": "person",
            "track_id": 3,
            "conf": 0.91,
            "bbox": [0.197, 0.364, 0.273, 0.764],
            "helmet": "off",
            "helmet_conf": 0.88,
            "helmet_checked_at": "2026-08-14T05:37:01.900Z",
            "foot_point": [0.235, 0.762],
            "foot_point_m": [4.21, 7.85],
            "foot_conf": 0.88,
            "posture": "standing",
            "height_ratio": 0.97,
            "axis_angle_deg": 8.2,
            "stillness_s": 0.4,
            "in_zone": "forklift_lane",
        },
        {
            "class": "vehicle",
            "track_id": 11,
            "conf": 0.87,
            "bbox": [0.591, 0.389, 0.838, 0.756],
            "anchor_m": [7.02, 8.90],
            "moving": True,
            "danger_radius_m": 3.0,
        },
    ],
}


def test_frame_example_parses() -> None:
    msg = FrameMsg.model_validate(FRAME_EXAMPLE)
    assert msg.cam_id == 1
    person, vehicle = msg.objects
    assert isinstance(person, DetectedPerson)
    assert isinstance(vehicle, DetectedVehicle)
    assert person.helmet == "off"
    assert person.in_zone == "forklift_lane"
    assert vehicle.moving is True
    assert vehicle.danger_radius_m == 3.0


def test_frame_round_trips_to_spec_json() -> None:
    """직렬화하면 `class` 별칭이 다시 나와야 한다 — 엣지가 읽을 수 있는 형태."""
    msg = FrameMsg.model_validate(FRAME_EXAMPLE)
    dumped = msg.model_dump(mode="json", by_alias=True)
    assert dumped["objects"][0]["class"] == "person"
    assert dumped["objects"][1]["class"] == "vehicle"
    assert FrameMsg.model_validate(dumped) == msg


def test_helmet_field_may_be_omitted() -> None:
    """게이트 미통과 · 캐시 없음이면 `helmet` 필드 자체가 생략된다 (§6.3)."""
    obj = dict(FRAME_EXAMPLE["objects"][0])
    for key in ("helmet", "helmet_conf", "helmet_checked_at"):
        obj.pop(key)
    person = DetectedPerson.model_validate(obj)
    assert person.helmet is None
    assert "helmet" not in person.model_dump(mode="json", by_alias=True, exclude_none=True)


def test_helmet_has_no_unknown_value() -> None:
    """`unknown` 클래스는 존재하지 않는다 (§6.3)."""
    obj = dict(FRAME_EXAMPLE["objects"][0]) | {"helmet": "unknown"}
    with pytest.raises(ValueError, match="helmet"):
        DetectedPerson.model_validate(obj)


def test_unknown_field_is_rejected() -> None:
    """명세서에 없는 필드가 실려 오면 계약 위반이다."""
    obj = dict(FRAME_EXAMPLE["objects"][0]) | {"helmet_bbox": [0.1, 0.1, 0.2, 0.2]}
    with pytest.raises(ValueError, match="helmet_bbox"):
        DetectedPerson.model_validate(obj)


# --- §2.2 candidate -------------------------------------------------------

CANDIDATE_EXAMPLE: dict[str, Any] = {
    "type": "candidate",
    "cam_id": 1,
    "ts": "2026-08-14T05:37:02.183Z",
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
    "nearby": [
        {
            "class": "vehicle",
            "track_id": 11,
            "dist_m": 3.2,
            "method": "mask_nearest",
            "depth_verified": True,
            "moving": True,
            "within_danger_radius": True,
        }
    ],
}


def test_candidate_example_parses() -> None:
    msg = CandidateMsg.model_validate(CANDIDATE_EXAMPLE)
    assert msg.violations == [ViolationType.NO_HELMET, ViolationType.ZONE_INTRUSION]
    assert msg.observed_ms == 3200
    assert msg.nearby[0].method == "mask_nearest"
    assert msg.nearby[0].within_danger_radius is True


def test_candidate_nearby_defaults_to_empty() -> None:
    """주변에 지게차가 없으면 빈 배열이다 (§2.2)."""
    payload = {k: v for k, v in CANDIDATE_EXAMPLE.items() if k != "nearby"}
    assert CandidateMsg.model_validate(payload).nearby == []


# --- §2.3 track_lost · §2.4 heartbeat -------------------------------------

TRACK_LOST_EXAMPLE: dict[str, Any] = {
    "type": "track_lost",
    "cam_id": 1,
    "track_id": 3,
    "class": "person",
    "last_ts": "2026-08-14T05:37:09.410Z",
    "last_foot_point_m": [4.55, 7.90],
    "last_helmet": "off",
    "reason": "occluded",
}

HEARTBEAT_EXAMPLE: dict[str, Any] = {
    "type": "heartbeat",
    "ts": "2026-08-14T05:37:05.000Z",
    "fps": {"cam1": 8.2, "cam2": 8.0},
    "gpu_util": 0.41,
    "mem_used_mb": 3820,
    "cls_calls_per_min": 96,
    "cls_cache_hit_rate": 0.87,
    "depth_calls_per_min": 14,
    "cameras": {"cam1": "ok", "cam2": "ok"},
}


def test_track_lost_example_parses() -> None:
    msg = TrackLostMsg.model_validate(TRACK_LOST_EXAMPLE)
    assert msg.class_ == "person"
    assert msg.reason == "occluded"
    assert msg.last_foot_point_m == (4.55, 7.90)


def test_heartbeat_example_parses() -> None:
    msg = HeartbeatMsg.model_validate(HEARTBEAT_EXAMPLE)
    assert msg.fps["cam1"] == 8.2
    assert msg.cameras["cam2"] == "ok"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (FRAME_EXAMPLE, FrameMsg),
        (CANDIDATE_EXAMPLE, CandidateMsg),
        (TRACK_LOST_EXAMPLE, TrackLostMsg),
        (HEARTBEAT_EXAMPLE, HeartbeatMsg),
    ],
)
def test_edge_union_dispatches_on_type(payload: dict[str, Any], expected: type) -> None:
    assert isinstance(_edge_adapter.validate_python(payload), expected)


# --- §3 MQTT --------------------------------------------------------------


def test_alert_command_example_parses() -> None:
    msg = AlertCommand.model_validate(
        {
            "event_id": "EV-20260814-0231",
            "type": "no_helmet",
            "level": 2,
            "zone_id": "forklift_lane",
            "duration_s": 5,
            "repeat": False,
        }
    )
    assert msg.type is ViolationType.NO_HELMET
    assert msg.level == 2


def test_device_status_example_parses() -> None:
    msg = DeviceStatus.model_validate(
        {
            "device": "esp32-01",
            "online": True,
            "uptime_s": 84210,
            "last_alert": "2026-08-14T05:37:03Z",
        }
    )
    assert msg.device == "esp32-01"
    assert msg.last_alert is not None


# --- §4.5 policies --------------------------------------------------------

#: API명세서 §4.5 `GET /policies` 응답 예시 전량.
POLICIES_EXAMPLE: dict[str, Any] = {
    "confirm_duration_s": 3,
    "resolve_duration_s": 10,
    "cooldown_s": 30,
    "resolve_window_s": 300,
    "track_lost_grace_s": 15,
    "reassoc_window_s": 10,
    "reassoc_max_speed_ms": 1.5,
    "reassoc_radius_cap_m": 5.0,
    "proximity_threshold_m": 2.0,
    "vehicle_danger_radius_m": 3.0,
    "depth_band_m": [2.0, 3.5],
    "depth_cache_ms": 500,
    "screening_radius_m": 5.0,
    "min_confidence": 0.55,
    "cls_cache_ms": 1000,
    "cls_min_crop_px": 64,
    "cls_min_conf": 0.60,
    "clip_pre_roll_s": 10,
    "clip_post_roll_s": 10,
    "overlay_buffer_ms": 300,
    "overlay_stale_ms": 1000,
    "fall_height_ratio_max": 0.5,
    "fall_axis_angle_min_deg": 55,
    "fall_stillness_s": 5,
    "anomaly_sample_interval_min": 5,
}


def test_policy_defaults_match_spec_exactly() -> None:
    """기본값이 명세서와 한 글자도 달라지면 안 된다 — DB 시드의 원천이다."""
    assert Policies().model_dump(mode="json") == POLICIES_EXAMPLE


def test_policy_key_set_matches_spec() -> None:
    assert set(Policies.model_fields) == set(POLICIES_EXAMPLE)


# --- §5 대시보드 WebSocket -------------------------------------------------


def test_event_updated_example_parses() -> None:
    payload: dict[str, Any] = {
        "type": "event_updated",
        "event_id": "EV-20260814-0231",
        "status": "resolved",
        "resolved_at": "2026-08-14T05:37:40Z",
        "resolution_sec": 37,
    }
    msg = _dashboard_adapter.validate_python(payload)
    assert isinstance(msg, EventUpdatedMsg)
    assert msg.status is EventStatus.RESOLVED
    assert msg.resolution_sec == 37


def test_event_status_covers_full_state_machine() -> None:
    """기능명세서 §4.2 상태 전이표의 7개 상태 전량."""
    assert {s.value for s in EventStatus} == {
        "candidate",
        "active",
        "alerted",
        "re_alerted",
        "lost",
        "resolved",
        "expired",
    }
