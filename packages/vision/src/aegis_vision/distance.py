"""지면 거리 — 사람과 지게차가 실제로 얼마나 가까운가. FN-DET-08 · FN-DET-09

출처: API명세서 §6.5 (`nearby[].dist_m`) · 기능명세서 FN-DET-08 · FN-DET-09

**거리 수치는 항상 호모그래피 값을 쓴다**(CLAUDE.md 절대규칙 4). 단안 뎁스는 절대거리가
부정확하므로 앞뒤 분리 판별과 깊이 분산 확인에만 쓰고, 미터로 보고되는 값은 전부 지면
평면 위에서 잰다.

`method` 두 가지는 §2.2 가 정한 이름 그대로다.

| method | 계산 | 언제 |
|---|---|---|
| `bbox_center` | 두 bbox 아래변 중앙을 지면으로 투영해 거리 | 초기 구현 · 마스크 미디코드 |
| `mask_nearest` | 두 윤곽을 지면으로 투영해 **최단** 거리 | 정밀 · 포크가 뻗은 지게차 |

포크가 전방으로 뻗은 지게차는 중심 간 거리가 실제 접촉 위험을 과소평가한다 — 위험은
포크 끝단에서 발생하므로 윤곽 최단 거리가 안전 판정에 정확하다(FN-DET-09).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from aegis_vision.footpoint import bbox_foot_point
from aegis_vision.homography import Homography, PointM, PointPx

__all__ = [
    "distance_bbox_center_m",
    "distance_mask_nearest_m",
    "ground_distance_m",
    "nearest_pair_m",
    "project_to_ground",
    "within_radius",
]


def ground_distance_m(a_m: PointM, b_m: PointM) -> float:
    """지면 두 점 사이 거리(m). 좌표는 **둘 다 미터**여야 한다."""
    return math.hypot(float(a_m[0]) - float(b_m[0]), float(a_m[1]) - float(b_m[1]))


def project_to_ground(points: Sequence[PointPx], homography: Homography) -> list[PointM]:
    """정규화 픽셀 점들을 지면으로 투영한다.

    **윤곽 점만 넣는다.** 마스크 전체를 투영하면 서 있는 사람의 상반신이 지면 가정에
    걸려 먼 지점으로 날아가고, 그 점이 최단 거리로 뽑히면 실제보다 가깝거나 먼 값이
    나온다(기능명세서 FN-DET-10 · vision 규칙).
    """
    return [homography.to_ground(point) for point in points]


def distance_bbox_center_m(
    person_bbox: tuple[float, float, float, float],
    vehicle_bbox: tuple[float, float, float, float],
    homography: Homography,
) -> float:
    """`method: "bbox_center"` — 두 아래변 중앙의 지면 거리. API명세서 §2.2

    **아래변 중앙을 쓰는 이유**: bbox 의 기하 중심은 공중에 있어 지면 평면 위의 점이
    아니다. 그것을 호모그래피에 넣으면 사람 키만큼 뒤쪽으로 밀린 지점이 나온다.
    """
    person_m = homography.to_ground(bbox_foot_point(person_bbox))
    vehicle_m = homography.to_ground(bbox_foot_point(vehicle_bbox))
    return ground_distance_m(person_m, vehicle_m)


def distance_mask_nearest_m(
    person_contour: Sequence[PointPx],
    vehicle_contour: Sequence[PointPx],
    homography: Homography,
) -> float:
    """`method: "mask_nearest"` — 두 윤곽의 지면 최단 거리. FN-DET-09"""
    distance, _, _ = nearest_pair_m(
        project_to_ground(person_contour, homography),
        project_to_ground(vehicle_contour, homography),
    )
    return distance


def nearest_pair_m(
    a_points_m: Sequence[PointM],
    b_points_m: Sequence[PointM],
) -> tuple[float, PointM, PointM]:
    """가장 가까운 점 쌍과 그 거리. 오버레이 거리선의 양 끝점이 이 값이다(§5.1 `anchor`).

    윤곽 점 수가 각각 수십 개 수준이라 전수 비교로 충분하다 — 프레임당 수천 번의 곱셈은
    엣지 예산에서 무시할 수준이고, 근사 자료구조를 쓰면 그 오차가 곧 경고 임계값 오차가
    된다.
    """
    if not a_points_m or not b_points_m:
        msg = "거리를 잴 점이 없다 — 두 윤곽 모두 비어 있지 않아야 한다"
        raise ValueError(msg)
    best = (math.inf, a_points_m[0], b_points_m[0])
    for a in a_points_m:
        for b in b_points_m:
            distance = ground_distance_m(a, b)
            if distance < best[0]:
                best = (distance, a, b)
    return best


def within_radius(distance_m: float, radius_m: float) -> bool:
    """위험 반경 안인가. `nearby[].within_danger_radius`(§2.2)가 이 값이다.

    경계값을 **포함**한다. 정확히 3.0m 를 위험 밖으로 보면 임계값 자체가 안전 구간이
    되는데, 그것은 반경을 3.0m 로 정한 의도가 아니다.
    """
    return distance_m <= radius_m
