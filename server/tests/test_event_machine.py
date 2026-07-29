"""FN-EVT-01 후보 병합 — 순수 판단만 본다 (기능명세서 §4.2).

이 모듈이 지키는 약속 하나: **같은 `cam_id` + `track_id` + 위반 유형이면 새로
만들지 않는다.** 이게 깨지면 같은 위반이 후보 빈도만큼 이벤트로 불어나고
시정률의 분모가 통째로 무의미해진다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from aegis_contracts import CandidateMsg, EventStatus, EventSummary, ViolationType
from server.domain.event_machine import (
    build_candidate_event,
    format_event_id,
    merge_changes,
    plan_candidate,
)

TS = datetime(2026, 8, 14, 5, 37, 2, 183000, tzinfo=UTC)


def candidate(**overrides: Any) -> CandidateMsg:
    """API명세서 §2.2 예시를 기본값으로 쓴다."""
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
        **overrides,
    }
    return CandidateMsg.model_validate(body)


# --------------------------------------------------------------------------
# plan_candidate
# --------------------------------------------------------------------------


def test_new_violation_creates_an_event() -> None:
    plan = plan_candidate(candidate(), {})
    assert plan.creates == (ViolationType.NO_HELMET,)
    assert plan.updates == ()


def test_open_event_is_merged_not_recreated() -> None:
    """FN-EVT-01 의 핵심. 같은 유형이 열려 있으면 갱신으로 간다."""
    plan = plan_candidate(candidate(), {ViolationType.NO_HELMET: "EV-20260814-0231"})
    assert plan.creates == ()
    assert plan.updates == ((ViolationType.NO_HELMET, "EV-20260814-0231"),)


def test_another_violation_type_on_the_same_track_is_a_separate_event() -> None:
    """안전모 미착용과 구역 침입은 시정 행동도 규정 조항도 다르다. 한 건으로 묶지 않는다."""
    plan = plan_candidate(
        candidate(violations=["zone_intrusion"]),
        {ViolationType.NO_HELMET: "EV-20260814-0231"},
    )
    assert plan.creates == (ViolationType.ZONE_INTRUSION,)


def test_candidate_carries_exactly_one_violation() -> None:
    """§2.2 — 한 트랙에 두 유형이 걸리면 후보 메시지를 유형 수만큼 각각 보낸다.

    한 메시지에 묶여 오면 `observed_ms` 가 어느 유형의 값인지 알 수 없어, 확정
    판정(FN-EVT-02)의 참고값이 무의미해진다. 계약이 그것을 막는다.
    """
    with pytest.raises(ValidationError):
        candidate(violations=["no_helmet", "zone_intrusion"])
    with pytest.raises(ValidationError):
        candidate(violations=[])


# --------------------------------------------------------------------------
# format_event_id
# --------------------------------------------------------------------------


def test_event_id_matches_the_spec_shape() -> None:
    assert format_event_id(TS, 231) == "EV-20260814-0231"


def test_event_id_date_is_utc() -> None:
    """저장이 UTC 이므로 날짜 접두사도 UTC 다. 로컬 자정으로 끊으면 두 날에 걸친다."""
    late = datetime(2026, 8, 14, 23, 30, tzinfo=UTC)
    assert format_event_id(late, 1).startswith("EV-20260814-")


# --------------------------------------------------------------------------
# build_candidate_event
# --------------------------------------------------------------------------


def test_new_event_stays_at_candidate() -> None:
    """M2 에는 확정 판정이 없다. `confirmed_at` 을 지금 채우면 시정률 분모가 오염된다."""
    event = build_candidate_event(candidate(), ViolationType.NO_HELMET, "EV-20260814-0231")
    assert event.status == EventStatus.CANDIDATE
    assert event.confirmed_at is None
    assert event.alerted_at is None
    assert event.alert_count == 0


def test_detected_at_is_the_observation_time_not_the_arrival_time() -> None:
    event = build_candidate_event(candidate(), ViolationType.NO_HELMET, "EV-1")
    assert event.detected_at == TS


def test_min_distance_is_null_when_there_was_nothing_to_measure() -> None:
    """0.0 은 "붙어 있었다"는 주장이다. 잴 대상이 없었던 것과 다르다."""
    event = build_candidate_event(candidate(nearby=[]), ViolationType.NO_HELMET, "EV-1")
    assert event.min_distance_m is None
    assert event.depth_verified is None


def test_min_distance_is_the_closest_vehicle() -> None:
    near = candidate(violations=["proximity"])
    event = build_candidate_event(near, ViolationType.PROXIMITY, "EV-1")
    assert event.min_distance_m == pytest.approx(3.2)
    assert event.depth_verified is True


# --------------------------------------------------------------------------
# merge_changes
# --------------------------------------------------------------------------


def existing(**overrides: Any) -> EventSummary:
    body: dict[str, Any] = {
        "event_id": "EV-20260814-0231",
        "cam_id": 1,
        "track_id": 3,
        "violation_type": "no_helmet",
        "zone_id": None,
        "status": "candidate",
        "detected_at": TS,
        "confirmed_at": None,
        "alerted_at": None,
        "resolved_at": None,
        "resolution_sec": None,
        "alert_count": 0,
        "min_distance_m": None,
        "posture": "standing",
        "repeat_count_7d": 0,
        "thumbnail_url": None,
        **overrides,
    }
    return EventSummary.model_validate(body)


def test_unchanged_candidate_produces_no_write() -> None:
    """후보는 초당 여러 번 온다. 같은 값을 다시 쓰면 DB 가 후보 빈도만큼 부하를 받는다."""
    event = existing(zone_id="forklift_lane", min_distance_m=3.2)
    assert merge_changes(event, candidate()) == {}


def test_zone_is_filled_in_when_the_worker_walks_into_it() -> None:
    assert merge_changes(existing(), candidate())["zone_id"] == "forklift_lane"


def test_zone_follows_the_latest_observation_while_still_a_candidate() -> None:
    """확정 전에는 최신 관측값으로 따라간다 (기능명세서 §4.2)."""
    event = existing(zone_id="forklift_lane")
    assert merge_changes(event, candidate(zone_id=None))["zone_id"] is None


def test_zone_freezes_once_the_event_is_confirmed() -> None:
    """§4.2 — `events.zone_id` 는 **확정 시점의 구역을 기록하고 이후 바꾸지 않는다.**

    위반자가 구역을 나간 뒤 이벤트의 구역까지 바뀌면 구역별 집계가 사후에 흔들린다.
    """
    for status in ("active", "alerted", "re_alerted", "lost"):
        event = existing(status=status, zone_id="forklift_lane")
        assert "zone_id" not in merge_changes(event, candidate(zone_id=None))


def test_min_distance_only_moves_closer() -> None:
    """가장 가까웠던 순간이 위험도의 근거다. 지게차가 멀어졌다고 그 사실이 사라지면 안 된다."""
    event = existing(min_distance_m=1.4)
    assert "min_distance_m" not in merge_changes(event, candidate())

    event = existing(min_distance_m=5.0)
    assert merge_changes(event, candidate())["min_distance_m"] == pytest.approx(3.2)


def test_posture_change_is_recorded() -> None:
    event = existing(posture="standing")
    assert merge_changes(event, candidate(posture="fallen"))["posture"] == "fallen"
