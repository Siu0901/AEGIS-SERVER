"""금지구역 판정 — 접지점이 폴리곤 안에 있는가. FN-DET-07

출처: 기능명세서 FN-DET-07 · API명세서 §4.5 (`zones.polygon_m` · `buffer_m`)

**폴리곤은 지면 실좌표(m)다.** 화면에서 그린 픽셀 폴리곤은 설정 화면이 호모그래피로
변환해 저장하므로(FN-CFG-02), 여기 들어오는 좌표는 이미 미터다. 픽셀 폴리곤과 미터
접지점을 섞어 넣으면 판정이 조용히 뒤집힌다.

**히스테리시스로 경계선 떨림을 막는다.** 경계에 서 있는 사람의 접지점은 프레임마다
수 cm 씩 흔들리고, 단일 임계값이면 그 흔들림이 그대로 진입·이탈 반복이 된다. 그러면
`zone_intrusion` 후보가 켜졌다 꺼졌다 하면서 확정 타이머가 영원히 차지 않는다.

`buffer_m` 하나로 두 선을 만든다.

```
        │←buffer→│←buffer→│
  구역 안 │        │        │ 구역 밖
   ───────┼────────┼────────┼───────
        경계     진입선    이탈선
```

* **진입선 = 경계에서 바깥으로 `buffer_m`** — 호모그래피 오차를 흡수하고 사전 경고를
  가능하게 한다(§4.5 가 `buffer_m` 을 그렇게 정의한다).
* **이탈선 = 진입선에서 다시 바깥으로 `buffer_m`** — 두 선 사이가 히스테리시스 폭이다.

새 상수를 만들지 않고 같은 값을 두 번 쓴다. `buffer_m = 0` 이면 두 선이 경계로 겹쳐
히스테리시스가 사라지는데, 그것이 "여유 없음"의 자연스러운 뜻이다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from aegis_vision.homography import PointM

__all__ = ["ZoneShape", "point_in_polygon", "signed_distance_m", "zone_for_point", "zone_state"]


@dataclass(frozen=True, slots=True)
class ZoneShape:
    """판정에 필요한 구역 정보만. 계약 모델(`aegis_contracts.Zone`)의 부분집합이다.

    이 패키지는 의존성이 없어야 하므로 계약을 import 하지 않는다(하드웨어·프레임워크
    의존 0). 부르는 쪽이 `Zone` 에서 이 세 값을 옮겨 담는다.
    """

    zone_id: str
    polygon_m: tuple[PointM, ...]
    buffer_m: float = 0.0

    def __post_init__(self) -> None:
        if len(self.polygon_m) < 3:
            msg = f"폴리곤 꼭짓점이 {len(self.polygon_m)}개다 — 구역은 3개 이상이어야 한다"
            raise ValueError(msg)
        if self.buffer_m < 0.0:
            msg = f"buffer_m 은 음수일 수 없다: {self.buffer_m!r}"
            raise ValueError(msg)


def point_in_polygon(point_m: PointM, polygon_m: Sequence[PointM]) -> bool:
    """점-다각형 내부 판정(ray casting). 경계 위의 점은 **안**으로 본다.

    경계를 밖으로 보면 폴리곤 변에 정확히 걸친 접지점이 프레임마다 안팎을 오간다.
    안전 판정에서는 경계를 포함하는 쪽이 보수적이기도 하다.
    """
    if len(polygon_m) < 3:
        msg = f"폴리곤 꼭짓점이 {len(polygon_m)}개다 — 3개 이상이어야 한다"
        raise ValueError(msg)
    x, y = float(point_m[0]), float(point_m[1])
    inside = False
    count = len(polygon_m)
    for index in range(count):
        ax, ay = (float(value) for value in polygon_m[index])
        bx, by = (float(value) for value in polygon_m[(index + 1) % count])
        if _on_segment((x, y), (ax, ay), (bx, by)):
            return True
        if (ay > y) != (by > y):
            crossing = ax + (y - ay) / (by - ay) * (bx - ax)
            if crossing > x:
                inside = not inside
    return inside


def signed_distance_m(point_m: PointM, polygon_m: Sequence[PointM]) -> float:
    """경계까지의 거리(m). **안이면 양수, 밖이면 음수.**

    진입·이탈 임계를 거리로 표현하기 위한 값이다. `buffer_m` 이 미터 단위이므로
    "안/밖" 이진값만으로는 버퍼를 적용할 수 없다.
    """
    distance = min(
        _distance_to_segment(point_m, polygon_m[index], polygon_m[(index + 1) % len(polygon_m)])
        for index in range(len(polygon_m))
    )
    return distance if point_in_polygon(point_m, polygon_m) else -distance


def zone_state(point_m: PointM, zone: ZoneShape, *, was_inside: bool) -> bool:
    """이 접지점이 지금 구역 안인가. 히스테리시스 포함. FN-DET-07

    `was_inside` 는 **직전 프레임의 판정 결과**다. 상태를 여기서 들고 있지 않는 이유는
    이 패키지에 I/O 도 가변 상태도 두지 않기 때문이다(순수 함수) — 트랙별 직전 값은
    부르는 쪽(엣지 러너)이 관리한다.
    """
    distance = signed_distance_m(point_m, zone.polygon_m)
    enter_line = -zone.buffer_m
    exit_line = -2.0 * zone.buffer_m
    if was_inside:
        return distance > exit_line
    return distance >= enter_line


def zone_for_point(
    point_m: PointM,
    zones: Sequence[ZoneShape],
    *,
    previous_zone_id: str | None = None,
) -> str | None:
    """`frame.in_zone` / `candidate.zone_id` 로 나갈 구역 하나. 없으면 `None`.

    여러 구역이 겹치면 **경계가 가장 가까운(= 더 좁은) 구역**을 고른다. 넓은 구역
    안에 좁은 구역이 들어 있는 배치에서 넓은 쪽을 고르면 더 구체적인 정보가 사라진다 —
    「공장 전체」보다 「지게차 통행로」가 현장에서 쓸모 있는 답이다. 같은 깊이면
    `zone_id` 순으로 자른다. **목록 순서로 정하지 않는다** — 그 순서는 DB 조회 순서라
    아무 의미가 없는데 판정을 바꾸게 된다.

    `previous_zone_id` 는 히스테리시스의 입력이다 — 직전에 그 구역 안이었다면 이탈선을
    넘을 때까지 그대로 남는다.
    """
    inside = [
        (signed_distance_m(point_m, zone.polygon_m), zone.zone_id)
        for zone in zones
        if zone_state(point_m, zone, was_inside=previous_zone_id == zone.zone_id)
    ]
    return min(inside)[1] if inside else None


def _distance_to_segment(point: PointM, start: PointM, end: PointM) -> float:
    px, py = float(point[0]), float(point[1])
    ax, ay = float(start[0]), float(start[1])
    bx, by = float(end[0]), float(end[1])
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _on_segment(point: PointM, start: PointM, end: PointM, *, tolerance: float = 1e-12) -> bool:
    return _distance_to_segment(point, start, end) <= tolerance
