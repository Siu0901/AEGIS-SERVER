"""접지점 — 합성 마스크로 검증한다. FN-DET-06 · API명세서 §6.1

마스크는 정규화 픽셀 점들의 목록이므로 손으로 만들 수 있다. 실제 영상도 세그멘테이션
모델도 필요 없다.
"""

from __future__ import annotations

import pytest

from aegis_vision.footpoint import (
    FootPointError,
    band_width,
    bbox_foot_point,
    foot_confidence,
    foot_point_from_mask,
    mask_foot_point,
)
from aegis_vision.homography import PointPx


def _rectangle(x1: float, y1: float, x2: float, y2: float, *, step: float = 0.005) -> list[PointPx]:
    """가득 찬 직사각형 마스크. 합성용이라 격자로 채운다."""
    points: list[PointPx] = []
    y = y1
    while y <= y2 + 1e-9:
        x = x1
        while x <= x2 + 1e-9:
            points.append((round(x, 6), round(y, 6)))
            x += step
        y += step
    return points


def test_bbox_foot_point_is_bottom_center() -> None:
    point = bbox_foot_point((0.2, 0.3, 0.4, 0.8))
    assert point[0] == pytest.approx(0.3)
    assert point[1] == pytest.approx(0.8)


def test_bbox_foot_point_rejects_inverted_box() -> None:
    with pytest.raises(FootPointError, match="뒤집"):
        bbox_foot_point((0.4, 0.3, 0.2, 0.8))


def test_mask_foot_point_is_bottom_median() -> None:
    """직사각형 마스크에서는 아래변 중앙과 같아야 한다."""
    mask = _rectangle(0.20, 0.30, 0.40, 0.80)
    point = mask_foot_point(mask)
    assert point[0] == pytest.approx(0.30, abs=1e-3)
    assert point[1] == pytest.approx(0.80, abs=1e-9)


def test_spread_legs_do_not_pull_the_point_into_the_gap() -> None:
    """다리를 벌린 자세 — 두 발 사이는 비어 있다.

    §6.1 이 평균이 아니라 **중앙값**을 쓰라고 한 이유가 이것이다. 중앙값은 픽셀이
    실제로 있는 쪽에 붙고, 평균은 발 사이의 빈 공간을 가리킨다. 두 발의 픽셀 수가
    같으면 중앙값도 가운데로 오므로, 한쪽 발이 더 크게 보이는(가까운) 경우로 만든다.
    """
    left = _rectangle(0.20, 0.74, 0.26, 0.80)
    right = _rectangle(0.36, 0.74, 0.39, 0.80)
    point = mask_foot_point([*left, *right])
    # 왼발 픽셀이 더 많으므로 중앙값은 왼발 쪽이다 — 빈 공간(0.31)이 아니다.
    assert point[0] < 0.30


def test_band_is_taken_from_the_y_range_not_the_count() -> None:
    """아래쪽에 픽셀이 몰려 있어도 띠는 y 범위의 8% 다."""
    body = _rectangle(0.20, 0.30, 0.40, 0.70, step=0.02)
    feet = _rectangle(0.28, 0.78, 0.32, 0.80, step=0.002)
    mask = [*body, *feet]
    # 개수 기준이었다면 촘촘한 발 픽셀이 띠를 독점하지만, y 범위 기준이면 하위 8%
    # (0.76 이상)만 들어온다 — 결과는 같은 발 영역이되 이유가 다르다.
    assert band_width(mask) == pytest.approx(0.04, abs=1e-6)


def test_empty_mask_is_rejected() -> None:
    with pytest.raises(FootPointError, match="비어"):
        mask_foot_point([])


def test_invalid_band_ratio_is_rejected() -> None:
    with pytest.raises(FootPointError, match="band_ratio"):
        mask_foot_point(_rectangle(0.2, 0.3, 0.4, 0.8), band_ratio=0.0)


# --------------------------------------------------------------------------
# foot_conf — 저하 요인 셋
# --------------------------------------------------------------------------


def test_full_mask_has_full_confidence() -> None:
    conf = foot_confidence(
        band_pixels=120,
        expected_band_pixels=100.0,
        band_width=0.05,
        bbox_width=0.10,
        max_spread_ratio=0.6,
    )
    assert conf == 1.0


def test_distant_person_loses_confidence_by_pixel_count() -> None:
    """원거리 — 띠에 남는 픽셀이 줄어든다."""
    conf = foot_confidence(
        band_pixels=25,
        expected_band_pixels=100.0,
        band_width=0.02,
        bbox_width=0.05,
        max_spread_ratio=0.6,
    )
    assert conf == pytest.approx(0.25)


def test_shadow_smear_loses_confidence_by_spread() -> None:
    """그림자 혼입 — 띠가 bbox 폭을 거의 다 덮는다."""
    conf = foot_confidence(
        band_pixels=200,
        expected_band_pixels=100.0,
        band_width=0.10,
        bbox_width=0.10,
        max_spread_ratio=0.6,
    )
    assert conf == 0.0


def test_confidence_rejects_out_of_range_arguments() -> None:
    with pytest.raises(FootPointError, match="범위"):
        foot_confidence(
            band_pixels=10,
            expected_band_pixels=0.0,
            band_width=0.02,
            bbox_width=0.05,
            max_spread_ratio=0.6,
        )


def test_mask_path_reports_point_and_confidence_together() -> None:
    mask = _rectangle(0.20, 0.30, 0.40, 0.80, step=0.01)
    result = foot_point_from_mask(
        mask,
        bbox=(0.20, 0.30, 0.40, 0.80),
        expected_band_pixels=40.0,
        max_spread_ratio=0.6,
    )
    assert result.point[1] == pytest.approx(0.80)
    assert result.band_pixels > 0
    # 직사각형 마스크는 띠 폭이 bbox 폭과 같아 그림자 감점이 최대다 — 합성 마스크의
    # 성질이지 코드 결함이 아니라는 것을 여기서 못박는다.
    assert result.conf == 0.0
