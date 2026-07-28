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
    AnomalyMsg,
    CameraHealth,
    CameraStatus,
    CameraSystemMsg,
    CandidateMsg,
    ChatResponse,
    ClipResponse,
    ComponentSystemMsg,
    DashboardMessage,
    DetectedPerson,
    DetectedVehicle,
    DeviceStatus,
    EdgeMessage,
    EventCreatedMsg,
    EventStatus,
    EventSummary,
    EventUpdatedMsg,
    FrameMsg,
    HeartbeatMsg,
    MetricMsg,
    MetricsDistributionResponse,
    MetricsRepeatResponse,
    MetricsTimeseriesResponse,
    OverlayMsg,
    OverlayPerson,
    OverlayVehicle,
    Policies,
    RecStatusResponse,
    SystemStatus,
    TrackLostMsg,
    ViolationType,
    ZoneUpdatedMsg,
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


# --- §2 필수 · 선택 규약 ---------------------------------------------------
#
#   `·생략` → 선택 (필드가 아예 안 실릴 수 있다)
#   `·null` → 필수, 값만 null (필드는 항상 실린다)


def test_helmet_trio_is_optional() -> None:
    """`helmet` / `helmet_conf` / `helmet_checked_at` 은 모두 `·생략` 이다 (§2.1)."""
    obj = dict(FRAME_EXAMPLE["objects"][0])
    for key in ("helmet", "helmet_conf", "helmet_checked_at"):
        obj.pop(key)
    person = DetectedPerson.model_validate(obj)
    assert person.helmet is None
    assert "helmet" not in person.model_dump(mode="json", by_alias=True, exclude_none=True)


def test_in_zone_field_is_mandatory_even_when_null() -> None:
    """`in_zone` 은 `·null` — 값은 null 이 되어도 **필드는 항상 실린다** (§2.1)."""
    obj = dict(FRAME_EXAMPLE["objects"][0])
    assert DetectedPerson.model_validate({**obj, "in_zone": None}).in_zone is None

    obj.pop("in_zone")
    with pytest.raises(ValueError, match="in_zone"):
        DetectedPerson.model_validate(obj)


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


def test_field_name_alias_is_not_accepted() -> None:
    """명세서의 키는 `class` 뿐이다. `class_` 로는 들어올 수 없다."""
    obj = dict(FRAME_EXAMPLE["objects"][1])
    obj["class_"] = obj.pop("class")
    with pytest.raises(ValueError, match="class"):
        DetectedVehicle.model_validate(obj)


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


def test_candidate_foot_conf_is_optional() -> None:
    """`fall` 처럼 접지점이 무의미한 경우 `foot_conf` 는 생략된다 (§2.2)."""
    payload = {k: v for k, v in CANDIDATE_EXAMPLE.items() if k != "foot_conf"}
    assert CandidateMsg.model_validate(payload).foot_conf is None


def test_candidate_zone_id_field_is_mandatory_even_when_null() -> None:
    """`zone_id` 는 `·null` ✔ — 값은 null 이 되어도 필드는 항상 실린다 (§2.2)."""
    assert CandidateMsg.model_validate({**CANDIDATE_EXAMPLE, "zone_id": None}).zone_id is None

    payload = {k: v for k, v in CANDIDATE_EXAMPLE.items() if k != "zone_id"}
    with pytest.raises(ValueError, match="zone_id"):
        CandidateMsg.model_validate(payload)


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
    "cameras": [
        {"cam_id": 1, "sub_state": "ok", "fps": 8.2},
        {"cam_id": 2, "sub_state": "ok", "fps": 8.0},
    ],
    "gpu_util": 0.41,
    "mem_used_mb": 3820,
    "cls_calls_per_min": 96,
    "cls_cache_hit_rate": 0.87,
    "depth_calls_per_min": 14,
}


def test_track_lost_example_parses() -> None:
    msg = TrackLostMsg.model_validate(TRACK_LOST_EXAMPLE)
    assert msg.class_ == "person"
    assert msg.reason == "occluded"
    assert msg.last_foot_point_m == (4.55, 7.90)


def test_track_lost_last_helmet_is_optional() -> None:
    payload = {k: v for k, v in TRACK_LOST_EXAMPLE.items() if k != "last_helmet"}
    assert TrackLostMsg.model_validate(payload).last_helmet is None


def test_heartbeat_example_parses() -> None:
    """`cameras` 는 카메라별 객체 배열이다 (§2.4)."""
    msg = HeartbeatMsg.model_validate(HEARTBEAT_EXAMPLE)
    assert [camera.cam_id for camera in msg.cameras] == [1, 2]
    assert msg.cameras[0].fps == 8.2
    assert msg.cameras[1].sub_state == "ok"


