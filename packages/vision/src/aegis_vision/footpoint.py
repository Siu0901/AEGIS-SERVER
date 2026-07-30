"""접지점 산출 — 사람이 지면에 닿는 한 점을 정한다. FN-DET-06

출처: API명세서 §6.1 (`foot_point`) · 기능명세서 FN-DET-06

```
마스크 기반 (정밀)
  1. 마스크 픽셀 중 y좌표 하위 8% 구간 추출 → 발 근처 픽셀 띠
  2. 그 띠의 x 중앙값 → 두 발 사이 중심 (다리를 벌려도 안정적)
  3. 정규화 좌표로 변환

bbox 기반 (초기 구현)
  아래변 중앙 [(x1+x2)/2, y2]
```

**여기서 미터로 바꾸지 않는다.** 접지점은 정규화 픽셀이고, 지면 좌표 변환은
`homography.Homography.to_ground` 가 한다. 두 단계를 한 함수에 합치면 캘리브레이션이
없는 카메라에서 접지점만 얻는 경로가 사라진다.

**평균이 아니라 중앙값을 쓰는 이유**: 다리를 벌리고 서면 x 분포가 양봉이 되는데,
평균은 두 발 사이의 빈 공간을 가리키고 중앙값은 픽셀이 실제로 있는 쪽에 붙는다.
그림자가 한쪽으로 길게 늘어졌을 때도 중앙값이 덜 끌려간다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aegis_vision.homography import PointPx

__all__ = [
    "FOOT_BAND_RATIO",
    "FootPoint",
    "FootPointError",
    "band_width",
    "bbox_foot_point",
    "foot_confidence",
    "foot_point_from_mask",
    "mask_foot_point",
]

#: 발 영역으로 보는 마스크 하위 구간 비율. API명세서 §6.1 이 정한 값(8%)이다.
#:
#: 튜닝 파라미터가 아니라 **산출법의 정의**이므로 여기 둔다. 임계값(신뢰도 하한 등)은
#: `edge/config.yaml` 소관이다(CLAUDE.md 절대규칙 6).
FOOT_BAND_RATIO = 0.08


class FootPointError(ValueError):
    """접지점을 낼 수 없다 — 마스크가 비었거나 bbox 가 뒤집혔다."""


@dataclass(frozen=True, slots=True)
class FootPoint:
    """접지점 하나와 그 근거.

    `conf` 는 `frame.foot_conf`(§2.1)로 그대로 나가고, 낮으면 **엣지가** 뎁스 검증
    트리거 C 를 발동한다(§6.1). 그래서 근거가 되는 픽셀 수를 함께 들고 있다 —
    "신뢰도가 낮다"와 "왜 낮은지"가 같은 자리에 있어야 카메라 각도를 고칠 수 있다.
    """

    point: PointPx
    conf: float
    band_pixels: int
    """접지점을 정한 하위 띠의 픽셀 수."""


def bbox_foot_point(bbox: tuple[float, float, float, float]) -> PointPx:
    """bbox 아래변 중앙. API명세서 §6.1 「bbox 기반 (초기 구현)」

    마스크가 없을 때만 쓴다. 다리를 벌리거나 팔을 뻗으면 중앙이 실제 접지점에서
    벗어나므로, 마스크가 있으면 반드시 `mask_foot_point` 를 쓴다.
    """
    x1, y1, x2, y2 = (float(value) for value in bbox)
    if x2 < x1 or y2 < y1:
        msg = f"bbox 가 뒤집혀 있다: {bbox!r}"
        raise FootPointError(msg)
    return ((x1 + x2) / 2.0, y2)


def mask_foot_point(
    pixels: Sequence[PointPx],
    *,
    band_ratio: float = FOOT_BAND_RATIO,
) -> PointPx:
    """마스크 픽셀에서 접지점을 뽑는다. API명세서 §6.1

    `pixels` 는 **정규화 픽셀 좌표**의 마스크 점들이다. 하위 `band_ratio` 구간을
    y 범위 기준으로 잘라내고 그 띠의 x 중앙값과 최하단 y 를 접지점으로 삼는다.

    띠를 **개수 비율이 아니라 y 범위 비율로** 자른다. 개수로 자르면 그림자처럼 아래쪽에
    픽셀이 몰린 마스크에서 띠가 발목 위까지 올라오고, 반대로 발끝만 보이는 마스크에서는
    한두 점만 남아 흔들린다.
    """
    band = _band(pixels, band_ratio)
    xs = sorted(float(point[0]) for point in band)
    bottom = max(float(point[1]) for point in pixels)
    return (_median(xs), bottom)


def foot_point_from_mask(
    pixels: Sequence[PointPx],
    *,
    bbox: tuple[float, float, float, float],
    expected_band_pixels: float,
    max_spread_ratio: float,
    band_ratio: float = FOOT_BAND_RATIO,
) -> FootPoint:
    """FN-DET-06 의 마스크 경로 전체 — 접지점과 신뢰도를 함께 낸다.

    마스크가 비어 있으면 **조용히 bbox 로 넘어가지 않는다.** 부르는 쪽이
    `bbox_foot_point` 를 명시적으로 골라야 한다 — 정밀 경로와 초기 구현 경로가 같은
    호출로 섞이면 `foot_conf` 가 무엇을 근거로 나온 값인지 알 수 없게 된다.
    """
    band = _band(pixels, band_ratio)
    point = mask_foot_point(pixels, band_ratio=band_ratio)
    x1, _, x2, _ = (float(value) for value in bbox)
    conf = foot_confidence(
        band_pixels=len(band),
        expected_band_pixels=expected_band_pixels,
        band_width=band_width(pixels, band_ratio=band_ratio),
        bbox_width=abs(x2 - x1),
        max_spread_ratio=max_spread_ratio,
    )
    return FootPoint(point=point, conf=conf, band_pixels=len(band))


def foot_confidence(
    *,
    band_pixels: int,
    expected_band_pixels: float,
    band_width: float,
    bbox_width: float,
    max_spread_ratio: float,
) -> float:
    """접지점 신뢰도 0~1. API명세서 §6.1 「`foot_conf` 저하 요인」

    저하 요인 셋을 각각 하나의 비율로 옮긴다.

    | 요인 | 표현 |
    |---|---|
    | 픽셀 수 부족(원거리) | `band_pixels / expected_band_pixels` (1에서 포화) |
    | 발 영역 가림 | 같은 비율 — 가려지면 띠의 픽셀이 줄어든다 |
    | 그림자 혼입 | 띠의 x 폭이 bbox 폭 대비 `max_spread_ratio` 를 넘는 만큼 감점 |

    **기대 픽셀 수와 폭 상한은 인자로 받는다.** 카메라 화각과 설치 높이에 따라 달라지는
    튜닝값이라 `edge/config.yaml` 에 있어야 하고, 이 순수 함수가 기본값을 들고 있으면
    그 순간 임계값이 코드에 박힌다(CLAUDE.md 절대규칙 6).
    """
    if expected_band_pixels <= 0 or bbox_width <= 0 or not 0.0 < max_spread_ratio <= 1.0:
        msg = (
            "foot_confidence 인자가 범위를 벗어났다: "
            f"expected_band_pixels={expected_band_pixels!r} bbox_width={bbox_width!r} "
            f"max_spread_ratio={max_spread_ratio!r}"
        )
        raise FootPointError(msg)

    coverage = min(1.0, max(0.0, band_pixels / expected_band_pixels))
    spread_ratio = max(0.0, band_width) / bbox_width
    excess = max(0.0, spread_ratio - max_spread_ratio)
    # 상한을 넘은 만큼 선형으로 깎되 0 아래로 내려가지 않는다. 띠 폭이 bbox 전체가 되면
    # (그림자가 발밑을 통째로 덮은 경우) 감점이 최대가 된다.
    spread_penalty = max(0.0, 1.0 - excess / max(1e-9, 1.0 - max_spread_ratio))
    return round(coverage * spread_penalty, 4)


def band_width(pixels: Sequence[PointPx], *, band_ratio: float = FOOT_BAND_RATIO) -> float:
    """하위 띠의 x 폭. `foot_confidence` 의 그림자 감점 입력이다."""
    xs = [float(point[0]) for point in _band(pixels, band_ratio)]
    return abs(max(xs) - min(xs))


def _band(pixels: Sequence[PointPx], band_ratio: float) -> list[PointPx]:
    """마스크의 하위 `band_ratio` 구간(발 근처 픽셀 띠)."""
    if not pixels:
        msg = "마스크 픽셀이 비어 있다"
        raise FootPointError(msg)
    if not 0.0 < band_ratio <= 1.0:
        msg = f"band_ratio 는 0 초과 1 이하여야 한다: {band_ratio!r}"
        raise FootPointError(msg)
    ys = [float(point[1]) for point in pixels]
    threshold = max(ys) - (max(ys) - min(ys)) * band_ratio
    band = [point for point in pixels if float(point[1]) >= threshold]
    # 모든 점의 y 가 같으면(수평선 마스크) 띠가 전체와 같다.
    return band or list(pixels)


def _median(sorted_values: Sequence[float]) -> float:
    count = len(sorted_values)
    middle = count // 2
    if count % 2 == 1:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2.0
