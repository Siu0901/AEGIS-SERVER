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

---

**FN-DET-08 은 두 반경으로 돈다**(API명세서 §4.5 · 기능명세서 §4.1).

| 반경 | 값 | 뜻 |
|---|---|---|
| `screening_radius_m` | 5.0 | `nearby[]` 에 실을지 — 관측 범위 |
| `danger_radius_m` | 3.0 | 장비를 따라다니는 **동적 위험 영역** |
| `proximity_threshold_m` | 2.0 | **즉시 경고 기준** — 후보를 올린다 |

셋을 하나로 합치지 않는 이유는 각각 다른 것을 정하기 때문이다. 5m 안의 지게차는
LLM 분석 맥락("이동 중인 지게차 3.2m 이내")으로 쓰이고, 3m 안은 화면에 위험으로
표시되며, 2m 안이라야 후보가 된다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from aegis_vision.footpoint import bbox_foot_point
from aegis_vision.homography import Homography, PointM, PointPx

__all__ = [
    "NearbyReading",
    "ProximityRadii",
    "distance_bbox_center_m",
    "distance_mask_nearest_m",
    "ground_distance_m",
    "nearest_pair_m",
    "project_to_ground",
    "proximity_candidate",
    "screen_nearby",
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


# --------------------------------------------------------------------------
# FN-DET-08 · 지게차 근접 판정
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProximityRadii:
    """FN-DET-08 이 쓰는 세 반경. 전부 정책값이며 **기본값을 두지 않는다.**

    기본값을 주면 정책 조회에 실패한 경로가 조용히 코드 상수로 판정하게 되고, 그때
    화면의 「위험 반경 3.0m」과 실제 판정 기준이 갈린다(CLAUDE.md 절대규칙 6).
    """

    screening_m: float
    """`nearby[]` 에 실을 최대 거리(`screening_radius_m`)."""
    danger_m: float
    """장비를 따라다니는 동적 위험 영역(`vehicle_classes.danger_radius_m`)."""
    warn_m: float
    """즉시 경고 기준(`proximity_threshold_m`). 이 안이라야 후보가 된다."""

    def __post_init__(self) -> None:
        if not 0.0 < self.warn_m <= self.danger_m <= self.screening_m:
            msg = (
                "반경은 경고 ≤ 위험 ≤ 스크리닝 순서여야 한다: "
                f"warn={self.warn_m!r} danger={self.danger_m!r} screening={self.screening_m!r}"
            )
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class NearbyReading:
    """사람 하나와 지게차 하나의 관계. `candidate.nearby[]` 한 원소가 된다(§2.2)."""

    track_id: int
    dist_m: float
    method: str
    """`bbox_center` 또는 `mask_nearest`(§6.5). 어느 방식으로 잰 값인지 함께 남긴다."""
    moving: bool
    within_danger_radius: bool
    depth_verified: bool = False
    """뎁스 검증 통과 여부. **트리거 미충족으로 미실행한 경우도 `False`**(§6.6)."""


def screen_nearby(
    readings: Sequence[NearbyReading],
    radii: ProximityRadii,
) -> list[NearbyReading]:
    """`nearby[]` 에 실을 것만 고른다 — 스크리닝 반경(기본 5m) 안(§2.2).

    가까운 순으로 정렬한다. 목록 순서가 감지 순서면 아무 의미 없는 것이 화면의 거리선
    순서와 LLM 이 읽는 맥락의 첫 줄을 정한다.
    """
    inside = [reading for reading in readings if reading.dist_m <= radii.screening_m]
    return sorted(inside, key=lambda reading: reading.dist_m)


def proximity_candidate(
    readings: Sequence[NearbyReading],
    radii: ProximityRadii,
) -> NearbyReading | None:
    """근접 후보를 낼 지게차 하나. 없으면 `None`. FN-DET-08

    **판정하지 않고 후보만 고른다.** 확정·경고는 서버 몫이다(CLAUDE.md 절대규칙 3).

    | 규칙 | 근거 |
    |---|---|
    | `dist_m ≤ warn_m` 이라야 후보 | §4.5 「근접 임계값은 즉시 경고 기준」 |
    | `depth_verified` 는 **회색지대에서만** 요구한다 | §6.6 |
    | 여럿이면 **이동 중인 쪽을 먼저**, 같으면 가까운 쪽 | FN-DET-08 ④ |

    `depth_verified` 를 늘 요구하지 않는 이유: 트리거 미충족이면 그 값이 항상 `False`
    이므로(§6.6), 무조건 요구하면 회색지대 밖의 근접이 영영 잡히지 않는다.

    이동 중인 쪽을 먼저 보는 이유: 3m 에서 달려오는 지게차가 2m 에 멈춰 선 지게차보다
    위험하다(FN-DET-08 ④ 「이동 중이면 위험도를 상향 조정」).

    ★ **`moving` 은 문턱을 넓히지 않는다.** 이동 중이라고 경고 거리를 늘리면 정지한
    지게차 옆을 지나가는 사람과 같은 거리에서 서로 다른 판정이 나오고, 그 차이는
    이벤트 기록에 남지 않아 나중에 설명할 수 없다. 위험도(어느 것을 근거로 삼을지)만
    바꾸고 임계값은 그대로 둔다.
    """
    warned = [reading for reading in readings if reading.dist_m <= radii.warn_m]
    if not warned:
        return None
    return min(warned, key=lambda reading: (not reading.moving, reading.dist_m))
