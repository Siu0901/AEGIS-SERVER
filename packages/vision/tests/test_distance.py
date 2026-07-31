"""지면 거리 — `bbox_center` 와 `mask_nearest`. FN-DET-08 · FN-DET-09

포크가 뻗은 지게차에서 두 방식이 **다른 답을 내는지**가 핵심이다. 같은 답이 나오면
FN-DET-09 를 따로 만들 이유가 없다.
"""

from __future__ import annotations

import pytest

from aegis_vision.distance import (
    NearbyReading,
    ProximityRadii,
    distance_bbox_center_m,
    distance_mask_nearest_m,
    ground_distance_m,
    nearest_pair_m,
    project_to_ground,
    proximity_candidate,
    screen_nearby,
    within_radius,
)
from aegis_vision.homography import Correspondence, Homography, PointPx

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


# --- FN-DET-09 · 합성 마스크로 두 방식을 갈라 놓는다 -----------------------


def _rect(x1: float, y1: float, x2: float, y2: float, *, step: float = 0.01) -> list[PointPx]:
    """축 정렬 직사각형의 윤곽점. 합성 마스크의 부품이다."""
    points: list[PointPx] = []
    count_x = max(int((x2 - x1) / step), 1)
    count_y = max(int((y2 - y1) / step), 1)
    for i in range(count_x + 1):
        x = x1 + (x2 - x1) * i / count_x
        points.extend([(x, y1), (x, y2)])
    for j in range(count_y + 1):
        y = y1 + (y2 - y1) * j / count_y
        points.extend([(x1, y), (x2, y)])
    return points


def _forklift_with_fork() -> tuple[list[PointPx], tuple[float, float, float, float]]:
    """★ 포크가 **사람 쪽으로** 뻗은 지게차. 윤곽과 bbox 를 함께 낸다.

    차체는 오른쪽에 뭉쳐 있고 포크만 왼쪽으로 길게 나온다. 이 형상이 FN-DET-09 의
    존재 이유다 — 질량은 멀리 있는데 **부딪히는 부분은 가까이** 있다.
    """
    body = _rect(0.50, 0.40, 0.70, 0.52)
    fork = _rect(0.30, 0.49, 0.50, 0.51)
    contour = body + fork
    xs = [point[0] for point in contour]
    ys = [point[1] for point in contour]
    return contour, (min(xs), min(ys), max(xs), max(ys))


def test_mask_nearest_and_bbox_center_diverge_on_a_protruding_fork(flat: Homography) -> None:
    """★ 완료 조건 3 — 두 방식이 **다른 값**을 내는 케이스를 합성 마스크로 잠근다.

    중심 거리는 차체 무게중심을 따라가고, 최근접 거리는 포크 끝을 따라간다. 위험
    반경 3.0m 를 사이에 두고 **판정 자체가 갈린다** — 중심으로 재면 안전, 마스크로
    재면 위험이다. 같은 답이 나온다면 FN-DET-09 를 따로 만들 이유가 없다.
    """
    person_contour = _rect(0.10, 0.42, 0.16, 0.52)
    person_bbox = (0.10, 0.42, 0.16, 0.52)
    vehicle_contour, vehicle_bbox = _forklift_with_fork()

    center = distance_bbox_center_m(person_bbox, vehicle_bbox, flat)
    nearest = distance_mask_nearest_m(person_contour, vehicle_contour, flat)

    # bbox 아래변 중앙: 사람 (0.13, 0.52) → (1.3, 5.2) · 지게차 (0.50, 0.52) → (5.0, 5.2)
    assert center == pytest.approx(3.7)
    # 최근접: 사람 오른쪽 변 x=0.16 ↔ 포크 끝 x=0.30 → 1.4m
    assert nearest == pytest.approx(1.4, abs=0.05)
    assert center - nearest > 2.0, "두 방식이 사실상 같은 값이면 이 기능이 필요 없다"

    # 그리고 그 차이가 판정을 바꾼다.
    assert within_radius(center, 3.0) is False
    assert within_radius(nearest, 3.0) is True


