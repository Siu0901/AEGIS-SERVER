"""`frame` → `overlay` 합성 (API명세서 §5.1 · FN-UI-02).

여기서 지키는 것은 "클라이언트가 위반 여부를 스스로 추론하지 않게 한다"는 §5.1 의
전제다. 프레임을 그대로 흘려보내면 프론트가 `helmet == "off"` 같은 규칙을 다시 쓰게 되고,
그 순간 서버 판정과 화면 표시가 갈라진다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from aegis_contracts import CandidateMsg, EventStatus, FrameMsg, ViolationType
from server.domain.overlay import LiveTracks, compose_overlay

TS = datetime(2026, 8, 14, 5, 37, 12, 480000, tzinfo=UTC)

PERSON: dict[str, Any] = {
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

VEHICLE: dict[str, Any] = {
    "class": "vehicle",
    "track_id": 11,
    "conf": 0.87,
    "bbox": [0.591, 0.389, 0.838, 0.756],
    "anchor": [0.702, 0.771],
    "anchor_m": [7.02, 8.90],
    "moving": True,
    "danger_radius_m": 3.0,
}


def frame(*objects: dict[str, Any], cam_id: int = 1) -> FrameMsg:
    body = {"type": "frame", "cam_id": cam_id, "ts": TS, "objects": objects}
    return FrameMsg.model_validate(body)


def candidate(**overrides: Any) -> CandidateMsg:
    body: dict[str, Any] = {
        "type": "candidate",
        "cam_id": 1,
        "ts": TS,
        "track_id": 3,
        "violations": ["no_helmet"],
        "zone_id": "forklift_lane",
        "bbox": [0.197, 0.364, 0.273, 0.764],
        "conf": 0.91,
        "foot_point_m": [4.21, 7.85],
        "observed_ms": 3200,
        "nearby": [
            {
                "class": "vehicle",
                "track_id": 11,
                "dist_m": 3.2,
                "method": "mask_nearest",
                "depth_verified": True,
                "moving": True,
                "within_danger_radius": False,
            }
        ],
        **overrides,
    }
    return CandidateMsg.model_validate(body)


def test_ts_is_carried_through_unchanged() -> None:
    """`ts` 는 **원본 프레임 시각**이다. 시간 정합의 기준이라 서버가 다시 찍으면 안 된다."""
    overlay = compose_overlay(frame(PERSON), LiveTracks())
    assert overlay.ts == TS


def test_bbox_stays_in_corner_form() -> None:
    """§5.1 — `[x1, y1, x2, y2]` 이지 `[x, y, w, h]` 가 아니다."""
    overlay = compose_overlay(frame(PERSON), LiveTracks())
    assert overlay.objects[0].bbox == pytest.approx((0.197, 0.364, 0.273, 0.764))


def test_clean_person_carries_empty_collections_not_missing_fields() -> None:
    """§5.1 은 "없으면 빈 배열"이라고 적는다. 필드 자체는 항상 실린다."""
    person = compose_overlay(frame(PERSON), LiveTracks()).objects[0]
    assert person.violations == []
    assert person.event_ids == []
    assert person.alert_state is None
    assert person.nearby == []


def test_violations_come_from_the_server_not_from_the_helmet_field() -> None:
    tracks = LiveTracks()
    overlay = compose_overlay(frame(PERSON), tracks)
    # 안전모가 `off` 인데도 위반이 비어 있다 — 판정은 후보를 받은 뒤에 붙는다.
    assert overlay.objects[0].model_dump(by_alias=True)["helmet"] == "off"
    assert overlay.objects[0].violations == []

    tracks.record_candidate(
        candidate(), {ViolationType.NO_HELMET: ("EV-20260814-0231", EventStatus.CANDIDATE)}
    )
    person = compose_overlay(frame(PERSON), tracks).objects[0]
    assert person.violations == [ViolationType.NO_HELMET]
    assert person.event_ids == ["EV-20260814-0231"]


def test_candidate_and_null_are_different_states() -> None:
    """§5.1 — `candidate` 는 "관측됐으나 확정 전", `null` 은 "이벤트가 없다"다.

    둘을 같은 값으로 내보내면 대시보드가 확정 진행 중인 트랙과 아무 일도 없는 트랙을
    구분할 수 없다.
    """
    tracks = LiveTracks()
    assert compose_overlay(frame(PERSON), tracks).objects[0].alert_state is None

    tracks.record_candidate(candidate(), {ViolationType.NO_HELMET: ("EV-1", EventStatus.CANDIDATE)})
    assert compose_overlay(frame(PERSON), tracks).objects[0].alert_state == "candidate"


def test_alert_state_takes_the_most_advanced_stage() -> None:
    """박스는 트랙당 하나다. 확정 전 후보 때문에 경고 표시가 내려가면 안 된다."""
    tracks = LiveTracks()
    tracks.record_candidate(
        candidate(),
        {
            ViolationType.NO_HELMET: ("EV-1", EventStatus.CANDIDATE),
            ViolationType.PROXIMITY: ("EV-2", EventStatus.ALERTED),
        },
    )
    assert compose_overlay(frame(PERSON), tracks).objects[0].alert_state == "alerted"


def test_alert_state_maps_from_the_event_status() -> None:
    tracks = LiveTracks()
    tracks.record_candidate(candidate(), {ViolationType.NO_HELMET: ("EV-1", EventStatus.ALERTED)})
    assert compose_overlay(frame(PERSON), tracks).objects[0].alert_state == "alerted"


def test_vehicle_anchor_comes_from_the_edge_not_from_the_box() -> None:
    """§2.1 — `anchor` 는 마스크 하단에서 산출한 값이라 **bbox 아래변 중앙이 아니다.**

    서버가 박스로 추정하면 포크가 뻗었거나 적재물이 있을 때 거리선이 엉뚱한 곳에 붙는다.
    이 픽스처의 `anchor`(0.702, 0.771)는 아래변 중앙(0.7145, 0.756)과 일부러 다르다.
    """
    vehicle = compose_overlay(frame(VEHICLE), LiveTracks()).objects[0]
    assert vehicle.model_dump()["anchor"] == pytest.approx((0.702, 0.771))


def test_nearby_carries_the_distance_and_the_other_end_of_the_line() -> None:
    tracks = LiveTracks()
    tracks.record_candidate(candidate(), {ViolationType.NO_HELMET: ("EV-1", EventStatus.CANDIDATE)})
    person = compose_overlay(frame(PERSON, VEHICLE), tracks).objects[0]
    assert len(person.nearby) == 1
    assert person.nearby[0].dist_m == pytest.approx(3.2)
    assert person.nearby[0].anchor == pytest.approx((0.702, 0.771))
    assert person.nearby[0].in_danger_zone is False


def test_nearby_drops_vehicles_that_are_not_in_this_frame() -> None:
    """선의 반대편을 찍을 수 없으면 거리 라벨만 남아 아무 데도 안 붙은 숫자가 된다."""
    tracks = LiveTracks()
    tracks.record_candidate(candidate(), {ViolationType.NO_HELMET: ("EV-1", EventStatus.CANDIDATE)})
    person = compose_overlay(frame(PERSON), tracks).objects[0]
    assert person.nearby == []


def test_violations_belong_to_the_person_not_the_vehicle() -> None:
    """§2.2 — `track_id` 는 "위반 대상 **사람**의 추적 번호"다."""
    tracks = LiveTracks()
    tracks.record_candidate(candidate(), {ViolationType.NO_HELMET: ("EV-1", EventStatus.CANDIDATE)})
    vehicle = compose_overlay(frame(PERSON, VEHICLE), tracks).objects[1]
    assert vehicle.violations == []
    assert vehicle.event_ids == []


def test_helmet_field_is_omitted_when_the_edge_omitted_it() -> None:
    """게이트 미통과는 `null` 이 아니라 **필드 생략**으로 표현된다(§2.1 · §6.3)."""
    ungated = {key: value for key, value in PERSON.items() if not key.startswith("helmet")}
    person = compose_overlay(frame(ungated), LiveTracks()).objects[0]
    assert "helmet" not in person.model_dump(exclude_unset=True, by_alias=True)


def test_forgetting_a_track_clears_its_violations() -> None:
    """새 트랙이 같은 번호를 물려받아도 위반을 이어받으면 안 된다."""
    tracks = LiveTracks()
    tracks.record_candidate(candidate(), {ViolationType.NO_HELMET: ("EV-1", EventStatus.CANDIDATE)})
    tracks.forget(1, 3)
    assert compose_overlay(frame(PERSON), tracks).objects[0].violations == []


def test_tracks_are_scoped_per_camera() -> None:
    """`track_id` 는 카메라 안에서만 유효하다(기능명세서 §4.2 재결합 조건)."""
    tracks = LiveTracks()
    tracks.record_candidate(candidate(), {ViolationType.NO_HELMET: ("EV-1", EventStatus.CANDIDATE)})
    other = compose_overlay(frame(PERSON, cam_id=2), tracks).objects[0]
    assert other.violations == []
