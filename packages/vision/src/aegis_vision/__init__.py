"""AEGIS 순수 로직 — 호모그래피 · 접지점 · 구역 · 거리 · 자세.

**하드웨어 의존이 0이며 I/O가 없다.** DB · 네트워크 · 파일 · 시간 전부 금지이고
순수 함수만 둔다(CLAUDE.md 절대규칙 2). 시간이 필요하면 `clock.Clock` 을 주입받는다.

| 모듈 | FN | 내용 |
|---|---|---|
| `clock` | — | 시계 주입 (`RealClock` 만 시스템 시계를 읽는다) |
| `homography` | FN-DET-06 · FN-CFG-01 | 실측 4점 → H, 픽셀 ↔ 미터 양방향 |
| `footpoint` | FN-DET-06 | 마스크 하위 8% 무게중심 → 접지점 |
| `zones` | FN-DET-07 | 폴리곤 판정 + 히스테리시스(`buffer_m`) |
| `distance` | FN-DET-08 · 09 | 지면 거리 · 근접 후보 — `bbox_center` / `mask_nearest` |
| `posture` | FN-DET-10 | 쓰러짐 3조건 — 높이 비율 · 주축 각도 · 정지 지속 |
| `depth` | FN-DET-11 | 뎁스 온디맨드 트리거와 캐시 (**모델은 부르지 않는다**) |

좌표 규약은 **두 종류뿐**이다 — 접미사 없으면 정규화 픽셀(0.0~1.0), `_m` 이면 지면
미터. 두 종류를 같은 식에 섞지 않는다(API명세서 §1.2).
"""

from .clock import Clock, FakeClock, RealClock
from .depth import (
    DepthCache,
    DepthProbe,
    DepthResult,
    DepthTrigger,
    DepthTriggers,
    bbox_iou,
    depth_triggers,
)
from .depth import verify as verify_depth
from .distance import (
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
    Bbox,
    CalibrationError,
    Correspondence,
    Homography,
    Matrix3,
    PointM,
    PointPx,
)
from .occupancy import OccupancyTracker, mask_overlap_ratio, point_in_mask
from .posture import (
    FallThresholds,
    MaskShape,
    PostureReading,
    ReferenceHeight,
    StillnessTracker,
    axis_angle_deg,
    expected_height_px,
    height_ratio,
    mask_shape,
    perspective_scale,
    posture_of,
)
from .zones import ZoneShape, point_in_polygon, signed_distance_m, zone_for_point, zone_state

__all__ = [
    "FOOT_BAND_RATIO",
    "MIN_CORRESPONDENCES",
    "Bbox",
    "CalibrationError",
    "Clock",
    "Correspondence",
    "DepthCache",
    "DepthProbe",
    "DepthResult",
    "DepthTrigger",
    "DepthTriggers",
    "FakeClock",
    "FallThresholds",
    "FootPoint",
    "FootPointError",
    "Homography",
    "MaskShape",
    "Matrix3",
    "NearbyReading",
    "OccupancyTracker",
    "PointM",
    "PointPx",
    "PostureReading",
    "ProximityRadii",
    "RealClock",
    "ReferenceHeight",
    "StillnessTracker",
    "ZoneShape",
    "axis_angle_deg",
    "bbox_foot_point",
    "bbox_iou",
    "depth_triggers",
    "distance_bbox_center_m",
    "distance_mask_nearest_m",
    "expected_height_px",
    "foot_confidence",
    "foot_point_from_mask",
    "ground_distance_m",
    "height_ratio",
    "mask_foot_point",
    "mask_overlap_ratio",
    "mask_shape",
    "nearest_pair_m",
    "perspective_scale",
    "point_in_mask",
    "point_in_polygon",
    "posture_of",
    "project_to_ground",
    "proximity_candidate",
    "screen_nearby",
    "signed_distance_m",
    "verify_depth",
    "within_radius",
    "zone_for_point",
    "zone_state",
]