def test_on_a_compact_shape_the_gap_is_only_the_half_widths(flat: Homography) -> None:
    """반대편 — 뻗은 부분이 없으면 두 방식의 차이가 **반폭 합**으로 설명된다.

    어떤 형상에서나 크게 벌어진다면 그것은 형상 때문이 아니라 계산이 틀린 것이다.
    사람 반폭 0.3m + 지게차 반폭 0.3m = 0.6m 이 두 값의 전부여야 한다.
    """
    person_contour = _rect(0.10, 0.48, 0.16, 0.52)
    vehicle_contour = _rect(0.50, 0.48, 0.56, 0.52)
    center = distance_bbox_center_m((0.10, 0.48, 0.16, 0.52), (0.50, 0.48, 0.56, 0.52), flat)
    nearest = distance_mask_nearest_m(person_contour, vehicle_contour, flat)
    assert center == pytest.approx(4.0)
    assert nearest == pytest.approx(3.4, abs=0.05)
    assert center - nearest == pytest.approx(0.6, abs=0.05)


# --- FN-DET-08 · 근접 후보 --------------------------------------------------


RADII = ProximityRadii(screening_m=5.0, danger_m=3.0, warn_m=2.0)


def _reading(track_id: int, dist_m: float, *, moving: bool = False) -> NearbyReading:
    return NearbyReading(
        track_id=track_id,
        dist_m=dist_m,
        method="mask_nearest",
        moving=moving,
        within_danger_radius=dist_m <= RADII.danger_m,
    )


def test_radii_must_be_ordered() -> None:
    """경고 ≤ 위험 ≤ 스크리닝. 뒤집힌 설정은 조용히 통과하면 안 된다."""
    with pytest.raises(ValueError, match="순서"):
        ProximityRadii(screening_m=5.0, danger_m=1.0, warn_m=2.0)


def test_screening_keeps_only_what_is_within_five_metres() -> None:
    """`nearby[]` 는 스크리닝 반경 안만 담는다(§2.2). 가까운 순으로 정렬한다."""
    readings = [_reading(11, 6.0), _reading(12, 4.0), _reading(13, 1.2)]
    kept = screen_nearby(readings, RADII)
    assert [item.track_id for item in kept] == [13, 12]


def test_a_forklift_inside_the_danger_radius_is_not_yet_a_candidate() -> None:
    """★ 위험 반경(3.0m)과 경고 임계(2.0m)는 다른 것을 정한다(§4.5).

    3m 안은 화면에 위험으로 표시되지만, 후보가 되어 방송까지 가려면 2m 안이라야 한다.
    둘을 하나로 합치면 통로 폭에 맞춰 조정할 자리가 사라진다.
    """
    inside_danger = _reading(11, 2.6)
    assert inside_danger.within_danger_radius is True
    assert proximity_candidate([inside_danger], RADII) is None


def test_the_nearest_forklift_within_the_warning_radius_becomes_the_candidate() -> None:
    readings = [_reading(11, 1.8), _reading(12, 1.1), _reading(13, 4.0)]
    candidate = proximity_candidate(readings, RADII)
    assert candidate is not None
    assert candidate.track_id == 12


def test_a_moving_forklift_outranks_a_closer_stopped_one() -> None:
    """FN-DET-08 ④ — 이동 중이면 위험도를 상향 조정한다.

    3m 에서 달려오는 지게차가 2m 에 멈춰 선 지게차보다 위험하다. 다만 **둘 다 경고
    임계 안**일 때의 우선순위 문제이지, 임계값 자체를 넓히는 것이 아니다.
    """
    stopped_closer = _reading(11, 1.0, moving=False)
    moving_farther = _reading(12, 1.9, moving=True)
    candidate = proximity_candidate([stopped_closer, moving_farther], RADII)
    assert candidate is not None
    assert candidate.track_id == 12


def test_moving_does_not_widen_the_threshold() -> None:
    """★ 이동 중이라고 경고 거리를 늘리지 않는다.

    늘리면 같은 거리에서 서로 다른 판정이 나오고, 그 차이는 이벤트 기록에 남지 않아
    나중에 설명할 수 없다.
    """
    assert proximity_candidate([_reading(11, 2.4, moving=True)], RADII) is None


def test_depth_verification_is_not_required_outside_the_grey_band() -> None:
    """§6.6 — 트리거 미충족이면 `depth_verified` 는 항상 `False` 다.

    늘 `True` 를 요구하면 회색지대 밖의 근접이 영영 잡히지 않는다.
    """
    reading = _reading(11, 0.8)
    assert reading.depth_verified is False
    assert proximity_candidate([reading], RADII) is not None