def test_heartbeat_reports_sub_stream_only() -> None:
    """엣지는 서브 스트림만 본다. 메인 상태는 서버 몫이라 여기 없다 (§2.4 · §4.6)."""
    assert "main_state" not in CameraHealth.model_fields
    payload = dict(HEARTBEAT_EXAMPLE)
    payload["cameras"] = [{"cam_id": 1, "main_state": "ok", "sub_state": "ok", "fps": 8.2}]
    with pytest.raises(ValueError, match="main_state"):
        HeartbeatMsg.model_validate(payload)


def test_stream_state_rejects_component_state_values() -> None:
    """`degraded` 는 구성요소 상태이지 스트림 상태가 아니다 (§4.6)."""
    payload = dict(HEARTBEAT_EXAMPLE)
    payload["cameras"] = [{"cam_id": 1, "sub_state": "degraded", "fps": 8.2}]
    with pytest.raises(ValueError, match="sub_state"):
        HeartbeatMsg.model_validate(payload)


def test_heartbeat_has_no_top_level_fps() -> None:
    """`fps` 는 `cameras[]` 안으로 들어갔다 (§2.4)."""
    payload = dict(HEARTBEAT_EXAMPLE) | {"fps": {"cam1": 8.2}}
    with pytest.raises(ValueError, match="fps"):
        HeartbeatMsg.model_validate(payload)


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


# --- §4.1 이벤트 · §4.2 지표 · §4.4 챗봇 · §4.6 시스템 ----------------------


def test_event_summary_carries_confirmed_at() -> None:
    """§4.1 — 단계별 시각 셋(`detected_at`·`confirmed_at`·`alerted_at`)이 모두 나온다."""
    payload: dict[str, Any] = {
        "event_id": "EV-20260814-0231",
        "cam_id": 1,
        "track_id": 3,
        "violation_type": "no_helmet",
        "zone_id": "forklift_lane",
        "status": "alerted",
        "detected_at": "2026-08-14T05:37:02.183Z",
        "confirmed_at": "2026-08-14T05:37:03.005Z",
        "alerted_at": "2026-08-14T05:37:03.010Z",
        "resolved_at": None,
        "resolution_sec": None,
        "alert_count": 1,
        "min_distance_m": 3.2,
        "posture": "standing",
        "repeat_count_7d": 4,
        "thumbnail_url": "/media/kf/EV-20260814-0231_0.jpg",
    }
    summary = EventSummary.model_validate(payload)
    assert summary.confirmed_at is not None
    assert summary.detected_at < summary.confirmed_at < summary.alerted_at  # type: ignore[operator]


def test_metrics_timeseries_example_parses() -> None:
    """§4.2 — `n` 은 표본 크기다. 비율만 보고 판단하지 않기 위해 함께 온다."""
    response = MetricsTimeseriesResponse.model_validate(
        {
            "metric": "correction_rate",
            "bucket": "day",
            "points": [
                {"t": "2026-08-12", "value": 0.81, "n": 18},
                {"t": "2026-08-13", "value": 0.87, "n": 23},
            ],
        }
    )
    assert [point.n for point in response.points] == [18, 23]


def test_timeseries_t_carries_three_bucket_formats() -> None:
    """§4.2 — `points[].t` 는 `bucket` 마다 형식이 다르다.

    `day`·`week` 는 `YYYY-MM-DD`(주는 월요일), `hour` 는 `YYYY-MM-DDTHH:00:00Z` 다.
    한 필드에 세 형식이 오므로 `str` 이며, 날짜를 자정 시각으로 바꿔 싣지 않는다.
    """
    hourly = MetricsTimeseriesResponse.model_validate(
        {
            "metric": "violations",
            "bucket": "hour",
            "points": [{"t": "2026-08-12T09:00:00Z", "value": 4, "n": 4}],
        }
    )
    assert hourly.points[0].t == "2026-08-12T09:00:00Z"

    weekly = MetricsTimeseriesResponse.model_validate(
        {
            "metric": "correction_rate",
            "bucket": "week",
            "points": [{"t": "2026-08-10", "value": 0.84, "n": 121}],
        }
    )
    assert weekly.points[0].t == "2026-08-10"


def test_metrics_distribution_example_parses() -> None:
    response = MetricsDistributionResponse.model_validate(
        {
            "by": "violation_type",
            "buckets": [
                {"key": "no_helmet", "label": "안전모 미착용", "count": 13, "ratio": 0.57},
                {"key": "zone_intrusion", "label": "금지구역 침입", "count": 7, "ratio": 0.30},
            ],
        }
    )
    assert response.buckets[0].count == 13


