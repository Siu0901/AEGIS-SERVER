"""뎁스 온디맨드 검증 — 언제 부를지와 결과를 얼마나 믿을지. FN-DET-11 (API명세서 §6.6)

출처: 기능명세서 §4.1 FN-DET-11 · API명세서 §6.6 (`depth_verified`) · §2.2 (`nearby[]`)

★ **거리 수치는 절대 뎁스에서 가져오지 않는다**(CLAUDE.md 절대규칙 4 · §6.6).
단안 뎁스는 상대 깊이라 절대 거리가 부정확하다. 미터로 보고되는 값은 전부 호모그래피가
낸다. 뎁스가 답하는 것은 두 가지뿐이다.

| 쓰임 | 질문 |
|---|---|
| 앞뒤 분리 판별 | 화면에서 겹쳐 보이는 사람과 지게차가 **실제로도** 가까운가 |
| 깊이 분산 | 마스크 영역의 깊이가 지면을 따라 퍼져 있는가(누움) 아니면 뭉쳐 있는가(섬) |

**이 모듈은 모델을 부르지 않는다.** 트리거 판정과 캐시만 순수 로직으로 두고, 실제
추론은 `DepthProbe` 프로토콜 뒤에 있다 — 구현은 M9 의 `edge/depth.py`(Depth Anything
V2 Small)다. 그때까지 시뮬레이터와 테스트가 결정적인 대역을 주입한다.

---

**트리거 (하나라도 충족 시 1프레임 실행)** — 기능명세서 FN-DET-11

| | 조건 |
|---|---|
| A | 산출 거리가 회색지대(`depth_band_m`, 기본 2.0~3.5m) 안 |
| B | 두 객체의 화면상 영역이 겹침(IoU > 0) |
| C | 접지점 신뢰도가 임계 미만 |
| D | 쓰러짐 3조건 충족 (자세 검증용) |

**트리거가 없으면 실행하지 않고 `depth_verified = False` 다**(§6.6). 「검증하지
않았다」와 「검증했는데 아니었다」가 같은 값으로 나가는 것은 명세서가 정한 규약이며,
그래서 근접 후보 판정은 회색지대에서만 이 값을 요구한다(`distance.proximity_candidate`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from aegis_vision.homography import Bbox, PointM

__all__ = [
    "DepthCache",
    "DepthProbe",
    "DepthResult",
    "DepthTrigger",
    "DepthTriggers",
    "bbox_iou",
    "depth_triggers",
    "verify",
]


@dataclass(frozen=True, slots=True)
class DepthResult:
    """뎁스 1프레임의 결과. **거리는 여기서 나오지 않는다.**"""

    same_plane: bool
    """사람과 지게차의 깊이 분포가 유사한가. `nearby[].depth_verified` 가 이 값이다(§6.6).

    깊이가 뚜렷이 분리되면 원근 착시이므로 근접 위반을 기각한다.
    """
    depth_variance: float | None = None
    """사람 마스크 영역의 깊이 분산. 쓰러짐 검증용(트리거 D)이며 근접 검증에서는 `None`.

    서 있는 사람은 카메라로부터 거의 같은 거리에 있어 분산이 작고, 지면에 누운 사람은
    깊이가 지면을 따라 퍼져 분산이 크다(기능명세서 FN-DET-10 「뎁스 보강」).
    """


class DepthProbe(Protocol):
    """뎁스 모델 한 번 호출. **구현은 이 패키지 밖에 있다.**

    `packages/vision` 은 `torch`·`tensorrt` 를 import 하지 않는다(`.claude/rules/vision.md`).
    추론은 M9 의 `edge/depth.py` 가 하고, 여기서는 주입받은 것을 부를 뿐이다.
    """

    def measure(
        self,
        *,
        person_bbox: Bbox,
        vehicle_bbox: Bbox | None,
    ) -> DepthResult: ...


class DepthTrigger:
    """트리거 이름. 어느 조건으로 실행됐는지 로그와 진단에 남긴다."""

    GRAY_BAND = "gray_band"
    """A — 산출 거리가 회색지대 안."""
    OVERLAP = "overlap"
    """B — 화면상 영역이 겹침."""
    LOW_FOOT_CONF = "low_foot_conf"
    """C — 접지점 신뢰도가 임계 미만."""
    FALL_CANDIDATE = "fall_candidate"
    """D — 쓰러짐 3조건 충족."""


@dataclass(frozen=True, slots=True)
class DepthTriggers:
    """어느 트리거가 걸렸는가. 비어 있으면 **실행하지 않는다.**"""

    reasons: tuple[str, ...]

    def __bool__(self) -> bool:
        return bool(self.reasons)


def bbox_iou(a: Bbox, b: Bbox) -> float:
    """두 bbox 의 IoU. 트리거 B 는 **0 초과**면 걸린다(기능명세서 FN-DET-11).

    임계값을 두지 않는 이유: 겹치기 시작하는 순간이 곧 원근 착시가 가능해지는 순간이다.
    화면에서 1픽셀이라도 겹치면 앞뒤 관계를 화면만으로는 알 수 없다.
    """
    ax1, ay1, ax2, ay2 = (float(value) for value in a)
    bx1, by1, bx2, by2 = (float(value) for value in b)
    left = max(ax1, bx1)
    top = max(ay1, by1)
    right = min(ax2, bx2)
    bottom = min(ay2, by2)
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - overlap
    return 0.0 if union <= 0.0 else overlap / union


def depth_triggers(
    *,
    dist_m: float | None,
    person_bbox: Bbox | None = None,
    vehicle_bbox: Bbox | None = None,
    foot_conf: float | None = None,
    min_foot_conf: float,
    band_m: tuple[float, float],
    fall_candidate: bool = False,
) -> DepthTriggers:
    """네 조건 중 걸린 것들. 기능명세서 FN-DET-11

    **전부 검사하고 이유를 모아서 돌려준다.** 첫 조건에서 끊으면 왜 실행됐는지 하나만
    남아, 회색지대 때문인지 겹침 때문인지를 로그로 구분할 수 없다.
    """
    low, high = band_m
    if low > high:
        msg = f"회색지대 범위가 뒤집혔다: {band_m!r}"
        raise ValueError(msg)

    reasons: list[str] = []
    if dist_m is not None and low <= dist_m <= high:
        reasons.append(DepthTrigger.GRAY_BAND)
    overlapping = (
        person_bbox is not None
        and vehicle_bbox is not None
        and bbox_iou(person_bbox, vehicle_bbox) > 0.0
    )
    if overlapping:
        reasons.append(DepthTrigger.OVERLAP)
    if foot_conf is not None and foot_conf < min_foot_conf:
        reasons.append(DepthTrigger.LOW_FOOT_CONF)
    if fall_candidate:
        reasons.append(DepthTrigger.FALL_CANDIDATE)
    return DepthTriggers(reasons=tuple(reasons))


class DepthCache:
    """객체 쌍별 뎁스 결과 재사용. API명세서 §6.6 「캐싱」

    캐시 키는 `(cam_id, 사람 track_id, 지게차 track_id)` 다. 이 조합을 만들기 위해
    **지게차에도 track_id 를 부여**한다(§6.6).

    무효화 규칙 둘:

    | 규칙 | 근거 |
    |---|---|
    | `depth_cache_ms`(기본 500ms) 경과 | 오래된 앞뒤 관계로 지금을 설명하지 않는다 |
    | 어느 한쪽이 지면 좌표로 임계 이상 이동 | §6.6 — 움직였으면 그 판정은 다른 장면의 것이다 |

    시간은 부르는 쪽이 `Clock` 에서 얻어 넘긴다(CLAUDE.md 절대규칙 1).
    """

    def __init__(self, *, ttl_s: float, move_invalidate_m: float) -> None:
        if ttl_s <= 0.0 or move_invalidate_m <= 0.0:
            msg = f"캐시 인자는 0보다 커야 한다: ttl={ttl_s!r} move={move_invalidate_m!r}"
            raise ValueError(msg)
        self._ttl_s = ttl_s
        self._move_m = move_invalidate_m
        self._entries: dict[tuple[int, int, int], tuple[float, PointM, PointM, DepthResult]] = {}

    @property
    def size(self) -> int:
        return len(self._entries)

    def get(
        self,
        key: tuple[int, int, int],
        *,
        at_s: float,
        person_m: PointM,
        vehicle_m: PointM,
    ) -> DepthResult | None:
        """살아 있는 결과. 만료했거나 둘 중 하나가 움직였으면 `None`(그리고 버린다)."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, stored_person, stored_vehicle, result = entry
        moved = max(
            _distance(person_m, stored_person),
            _distance(vehicle_m, stored_vehicle),
        )
        if at_s - stored_at > self._ttl_s or moved >= self._move_m:
            del self._entries[key]
            return None
        return result

    def put(
        self,
        key: tuple[int, int, int],
        result: DepthResult,
        *,
        at_s: float,
        person_m: PointM,
        vehicle_m: PointM,
    ) -> None:
        self._entries[key] = (at_s, person_m, vehicle_m, result)

    def forget(self, cam_id: int, track_id: int) -> None:
        """트랙이 끊겼다 — 그 트랙이 낀 모든 쌍을 버린다.

        놔두면 새 트랙이 같은 번호를 받았을 때 **남의 판정**을 물려받는다.
        """
        for key in [
            item for item in self._entries if item[0] == cam_id and track_id in (item[1], item[2])
        ]:
            del self._entries[key]


def _distance(a: PointM, b: PointM) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def verify(
    probe: DepthProbe,
    cache: DepthCache,
    *,
    key: tuple[int, int, int],
    at_s: float,
    person_bbox: Bbox,
    vehicle_bbox: Bbox | None,
    person_m: PointM,
    vehicle_m: PointM,
    triggers: DepthTriggers,
) -> DepthResult:
    """트리거가 걸렸을 때만 1프레임 실행하고, 결과를 캐시에 넣는다.

    **트리거가 없으면 모델을 부르지 않고 `same_plane=False` 를 돌려준다**(§6.6
    「트리거 미충족으로 미실행한 경우도 `false`」). 조용히 `True` 로 답하면 검증하지
    않은 근접이 검증된 것으로 기록된다.
    """
    if not triggers:
        return DepthResult(same_plane=False)
    cached = cache.get(key, at_s=at_s, person_m=person_m, vehicle_m=vehicle_m)
    if cached is not None:
        return cached
    result = probe.measure(person_bbox=person_bbox, vehicle_bbox=vehicle_bbox)
    cache.put(key, result, at_s=at_s, person_m=person_m, vehicle_m=vehicle_m)
    return result
