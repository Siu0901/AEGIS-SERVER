"""금지구역 판정과 히스테리시스. FN-DET-07

좌표는 전부 **지면 미터**다. 개발용 구역(`scripts/seed_zones.py` 의 `forklift_lane`,
x 2~7 · y 6~11)을 그대로 써서, 시나리오와 같은 숫자 위에서 검증한다.
"""

from __future__ import annotations

import pytest

from aegis_vision.zones import (
    ZoneShape,
    point_in_polygon,
    signed_distance_m,
    zone_for_point,
    zone_state,
)

LANE = ZoneShape(
    zone_id="forklift_lane",
    polygon_m=((2.0, 6.0), (7.0, 6.0), (7.0, 11.0), (2.0, 11.0)),
    buffer_m=0.3,
)


@pytest.mark.parametrize(
    ("point", "inside"),
    [
        ((4.5, 8.5), True),
        ((2.0, 6.0), True),  # 꼭짓점 — 경계는 안이다
        ((7.0, 8.0), True),  # 변 위
        ((1.99, 8.0), False),
        ((8.28, 9.00), False),  # no_helmet 시나리오의 출발점
        ((4.5, 5.9), False),
    ],
)
def test_point_in_polygon(point: tuple[float, float], inside: bool) -> None:
    assert point_in_polygon(point, LANE.polygon_m) is inside


def test_polygon_needs_three_vertices() -> None:
    with pytest.raises(ValueError, match="3개 이상"):
        point_in_polygon((0.0, 0.0), [(0.0, 0.0), (1.0, 1.0)])


def test_zone_shape_rejects_degenerate_input() -> None:
    with pytest.raises(ValueError, match="3개 이상"):
        ZoneShape(zone_id="bad", polygon_m=((0.0, 0.0), (1.0, 0.0)))
    with pytest.raises(ValueError, match="buffer_m"):
        ZoneShape(zone_id="bad", polygon_m=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)), buffer_m=-0.1)


def test_signed_distance_sign_and_size() -> None:
    assert signed_distance_m((4.5, 8.5), LANE.polygon_m) == pytest.approx(2.5)
    assert signed_distance_m((8.0, 8.5), LANE.polygon_m) == pytest.approx(-1.0)
    assert signed_distance_m((7.0, 8.5), LANE.polygon_m) == pytest.approx(0.0)


# --------------------------------------------------------------------------
# 히스테리시스 — 경계선 떨림
# --------------------------------------------------------------------------


def test_enters_at_the_buffer_line_before_the_boundary() -> None:
    """버퍼만큼 바깥에서 이미 진입이다 — 사전 경고와 호모그래피 오차 흡수(§4.5)."""
    just_outside = (7.0 + LANE.buffer_m - 0.01, 8.0)
    assert zone_state(just_outside, LANE, was_inside=False) is True


def test_does_not_enter_beyond_the_buffer_line() -> None:
    assert zone_state((7.0 + LANE.buffer_m + 0.01, 8.0), LANE, was_inside=False) is False


def test_stays_inside_between_the_two_lines() -> None:
    """진입선과 이탈선 사이 — 직전에 안이었으면 그대로 안이다."""
    between = (7.0 + LANE.buffer_m + 0.1, 8.0)
    assert zone_state(between, LANE, was_inside=True) is True
    assert zone_state(between, LANE, was_inside=False) is False


def test_leaves_only_past_the_exit_line() -> None:
    assert zone_state((7.0 + 2 * LANE.buffer_m + 0.01, 8.0), LANE, was_inside=True) is False


def test_boundary_jitter_does_not_toggle() -> None:
    """경계에서 ±5cm 흔들리는 접지점. 단일 임계값이면 여기서 켜졌다 꺼졌다 한다.

    그러면 `zone_intrusion` 후보가 끊겨 확정 타이머(3초)가 영원히 차지 않는다.
    """
    inside = False
    states: list[bool] = []
    for offset in (-0.05, 0.05, -0.04, 0.06, -0.05, 0.05):
        inside = zone_state((7.0 + offset, 8.0), LANE, was_inside=inside)
        states.append(inside)
    assert states == [True] * 6


def test_zero_buffer_collapses_to_the_boundary() -> None:
    """`buffer_m = 0` 이면 히스테리시스가 없다 — "여유 없음"의 자연스러운 뜻이다."""
    sharp = ZoneShape(zone_id="sharp", polygon_m=LANE.polygon_m, buffer_m=0.0)
    assert zone_state((6.99, 8.0), sharp, was_inside=False) is True
    assert zone_state((7.01, 8.0), sharp, was_inside=True) is False


# --------------------------------------------------------------------------
# 여러 구역
# --------------------------------------------------------------------------


def test_zone_for_point_picks_the_narrower_overlap() -> None:
    """겹친 구역에서는 더 좁은 쪽이다 — 목록 순서가 판정을 바꾸면 안 된다."""
    wide = ZoneShape(zone_id="wide", polygon_m=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)))
    narrow = ZoneShape(zone_id="narrow", polygon_m=((4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0)))
    assert zone_for_point((5.0, 5.0), [wide, narrow]) == "narrow"
    assert zone_for_point((5.0, 5.0), [narrow, wide]) == "narrow"


def test_zone_for_point_returns_none_outside() -> None:
    assert zone_for_point((0.5, 0.5), [LANE]) is None


def test_zone_for_point_keeps_previous_zone_within_hysteresis() -> None:
    between = (7.0 + LANE.buffer_m + 0.1, 8.0)
    assert zone_for_point(between, [LANE], previous_zone_id="forklift_lane") == "forklift_lane"
    assert zone_for_point(between, [LANE], previous_zone_id=None) is None