def test_hour_of_day_keys_are_zero_padded_strings() -> None:
    """§4.2 — `key` 는 모든 축에서 문자열이고 시간대는 `"00"`~`"23"` 이다.

    제로패딩이 없으면 사전순 정렬이 시각순과 어긋나(`"10" < "9"`) 히트맵 칸 순서가
    뒤집힌다. 숫자로 실으면 축마다 타입이 달라져 화면이 분기해야 한다.
    """
    response = MetricsDistributionResponse.model_validate(
        {
            "by": "hour_of_day",
            "buckets": [
                {"key": "09", "label": "09시", "count": 4, "ratio": 0.17},
                {"key": "10", "label": "10시", "count": 6, "ratio": 0.26},
            ],
        }
    )
    keys = [bucket.key for bucket in response.buckets]
    assert keys == ["09", "10"]
    assert keys == sorted(keys)
    assert all(len(key) == 2 for key in keys)


def test_metrics_repeat_example_parses() -> None:
    """§4.2 — 집계 대상은 zone/camera/track 이며 **개인 단위 누적은 없다**."""
    response = MetricsRepeatResponse.model_validate(
        {
            "days": 7,
            "items": [
                {
                    "subject": "zone",
                    "key": "forklift_lane",
                    "label": "지게차 통행로",
                    "violation_type": "no_helmet",
                    "count": 9,
                    "last_at": "2026-08-14T05:37:03Z",
                }
            ],
        }
    )
    assert response.items[0].subject == "zone"

    with pytest.raises(ValueError, match="subject"):
        MetricsRepeatResponse.model_validate(
            {
                "days": 7,
                "items": [
                    {
                        "subject": "worker",
                        "key": "w-1",
                        "label": "작업자",
                        "violation_type": "no_helmet",
                        "count": 9,
                        "last_at": "2026-08-14T05:37:03Z",
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    "attachment",
    [
        {
            "kind": "clip",
            "event_id": "EV-20260814-0231",
            "clip_url": "/media/clips/EV-20260814-0231.mp4",
            "thumbnail_url": "/media/keyframes/EV-20260814-0231_0.jpg",
            "label": "안전모 미착용 · 카메라 1 · 8/13 15:22",
        },
        {"kind": "image", "image_url": "/media/keyframes/x.jpg", "label": "현재 화면"},
        {
            "kind": "table",
            "columns": ["구역", "건수"],
            "rows": [["지게차 통행로", 9], ["프레스 구역", 4]],
            "label": "구역별 위반",
        },
        {"kind": "event_ref", "event_id": "EV-20260814-0231", "label": "상세 보기"},
    ],
)
def test_chat_attachment_kinds_parse(attachment: dict[str, Any]) -> None:
    """§4.4 — `kind` 로 구분되는 4종."""
    response = ChatResponse.model_validate(
        {"route": "sql", "answer": "…", "attachments": [attachment], "sources": []}
    )
    assert response.attachments[0].kind == attachment["kind"]


def test_chat_attachments_use_urls_not_paths() -> None:
    """§4.4 — 서버 파일 경로를 싣지 않는다."""
    bad = {
        "kind": "clip",
        "event_id": "EV-1",
        "clip_path": "/srv/media/clips/EV-1.mp4",
        "thumbnail_url": "/media/kf/EV-1_0.jpg",
        "label": "x",
    }
    with pytest.raises(ValueError, match=r"clip_path|clip_url"):
        ChatResponse.model_validate({"route": "sql", "answer": "…", "attachments": [bad]})


#: API명세서 §4.6 `GET /system/status` 응답 예시 전량.
SYSTEM_STATUS_EXAMPLE: dict[str, Any] = {
    "edge": {
        "online": True,
        "gpu_util": 0.41,
        "cls_cache_hit_rate": 0.87,
        "depth_calls_per_min": 14,
        "msg_rejected_total": 0,
    },
    "cameras": [
        {"cam_id": 1, "main_state": "ok", "sub_state": "ok", "fps": 8.2, "recording": True},
        {"cam_id": 2, "main_state": "ok", "sub_state": "ok", "fps": 8.0, "recording": True},
    ],
    "mcu": {"online": True, "last_seen": "2026-08-14T05:39:58Z"},
    "cloud": {"available": True, "quota_used": 0.62},
    "storage": {
        "total_gb": 500,
        "used_gb": 378,
        "free_gb": 122,
        "retention_days": 7,
        "oldest_segment_at": "2026-08-07T05:37:00Z",
    },
    "time_sync": {"edge_offset_ms": 12},
}


def test_system_status_example_parses() -> None:
    """§4.6 — `storage` 는 §4.7 과 같은 5필드이고 카메라마다 `recording` 이 온다."""
    status = SystemStatus.model_validate(SYSTEM_STATUS_EXAMPLE)
    assert status.storage.total_gb == 500
    assert status.storage.oldest_segment_at is not None
    assert [camera.recording for camera in status.cameras] == [True, True]


def test_system_status_camera_splits_main_and_sub() -> None:
    """§4.6 — 메인이 끊겨도 추론은 돌고, 서브가 끊겨도 녹화는 돈다. 합치면 구분 불가."""
    camera = CameraStatus.model_validate(
        {
            "cam_id": 1,
            "main_state": "reconnecting",
            "sub_state": "ok",
            "fps": 8.2,
            "recording": True,
        }
    )
    assert camera.main_state == "reconnecting"
    assert camera.sub_state == "ok"

    with pytest.raises(ValueError, match="main_state"):
        CameraStatus.model_validate({"cam_id": 1, "state": "ok", "fps": 8.2, "recording": True})


def test_unobserved_values_are_null_except_the_two_exceptions() -> None:
    """§4.6 「관측 주체가 없을 때는 null 을 쓴다」.

    `0`·`false` 는 "관측했더니 0이었다"는 **주장**이라 실제 장애와 구분되지 않는다.
    예외는 두 가지뿐이다 — 서버가 직접 세는 `msg_rejected_total`(0 시작)과,
    "모름"이라는 값이 없고 연결 안 됨이 사실인 `sub_state`(`"down"`).
    """
    status = SystemStatus.model_validate(
        {
            "edge": {
                "online": False,
                "gpu_util": None,
                "cls_cache_hit_rate": None,
                "depth_calls_per_min": None,
                "msg_rejected_total": 0,
            },
            "cameras": [
                {
                    "cam_id": 1,
                    "main_state": "ok",
                    "sub_state": "down",
                    "fps": None,
                    "recording": None,
                }
            ],
            "mcu": {"online": False, "last_seen": None},
            "cloud": {"available": False, "quota_used": None},
            "storage": {
                "total_gb": None,
                "used_gb": None,
                "free_gb": None,
                "retention_days": None,
                "oldest_segment_at": None,
            },
            "time_sync": {"edge_offset_ms": None},
        }
    )
    assert status.edge.gpu_util is None
    assert status.edge.msg_rejected_total == 0
    assert status.cameras[0].fps is None
    assert status.cameras[0].recording is None
    assert status.cameras[0].sub_state == "down"
    assert status.storage.free_gb is None
    assert status.time_sync.edge_offset_ms is None


# --- §4.7 서버 → REC ------------------------------------------------------


def test_rec_status_example_parses() -> None:
    """§4.7 — 서버는 이 `storage` 절을 §4.6 으로 가공 없이 옮긴다."""
    response = RecStatusResponse.model_validate(
        {
            "cameras": [
                {"cam_id": 1, "recording": True, "last_segment_at": "2026-08-14T05:37:10Z"},
                {"cam_id": 2, "recording": True, "last_segment_at": "2026-08-14T05:37:10Z"},
            ],
            "storage": {
                "total_gb": 500,
                "used_gb": 378,
                "free_gb": 122,
                "retention_days": 7,
                "oldest_segment_at": "2026-08-07T05:37:00Z",
            },
        }
    )
    assert set(response.storage.model_dump()) == set(SYSTEM_STATUS_EXAMPLE["storage"])


def test_clip_ready_example_parses() -> None:
    """§4.7 — `ready` 에는 사유가 없다."""
    response = ClipResponse.model_validate(
        {
            "status": "ready",
            "size_bytes": 4812345,
            "download_url": "/clips/EV-20260814-0231.mp4",
            "actual_from": "2026-08-14T05:36:53Z",
            "actual_to": "2026-08-14T05:37:13Z",
        }
    )
    assert response.reason is None


def test_clip_not_found_example_carries_a_reason() -> None:
    """§4.7 비-`ready` 응답 — 파일이 없으므로 나머지가 전부 `null` 이고 `reason` 이 온다.

    `status` 만으로는 "보존 기간 경과"와 "그 시각에 녹화가 없었다"가 구분되지 않는다.
    서버는 이 값으로 `clip_status = failed` 의 원인을 기록한다.
    """
    response = ClipResponse.model_validate(
        {
            "status": "not_found",
            "size_bytes": None,
            "download_url": None,
            "actual_from": None,
            "actual_to": None,
            "reason": "보존 기간 경과 (oldest_segment_at 2026-08-07T05:37:00Z)",
        }
    )
    assert response.status == "not_found"
    assert response.size_bytes is None
    assert response.download_url is None
    assert response.actual_from is None
    assert response.actual_to is None
    assert response.reason is not None


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
    "overlay_buffer_webrtc_ms": 400,
    "overlay_buffer_hls_ms": 2800,
    "overlay_stale_ms": 1000,
    "fall_height_ratio_max": 0.5,
    "fall_axis_angle_min_deg": 55.0,
    "fall_stillness_s": 5.0,
    "anomaly_sample_interval_min": 5,
}


def test_policy_defaults_match_spec_exactly() -> None:
    """기본값이 명세서와 한 글자도 달라지면 안 된다 — DB 시드의 원천이다."""
    assert Policies().model_dump(mode="json") == POLICIES_EXAMPLE


def test_policy_key_set_matches_spec() -> None:
    assert set(Policies.model_fields) == set(POLICIES_EXAMPLE)


def test_durations_and_thresholds_accept_fractions() -> None:
    """튜닝은 정수 경계에서 멈추지 않는다 — 지속시간·임계값은 전부 float."""
    tuned = Policies.model_validate(
        {"fall_stillness_s": 2.5, "fall_axis_angle_min_deg": 57.5, "confirm_duration_s": 2.5}
    )
    assert tuned.fall_stillness_s == 2.5
    assert tuned.fall_axis_angle_min_deg == 57.5
    assert tuned.confirm_duration_s == 2.5


def test_pixel_count_stays_integral() -> None:
    """셀 수 있는 값만 `int` 로 남는다."""
    with pytest.raises(ValueError, match="cls_min_crop_px"):
        Policies.model_validate({"cls_min_crop_px": 64.5})


# --- §5 대시보드 WebSocket -------------------------------------------------

#: API명세서 §5.1
OVERLAY_EXAMPLE: dict[str, Any] = {
    "type": "overlay",
    "cam_id": 1,
    "ts": "2026-08-14T05:37:12.480Z",
    "objects": [
        {
            "class": "person",
            "track_id": 3,
            "bbox": [0.197, 0.364, 0.273, 0.764],
            "foot_point": [0.235, 0.762],
            "in_zone": "forklift_lane",
            "helmet": "off",
            "posture": "standing",
            "violations": ["no_helmet", "proximity"],
            "event_ids": ["EV-20260814-0231", "EV-20260814-0232"],
            "alert_state": "alerted",
            "nearby": [
                {
                    "track_id": 11,
                    "class": "vehicle",
                    "dist_m": 3.2,
                    "anchor": [0.714, 0.754],
                    "in_danger_zone": False,
                }
            ],
        },
        {
            "class": "vehicle",
            "track_id": 11,
            "bbox": [0.591, 0.389, 0.838, 0.756],
            "anchor": [0.714, 0.754],
            "moving": True,
            "danger_radius_m": 3.0,
            "violations": [],
            "event_ids": [],
            "alert_state": None,
            "nearby": [],
        },
    ],
}

#: API명세서 §5.2
EVENT_CREATED_EXAMPLE: dict[str, Any] = {
    "type": "event_created",
    "event_id": "EV-20260814-0231",
    "cam_id": 1,
    "violation_type": "no_helmet",
    "track_id": 3,
    "zone_id": "forklift_lane",
    "status": "alerted",
    "confirmed_at": "2026-08-14T05:37:03Z",
    "alerted_at": "2026-08-14T05:37:03Z",
    "severity": 2,
    "keyframe_url": "/media/keyframes/EV-20260814-0231_0.jpg",
}

EVENT_UPDATED_EXAMPLE: dict[str, Any] = {
    "type": "event_updated",
    "event_id": "EV-20260814-0231",
    "status": "resolved",
    "resolved_at": "2026-08-14T05:37:40Z",
    "resolution_sec": 37,
}

#: API명세서 §5.3
METRIC_EXAMPLE: dict[str, Any] = {
    "type": "metric",
    "period": "today",
    "correction_rate": 0.87,
    "undetermined_rate": 0.05,
    "total_violations": 23,
    "resolved": 20,
    "unresolved": 2,
    "undetermined": 1,
    "avg_resolution_sec": 41,
    "fall_events": 0,
    "anomaly_flags": 1,
}

ANOMALY_EXAMPLE: dict[str, Any] = {
    "type": "anomaly",
    "anomaly_id": 91,
    "cam_id": 1,
    "score": 0.71,
    "detected_at": "2026-08-14T02:14:00Z",
    "note": "평소와 다른 상황",
    "keyframe_url": "/media/keyframes/anom_91.jpg",
}

SYSTEM_EXAMPLE: dict[str, Any] = {
    "type": "system",
    "component": "cloud_api",
    "state": "degraded",
    "detail": "쿼터 62%",
    "at": "2026-08-14T05:30:00Z",
}

#: API명세서 §5.3 두 번째 예시 — `component == "camera"` 는 `cam_id` 와 `stream` 을 싣는다.
SYSTEM_CAMERA_EXAMPLE: dict[str, Any] = {
    "type": "system",
    "component": "camera",
    "cam_id": 2,
    "stream": "main",
    "state": "reconnecting",
    "detail": "RTSP 재연결 시도 2회",
    "at": "2026-08-14T05:31:12Z",
}

#: API명세서 §5.4
ZONE_UPDATED_EXAMPLE: dict[str, Any] = {
    "type": "zone_updated",
    "cam_id": 1,
    "action": "upsert",
    "zone": {
        "zone_id": "forklift_lane",
        "name": "지게차 통행로",
        "polygon_m": [[3.0, 6.0], [9.0, 6.0], [9.0, 11.0], [3.0, 11.0]],
        "buffer_m": 0.3,
        "active": True,
    },
}


def test_overlay_example_parses() -> None:
    msg = OverlayMsg.model_validate(OVERLAY_EXAMPLE)
    person, vehicle = msg.objects
    assert isinstance(person, OverlayPerson)
    assert isinstance(vehicle, OverlayVehicle)
    assert person.violations == [ViolationType.NO_HELMET, ViolationType.PROXIMITY]
    assert person.event_ids == ["EV-20260814-0231", "EV-20260814-0232"]
    assert person.alert_state == "alerted"
    assert vehicle.alert_state is None
    assert vehicle.violations == []


@pytest.mark.parametrize("index", [0, 1])
def test_overlay_bbox_is_corner_form(index: int) -> None:
    """`[x1, y1, x2, y2]` 좌상단·우하단이다 — `[x, y, w, h]` 가 아니다 (§1.2 · §5.1)."""
    x1, y1, x2, y2 = OverlayMsg.model_validate(OVERLAY_EXAMPLE).objects[index].bbox
    assert x1 < x2, "x2 는 우하단이므로 x1 보다 커야 한다"
    assert y1 < y2, "y2 는 우하단이므로 y1 보다 커야 한다"


def test_overlay_carries_distance_line_data() -> None:
    """FN-UI-02 근접 거리선 — `dist_m` 라벨과 반대편 끝점 `anchor` 가 있어야 한다."""
    person = OverlayMsg.model_validate(OVERLAY_EXAMPLE).objects[0]
    nearest = person.nearby[0]
    assert nearest.dist_m == 3.2
    assert nearest.anchor == (0.714, 0.754)
    assert nearest.in_danger_zone is False
    # 거리선의 반대편 끝점은 실제 그 차량의 접지 좌표와 같아야 한다.
    vehicle = OverlayMsg.model_validate(OVERLAY_EXAMPLE).objects[1]
    assert isinstance(vehicle, OverlayVehicle)
    assert nearest.track_id == vehicle.track_id
    assert nearest.anchor == vehicle.anchor


def test_overlay_alert_state_field_is_mandatory() -> None:
    """`alert_state` 는 `·null` — 값은 null 이 되어도 필드는 항상 실린다."""
    obj = dict(OVERLAY_EXAMPLE["objects"][1])
    obj.pop("alert_state")
    with pytest.raises(ValueError, match="alert_state"):
        OverlayVehicle.model_validate(obj)


def test_overlay_zone_polygon_is_not_carried() -> None:
    """금지구역 폴리곤은 `GET /zones` 소관이다 (§5.1)."""
    payload = dict(OVERLAY_EXAMPLE) | {"zones": [{"zone_id": "forklift_lane"}]}
    with pytest.raises(ValueError, match="zones"):
        OverlayMsg.model_validate(payload)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (OVERLAY_EXAMPLE, OverlayMsg),
        (EVENT_CREATED_EXAMPLE, EventCreatedMsg),
        (EVENT_UPDATED_EXAMPLE, EventUpdatedMsg),
        (METRIC_EXAMPLE, MetricMsg),
        (ANOMALY_EXAMPLE, AnomalyMsg),
        (SYSTEM_EXAMPLE, ComponentSystemMsg),
        (SYSTEM_CAMERA_EXAMPLE, CameraSystemMsg),
        (ZONE_UPDATED_EXAMPLE, ZoneUpdatedMsg),
    ],
)
def test_dashboard_union_dispatches_on_type(payload: dict[str, Any], expected: type) -> None:
    assert isinstance(_dashboard_adapter.validate_python(payload), expected)


