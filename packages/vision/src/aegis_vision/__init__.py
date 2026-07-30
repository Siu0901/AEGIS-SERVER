"""AEGIS 순수 로직 — 호모그래피 · 접지점 · 구역 · 거리 · 자세.

**하드웨어 의존이 0이며 I/O가 없다.** DB · 네트워크 · 파일 · 시간 전부 금지이고
순수 함수만 둔다(CLAUDE.md 절대규칙 2). 시간이 필요하면 `clock.Clock` 을 주입받는다.

| 모듈 | FN | 내용 |
|---|---|---|
| `clock` | — | 시계 주입 (`RealClock` 만 시스템 시계를 읽는다) |
| `homography` | FN-DET-06 · FN-CFG-01 | 실측 4점 → H, 픽셀 ↔ 미터 양방향 |
| `footpoint` | FN-DET-06 | 마스크 하위 8% 무게중심 → 접지점 |
| `zones` | FN-DET-07 | 폴리곤 판정 + 히스테리시스(`buffer_m`) |
| `distance` | FN-DET-08 · 09 | 지면 거리 — `bbox_center` / `mask_nearest` |

좌표 규약은 **두 종류뿐**이다 — 접미사 없으면 정규화 픽셀(0.0~1.0), `_m` 이면 지면
미터. 두 종류를 같은 식에 섞지 않는다(API명세서 §1.2).
"""

from .clock import Clock, FakeClock, RealClock
from .distance import (
    distance_bbox_center_m,
    distance_mask_nearest_m,
    ground_distance_m,
    nearest_pair_m,
    project_to_ground,
    within_radius,
)
from .footpoint import (
    FOOT_BAND_RATIO,
    FootPoint,
    FootPointError,
    bbox_foot_point,
    foot_confidence,
    foot_point_from_mask,
    mask_foot_point,
)
from .homography import (
    MIN_CORRESPONDENCES,
    CalibrationError,
    Correspondence,
    Homography,
    Matrix3,
    PointM,
    PointPx,
)
from .zones import ZoneShape, point_in_polygon, signed_distance_m, zone_for_point, zone_state

__all__ = [
    "FOOT_BAND_RATIO",
    "MIN_CORRESPONDENCES",
    "CalibrationError",
    "Clock",
    "Correspondence",
    "FakeClock",
    "FootPoint",
    "FootPointError",
    "Homography",
    "Matrix3",
    "PointM",
    "PointPx",
    "RealClock",
    "ZoneShape",
    "bbox_foot_point",
    "distance_bbox_center_m",
    "distance_mask_nearest_m",
    "foot_confidence",
    "foot_point_from_mask",
    "ground_distance_m",
    "mask_foot_point",
    "nearest_pair_m",
    "point_in_polygon",
    "project_to_ground",
    "signed_distance_m",
    "within_radius",
    "zone_for_point",
    "zone_state",
]
