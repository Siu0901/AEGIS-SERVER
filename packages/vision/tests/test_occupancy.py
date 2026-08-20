"""차량 탑승자 판별 — FN-DET-13 (기능명세서 §4.1)"""

from __future__ import annotations

from aegis_vision import OccupancyTracker, mask_overlap_ratio, point_in_mask

#: 차량 몸통. 정규화 화면 좌표다.
VEHICLE = ((0.40, 0.40), (0.80, 0.40), (0.80, 0.80), (0.40, 0.80))


def _square(x: float, y: float, size: float) -> tuple[tuple[float, float], ...]:
    return ((x, y), (x + size, y), (x + size, y + size), (x, y + size))


def _tracker() -> OccupancyTracker:
    return OccupancyTracker(confirm_s=1.5, release_s=3.0, overlap_min=0.35)


def test_point_in_mask_uses_screen_coordinates() -> None:
    assert point_in_mask((0.6, 0.6), VEHICLE)
    assert not point_in_mask((0.2, 0.6), VEHICLE)


def test_overlap_ratio_divides_by_the_person_area() -> None:
    """분모는 **사람 넓이**다. 차량으로 나누면 탑승 중이어도 0 에 가깝다."""
    inside = _square(0.50, 0.50, 0.10)
    assert mask_overlap_ratio(inside, VEHICLE) == 1.0
    outside = _square(0.05, 0.05, 0.10)
    assert mask_overlap_ratio(outside, VEHICLE) == 0.0


def test_riding_needs_the_confirm_duration() -> None:
    """①②를 채워도 `occupancy_confirm_s` 전에는 탑승이 아니다."""
    tracker = _tracker()
    person, foot = _square(0.50, 0.50, 0.10), (0.55, 0.60)
    assert (
        tracker.update(
            person_track_id=3,
            person_mask=person,
            person_foot=foot,
            vehicles={11: VEHICLE},
            at_s=0.0,
        )
        is None
    )
    assert (
        tracker.update(
            person_track_id=3,
            person_mask=person,
            person_foot=foot,
            vehicles={11: VEHICLE},
            at_s=1.4,
        )
        is None
    )
    assert (
        tracker.update(
            person_track_id=3,
            person_mask=person,
            person_foot=foot,
            vehicles={11: VEHICLE},
            at_s=1.6,
        )
        == 11
    )


def test_a_person_standing_behind_the_vehicle_is_not_riding() -> None:
    """★ 판별의 핵심 — 겹침이 커도 **접지점이 차량 밖**이면 탑승이 아니다.

    가림 때문에 마스크는 겹치지만 발은 지면에 있다. 겹침만으로 판단하면 뒤에 선
    사람을 탑승자로 오인하고, 그 오인은 실제 위험을 통째로 놓치는 방향이다.
    """
    tracker = _tracker()
    # 몸통은 차량과 완전히 겹치지만 발은 차량 아래(밖)를 딛고 있다.
    person, foot = _square(0.50, 0.50, 0.10), (0.55, 0.95)
    for at_s in (0.0, 2.0, 4.0):
        assert (
            tracker.update(
                person_track_id=3,
                person_mask=person,
                person_foot=foot,
                vehicles={11: VEHICLE},
                at_s=at_s,
            )
            is None
        )


def test_release_is_slower_than_confirm() -> None:
    """히스테리시스가 없으면 몸을 기울일 때마다 탑승·하차가 반복된다."""
    tracker = _tracker()
    person, foot = _square(0.50, 0.50, 0.10), (0.55, 0.60)
    tracker.update(
        person_track_id=3, person_mask=person, person_foot=foot, vehicles={11: VEHICLE}, at_s=0.0
    )
    assert (
        tracker.update(
            person_track_id=3,
            person_mask=person,
            person_foot=foot,
            vehicles={11: VEHICLE},
            at_s=2.0,
        )
        == 11
    )
    # 조건이 깨졌다(at_s=4.0). **`release_s` 3초를 채우기 전에는 여전히 탑승이다** —
    # 확정은 1.5초인데 해제는 3초라, 같은 1.5초가 지나도 아직 하차가 아니다.
    away, away_foot = _square(0.05, 0.05, 0.10), (0.10, 0.15)
    assert (
        tracker.update(
            person_track_id=3,
            person_mask=away,
            person_foot=away_foot,
            vehicles={11: VEHICLE},
            at_s=4.0,
        )
        == 11
    )
    assert (
        tracker.update(
            person_track_id=3,
            person_mask=away,
            person_foot=away_foot,
            vehicles={11: VEHICLE},
            at_s=5.5,
        )
        == 11
    )
    assert (
        tracker.update(
            person_track_id=3,
            person_mask=away,
            person_foot=away_foot,
            vehicles={11: VEHICLE},
            at_s=7.5,
        )
        is None
    )


def test_forget_drops_the_state_so_a_reused_id_starts_clean() -> None:
    tracker = _tracker()
    person, foot = _square(0.50, 0.50, 0.10), (0.55, 0.60)
    tracker.update(
        person_track_id=3, person_mask=person, person_foot=foot, vehicles={11: VEHICLE}, at_s=0.0
    )
    tracker.update(
        person_track_id=3, person_mask=person, person_foot=foot, vehicles={11: VEHICLE}, at_s=2.0
    )
    assert tracker.riding_on(3) == 11
    tracker.forget(3)
    assert tracker.riding_on(3) is None