# --- §5.3 system — component 로 판별된다 ------------------------------------


def test_system_camera_example_parses() -> None:
    """§5.3 — `component == "camera"` 면 `cam_id` 와 `stream` 이 함께 온다."""
    msg = CameraSystemMsg.model_validate(SYSTEM_CAMERA_EXAMPLE)
    assert msg.cam_id == 2
    assert msg.stream == "main"
    assert msg.state == "reconnecting"


@pytest.mark.parametrize("missing", ["cam_id", "stream"])
def test_camera_system_requires_cam_id_and_stream(missing: str) -> None:
    """어느 카메라의 어느 스트림인지 모르면 대시보드가 캐시를 갱신할 수 없다."""
    payload = {k: v for k, v in SYSTEM_CAMERA_EXAMPLE.items() if k != missing}
    with pytest.raises(ValueError, match=missing):
        _dashboard_adapter.validate_python(payload)


@pytest.mark.parametrize("extra", [{"cam_id": 1}, {"stream": "main"}])
def test_non_camera_system_forbids_stream_fields(extra: dict[str, Any]) -> None:
    """카메라가 아닌 구성요소는 스트림이 없다 — `cam_id`·`stream` 을 싣지 않는다."""
    key = next(iter(extra))
    with pytest.raises(ValueError, match=key):
        _dashboard_adapter.validate_python(SYSTEM_EXAMPLE | extra)


