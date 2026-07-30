"""지면 거리 — `bbox_center` 와 `mask_nearest`. FN-DET-08 · FN-DET-09

포크가 뻗은 지게차에서 두 방식이 **다른 답을 내는지**가 핵심이다. 같은 답이 나오면
FN-DET-09 를 따로 만들 이유가 없다.
"""

from __future__ import annotations

import pytest

from aegis_vision.distance import (
    distance_bbox_center_m,
    distance_mask_nearest_m,
    ground_distance_m,
    nearest_pair_m,
    project_to_ground,
    within_radius,
)
from aegis_vision.homography import Correspondence, Homography

#: 지면을 그대로 재는 캘리브레이션 — 정규화 픽셀 1.0 이 10m 다.
#:
#: 원근이 없어 손으로 검산할 수 있다. 원근이 있는 경우는 `test_homography.py` 가 맡고,
#: 여기서는 **거리 계산 자체**를 본다.
FLAT: list[Correspondence] = [
    ((0.0, 0.0), (0.0, 0.0)),
    ((1.0, 0.0), (10.0, 0.0)),
    ((1.0, 1.0), (10.0, 10.0)),
    ((0.0, 1.0), (0.0, 10.0)),
]


@pytest.fixture(name="flat")
def _flat() -> Homography:
    return Homography.from_correspondences(FLAT)


def test_ground_distance_is_euclidean() -> None:
    assert ground_distance_m((0.0, 0.0), (3.0, 4.0)) == pytest.approx(5.0)


def test_bbox_center_uses_the_bottom_edge(flat: Homography) -> None:
    """아래변 중앙끼리의 거리. bbox 기하 중심은 공중이라 쓰지 않는다."""
    person = (0.10, 0.20, 0.20, 0.50)  # 아래변 중앙 (0.15, 0.50) → (1.5, 5.0)
    vehicle = (0.40, 0.10, 0.60, 0.50)  # 아래변 중앙 (0.50, 0.50) → (5.0, 5.0)
    assert distance_bbox_center_m(person, vehicle, flat) == pytest.approx(3.5)


def test_mask_nearest_is_shorter_when_the_fork_reaches_out(flat: Homography) -> None:
    """포크가 사람 쪽으로 뻗은 지게차.

    bbox 아래변 중앙끼리는 3.5m 로 보이지만, 뻗은 팔(1.8, 4.5)과 포크 끝(3.0, 5.0)
    사이는 1.3m 다. **실제 접촉 위험은 그 두 끝에서 생기므로** 근접 판정은 이쪽 값을
    써야 한다(FN-DET-09).
    """
    person_contour = [(0.15, 0.50), (0.12, 0.45), (0.18, 0.45)]  # 마지막이 뻗은 팔
    vehicle_contour = [
        (0.50, 0.50),  # 차체 중앙
        (0.60, 0.48),
        (0.30, 0.50),  # 포크 끝 → (3.0, 5.0)
    ]
    center = distance_bbox_center_m((0.10, 0.20, 0.20, 0.50), (0.40, 0.10, 0.60, 0.50), flat)
    nearest = distance_mask_nearest_m(person_contour, vehicle_contour, flat)
    assert center == pytest.approx(3.5)
    assert nearest == pytest.approx(1.3)
    assert nearest < center


def test_nearest_pair_reports_both_endpoints(flat: Homography) -> None:
    """오버레이 거리선의 양 끝점이 이 값이다(§5.1)."""
    a = project_to_ground([(0.10, 0.50), (0.20, 0.50)], flat)
    b = project_to_ground([(0.50, 0.50), (0.80, 0.50)], flat)
    distance, point_a, point_b = nearest_pair_m(a, b)
    assert distance == pytest.approx(3.0)
    assert point_a == pytest.approx((2.0, 5.0))
    assert point_b == pytest.approx((5.0, 5.0))


def test_nearest_pair_rejects_empty_contours() -> None:
    with pytest.raises(ValueError, match="점이 없다"):
        nearest_pair_m([], [(0.0, 0.0)])


@pytest.mark.parametrize(
    ("distance", "radius", "expected"),
    [(2.99, 3.0, True), (3.0, 3.0, True), (3.01, 3.0, False)],
)
def test_within_radius_includes_the_boundary(
    distance: float,
    radius: float,
    expected: bool,
) -> None:
    """임계값 자체를 안전 구간으로 두지 않는다 — 3.0m 로 정한 의도가 아니다."""
    assert within_radius(distance, radius) is expected
