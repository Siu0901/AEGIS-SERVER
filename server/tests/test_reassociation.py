"""FN-EVT-07 ② 재결합 매칭 (기능명세서 §4.2).

핵심은 **반경이 고정값이 아니라 경과 시간에 비례한다**는 것이다. 고정 반경은 작게
잡으면 정상적인 재결합이 실패하고, 크게 잡으면 인접한 다른 작업자를 잘못 흡수한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from server.domain.reassociation import (
    LostTrack,
    ReassocMatch,
    match_lost_track,
    reassoc_radius_m,
)

LOST_AT = datetime(2026, 8, 14, 5, 37, 10, tzinfo=UTC)

WINDOW_S = 10.0
SPEED_MS = 1.5
CAP_M = 5.0


def lost(track_id: int = 3, at_m: tuple[float, float] = (4.55, 7.90)) -> LostTrack:
    return LostTrack(
        event_id=f"EV-20260814-{track_id:04d}",
        track_id=track_id,
        lost_at=LOST_AT,
        last_foot_point_m=at_m,
    )


def after(seconds: float) -> datetime:
    return LOST_AT + timedelta(seconds=seconds)


def test_radius_grows_with_elapsed_time() -> None:
    """ "1초 만에 다시 나타났다면 1.5m 이내에 있어야 한다"는 물리적 제약 그대로다."""
    assert reassoc_radius_m(1.0, max_speed_ms=SPEED_MS, cap_m=CAP_M) == pytest.approx(1.5)
    assert reassoc_radius_m(2.0, max_speed_ms=SPEED_MS, cap_m=CAP_M) == pytest.approx(3.0)


def test_radius_is_capped() -> None:
    """상한이 없으면 시간 창 끝에서 반경이 카메라 반대편까지 넓어진다."""
    assert reassoc_radius_m(10.0, max_speed_ms=SPEED_MS, cap_m=CAP_M) == pytest.approx(5.0)


def match(
    seconds: float,
    at_m: tuple[float, float],
    tracks: list[LostTrack] | None = None,
) -> ReassocMatch | None:
    return match_lost_track(
        appeared_at=after(seconds),
        foot_point_m=at_m,
        lost=tracks if tracks is not None else [lost()],
        window_s=WINDOW_S,
        max_speed_ms=SPEED_MS,
        cap_m=CAP_M,
    )


def test_close_and_soon_is_a_match() -> None:
    found = match(2.0, (5.55, 7.90))
    assert found is not None
    assert found.event_id == "EV-20260814-0003"
    assert found.distance_m == pytest.approx(1.0)


def test_too_far_for_the_elapsed_time_is_not_a_match() -> None:
    """1초 만에 4m 를 이동할 수는 없다. 다른 사람이다."""
    assert match(1.0, (8.55, 7.90)) is None


def test_the_same_distance_matches_once_enough_time_has_passed() -> None:
    assert match(3.0, (8.05, 7.90)) is not None


def test_outside_the_time_window_is_not_a_match() -> None:
    """시간 창을 넘기면 위치가 아무리 가까워도 결합하지 않는다."""
    assert match(11.0, (4.55, 7.90)) is None


def test_events_that_lost_after_the_appearance_are_ignored() -> None:
    """미래에 끊긴 트랙에 이어 붙일 수는 없다."""
    assert match(-1.0, (4.55, 7.90)) is None


def test_only_the_nearest_candidate_wins() -> None:
    """두 사람이 동시에 가려졌다 나오는 상황. 1:1 이 아니면 이벤트가 복제된다."""
    found = match(
        3.0,
        (5.00, 7.90),
        [lost(3, (4.55, 7.90)), lost(7, (6.00, 7.90))],
    )
    assert found is not None
    assert found.event_id == "EV-20260814-0003"
    assert found.distance_m == pytest.approx(0.45)