def test_system_state_is_narrowed_by_component() -> None:
    """두 열거형을 합집합으로 열어두지 않는다 (§5.3 검증 규칙)."""
    # 스트림에는 `degraded` 가 없다.
    with pytest.raises(ValueError, match="state"):
        _dashboard_adapter.validate_python(SYSTEM_CAMERA_EXAMPLE | {"state": "degraded"})

    # 구성요소에는 `reconnecting` 이 없다.
    with pytest.raises(ValueError, match="state"):
        _dashboard_adapter.validate_python(SYSTEM_EXAMPLE | {"state": "reconnecting"})

    # 공통값은 양쪽 다 통과한다.
    for shared in ("ok", "down"):
        assert (
            _dashboard_adapter.validate_python(SYSTEM_CAMERA_EXAMPLE | {"state": shared}).state
            == shared
        )
        assert (
            _dashboard_adapter.validate_python(SYSTEM_EXAMPLE | {"state": shared}).state == shared
        )


def test_camera_stream_kind_is_main_or_sub() -> None:
    with pytest.raises(ValueError, match="stream"):
        _dashboard_adapter.validate_python(SYSTEM_CAMERA_EXAMPLE | {"stream": "both"})


#: §5 구조 규약이 허용하는 단일 객체 중첩 — REST 리소스를 그대로 전달하는 경우뿐이다.
ALLOWED_NESTED_FIELDS = {("zone_updated", "zone")}


