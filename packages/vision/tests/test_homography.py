"""호모그래피 — 합성 좌표만으로 검증한다. 실제 영상이 필요 없다.

FN-DET-06 · FN-CFG-01 · API명세서 §6.2

여기서 재는 것은 셋이다.

1. **왕복 오차** — 픽셀 → 미터 → 픽셀 이 제자리로 돌아오는가
2. **재투영 오차** — 실측점을 다시 투영했을 때 얼마나 벗어나는가 (화면에 표시하는 값)
3. **거부** — 점이 모자라거나 한 직선 위에 있으면 실패하는가 (조용히 통과하면 안 된다)
"""

from __future__ import annotations

import math

import pytest

from aegis_vision.homography import CalibrationError, Correspondence, Homography

#: API명세서 §4.5 예시의 4점. 화면에서 클릭한 정규화 좌표와 줄자로 잰 지면 좌표다.
SPEC_POINTS: list[Correspondence] = [
    ((0.21, 0.83), (0.0, 0.0)),
    ((0.68, 0.80), (5.0, 0.0)),
    ((0.75, 0.55), (5.0, 5.0)),
    ((0.28, 0.57), (0.0, 5.0)),
]


def test_four_points_reproduce_exactly() -> None:
    """4점이면 자유도가 정확히 맞으므로 실측점이 그대로 재현된다."""
    homography = Homography.from_correspondences(SPEC_POINTS)
    for px, expected in SPEC_POINTS:
        got = homography.to_ground(px)
        assert got[0] == pytest.approx(expected[0], abs=1e-9)
        assert got[1] == pytest.approx(expected[1], abs=1e-9)
    assert homography.reprojection_error_m(SPEC_POINTS) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize(
    "point",
    [(0.21, 0.83), (0.5, 0.7), (0.68, 0.80), (0.4, 0.6), (0.75, 0.55)],
)
def test_round_trip_returns_to_origin(point: tuple[float, float]) -> None:
    """픽셀 → 미터 → 픽셀 왕복. 정규화 픽셀 1e-9 는 1920px 에서 2e-6 px 다."""
    homography = Homography.from_correspondences(SPEC_POINTS)
    assert homography.round_trip_error_px(point) < 1e-9


def test_ground_round_trip_returns_to_origin() -> None:
    """미터 → 픽셀 → 미터도 같아야 한다. 구역을 화면에 그렸다 되읽는 경로다(FN-UI-07)."""
    homography = Homography.from_correspondences(SPEC_POINTS)
    for target in [(0.0, 0.0), (2.5, 3.0), (5.0, 5.0), (1.2, 4.8)]:
        back = homography.to_ground(homography.to_pixel(target))
        assert math.dist(back, target) < 1e-9


def test_least_squares_absorbs_measurement_noise() -> None:
    """5점 이상이면 최소제곱이다. 한 점만 5cm 틀리게 재도 나머지가 무너지지 않는다."""
    exact = Homography.from_correspondences(SPEC_POINTS)
    noisy: list[Correspondence] = [
        *SPEC_POINTS,
        # 화면 한가운데 점 하나를 5cm 어긋나게 "실측"했다.
        ((0.5, 0.7), _shift(exact.to_ground((0.5, 0.7)), 0.05)),
    ]
    fitted = Homography.from_correspondences(noisy)
    error = fitted.reprojection_error_m(noisy)
    # 오차가 한 점에 몰리지 않고 나뉘므로 RMS 는 5cm 보다 작다.
    assert 0.0 < error < 0.05
    # 그러면서도 캘리브레이션 자체는 살아 있다 — 원래 4점의 재현이 10cm 안쪽이다.
    assert fitted.reprojection_error_m(SPEC_POINTS) < 0.05


def test_matrix_survives_storage_round_trip() -> None:
    """DB `cameras.homography` 에 넣었다 꺼내도 같은 변환이어야 한다."""
    homography = Homography.from_correspondences(SPEC_POINTS)
    restored = Homography.from_matrix(homography.to_rows())
    assert restored.to_ground((0.5, 0.7)) == pytest.approx(homography.to_ground((0.5, 0.7)))


def test_scale_is_normalized() -> None:
    """`matrix[2][2]` 를 1로 고정한다 — 같은 변환이 여러 표기를 갖지 않게."""
    homography = Homography.from_correspondences(SPEC_POINTS)
    assert homography.matrix[2][2] == pytest.approx(1.0)


# --------------------------------------------------------------------------
# 거부 — 조용히 통과시키지 않는다
# --------------------------------------------------------------------------


def test_three_points_are_rejected() -> None:
    with pytest.raises(CalibrationError, match="최소"):
        Homography.from_correspondences(SPEC_POINTS[:3])


def test_collinear_pixels_are_rejected() -> None:
    """통로 한쪽 선을 따라 4점을 찍는 실수. 행렬은 풀리지만 의미가 없다."""
    collinear: list[Correspondence] = [
        ((0.10, 0.80), (0.0, 0.0)),
        ((0.30, 0.80), (2.0, 0.0)),
        ((0.50, 0.80), (4.0, 0.0)),
        ((0.70, 0.80), (6.0, 0.0)),
    ]
    with pytest.raises(CalibrationError, match="직선"):
        Homography.from_correspondences(collinear)


def test_collinear_ground_points_are_rejected() -> None:
    """화면 점은 퍼져 있는데 실측값을 한 줄로 적은 경우."""
    bad: list[Correspondence] = [
        ((0.21, 0.83), (0.0, 0.0)),
        ((0.68, 0.80), (5.0, 0.0)),
        ((0.75, 0.55), (7.0, 0.0)),
        ((0.28, 0.57), (2.0, 0.0)),
    ]
    with pytest.raises(CalibrationError, match="직선"):
        Homography.from_correspondences(bad)


def test_horizon_point_is_rejected() -> None:
    """지평선 위(또는 카메라 뒤)의 픽셀에는 대응하는 지면 점이 없다.

    큰 수를 돌려주면 그 좌표가 거리·구역 판정으로 그대로 흘러간다.
    """
    homography = Homography.from_correspondences(SPEC_POINTS)
    row = homography.matrix[2]
    # W = 0 이 되는 v 를 직접 구한다 (u = 0.5 고정).
    horizon_v = -(row[0] * 0.5 + row[2]) / row[1]
    with pytest.raises(CalibrationError, match="지평선"):
        homography.to_ground((0.5, horizon_v))


def test_non_square_matrix_is_rejected() -> None:
    with pytest.raises(CalibrationError, match="3×3"):
        Homography.from_matrix([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])


def test_singular_matrix_is_rejected() -> None:
    with pytest.raises(CalibrationError, match="행렬식"):
        Homography.from_matrix([[1.0, 2.0, 3.0], [2.0, 4.0, 6.0], [0.0, 0.0, 1.0]])


def test_polygon_conversion_is_symmetric() -> None:
    """화면에서 그린 폴리곤 → 미터 → 화면. FN-CFG-02 가 저장하고 다시 그리는 경로다."""
    homography = Homography.from_correspondences(SPEC_POINTS)
    drawn = [(0.30, 0.78), (0.62, 0.76), (0.66, 0.60), (0.33, 0.61)]
    ground = homography.polygon_to_ground(drawn)
    back = homography.polygon_to_pixel(ground)
    for original, restored in zip(drawn, back, strict=True):
        assert math.dist(original, restored) < 1e-9


def _shift(point: tuple[float, float], distance: float) -> tuple[float, float]:
    return (point[0] + distance, point[1])