@pytest.mark.parametrize(
    "payload",
    [
        OVERLAY_EXAMPLE,
        EVENT_CREATED_EXAMPLE,
        EVENT_UPDATED_EXAMPLE,
        METRIC_EXAMPLE,
        ANOMALY_EXAMPLE,
        SYSTEM_EXAMPLE,
        SYSTEM_CAMERA_EXAMPLE,
        ZONE_UPDATED_EXAMPLE,
    ],
)
def test_dashboard_messages_follow_nesting_rule(payload: dict[str, Any]) -> None:
    """중첩은 배열 원소와 **REST 리소스 단일 객체**에만 허용된다 (§5 구조 규약).

    후자는 `zone_updated.zone` 하나뿐이다. 클라이언트가 `GET /zones` 응답과 같은
    형태로 캐시를 갱신할 수 있게 하려는 것이며, 이 경우 외에 새 중첩을 만들지 않는다.
    """
    kind = payload["type"]
    nested = [
        key
        for key, value in payload.items()
        if isinstance(value, dict) and (kind, key) not in ALLOWED_NESTED_FIELDS
    ]
    assert not nested, f"허용되지 않은 중첩 필드: {nested}"


@pytest.mark.parametrize(
    "payload",
    [EVENT_CREATED_EXAMPLE, ANOMALY_EXAMPLE],
)
def test_dashboard_file_references_are_urls(payload: dict[str, Any]) -> None:
    """서버 파일시스템 경로를 그대로 실어보내지 않는다 (§5 경로 규약)."""
    keys = set(payload)
    assert not {k for k in keys if k.endswith(("_path", "_paths"))}
    assert {k for k in keys if k.endswith(("_url", "_urls"))}


def test_event_updated_example_parses() -> None:
    msg = _dashboard_adapter.validate_python(EVENT_UPDATED_EXAMPLE)
    assert isinstance(msg, EventUpdatedMsg)
    assert msg.status is EventStatus.RESOLVED
    assert msg.resolution_sec == 37


def test_event_updated_carries_only_changed_fields() -> None:
    """`event_id` 와 `status` 만으로도 성립한다 (§5.2)."""
    msg = EventUpdatedMsg.model_validate(
        {"type": "event_updated", "event_id": "EV-20260814-0231", "status": "lost"}
    )
    assert msg.resolved_at is None


#: §5.2 전이별 동반 필드 표 전량.
TRANSITION_FIELDS: dict[str, dict[str, Any]] = {
    "alerted": {
        "alerted_at": "2026-08-14T05:37:03Z",
        "alert_count": 1,
        "severity": 2,
    },
    "re_alerted": {"alerted_at": "2026-08-14T05:37:33Z", "alert_count": 2},
    "lost": {"lost_at": "2026-08-14T05:37:20Z"},
    "alerted_after_reassoc": {"track_id": 12, "reassoc_count": 1},
    "resolved": {"resolved_at": "2026-08-14T05:37:40Z", "resolution_sec": 37},
    "expired": {"expired_at": "2026-08-14T05:37:35Z"},
    "clip_ready": {"clip_status": "ready", "clip_url": "/media/clips/EV-1.mp4"},
    "manual": {"is_false_positive": True, "note": "허리 굽혀 작업 중이었음"},
}


@pytest.mark.parametrize(("label", "extra"), list(TRANSITION_FIELDS.items()))
def test_event_updated_accepts_every_transition_payload(label: str, extra: dict[str, Any]) -> None:
    """§5.2 전이별 동반 필드가 전부 실릴 수 있어야 한다."""
    status = label.split("_after_")[0] if "_after_" in label else label
    if status in {"clip", "manual", "clip_ready"}:
        status = "alerted"
    payload = {"type": "event_updated", "event_id": "EV-1", "status": status} | extra
    assert _dashboard_adapter.validate_python(payload).event_id == "EV-1"


def test_severity_shares_scale_with_alert_command_level() -> None:
    """§5.2 `severity` 와 §3 `AlertCommand.level` 은 같은 척도, 같은 값이다."""
    created = EventCreatedMsg.model_validate(EVENT_CREATED_EXAMPLE)
    command = AlertCommand.model_validate(
        {
            "event_id": created.event_id,
            "type": created.violation_type,
            "level": created.severity,
            "zone_id": created.zone_id,
            "duration_s": 5,
            "repeat": False,
        }
    )
    assert command.level == created.severity == 2

    for bad in (0, 4):
        with pytest.raises(ValueError, match="severity"):
            EventCreatedMsg.model_validate(EVENT_CREATED_EXAMPLE | {"severity": bad})
        with pytest.raises(ValueError, match="level"):
            AlertCommand.model_validate(
                {
                    "event_id": "EV-1",
                    "type": "fall",
                    "level": bad,
                    "duration_s": 5,
                    "repeat": False,
                }
            )


# --- §5.4 zone_updated ----------------------------------------------------


def test_zone_updated_example_parses() -> None:
    msg = ZoneUpdatedMsg.model_validate(ZONE_UPDATED_EXAMPLE)
    assert msg.action == "upsert"
    assert msg.zone.name == "지게차 통행로"
    assert msg.zone.polygon_m is not None
    assert len(msg.zone.polygon_m) == 4


def test_zone_updated_delete_carries_only_zone_id() -> None:
    """`delete` 시에는 `zone_id` 만 포함한다 (§5.4)."""
    msg = ZoneUpdatedMsg.model_validate(
        {
            "type": "zone_updated",
            "cam_id": 1,
            "action": "delete",
            "zone": {"zone_id": "forklift_lane"},
        }
    )
    assert msg.zone.polygon_m is None


def test_zone_updated_upsert_requires_full_zone() -> None:
    """폴리곤 없는 upsert 를 통과시키면 대시보드 캐시가 망가진다."""
    payload = dict(ZONE_UPDATED_EXAMPLE) | {"zone": {"zone_id": "forklift_lane"}}
    with pytest.raises(ValueError, match="polygon_m"):
        ZoneUpdatedMsg.model_validate(payload)


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
