"""차량 탑승자 판별 — FN-DET-13 (기능명세서 §4.1)

지게차나 트럭에 **탑승 중인 사람**을 식별해 일부 위반 판정에서 제외한다.
판별하지 않으면 세 가지가 동시에 오작동한다(명세 §4.1 FN-DET-13).

| 판정 | 판별하지 않을 때 |
|---|---|
| `proximity` | 운전자와 차량의 거리가 사실상 0이라 **차량이 움직이는 내내 근접이 확정**된다 |
| `zone_intrusion` | 차량 통행은 정상 운용인데 운전자가 구역 안이라 침입으로 잡힌다 |
| `fall` | 앉은 자세는 `height_ratio` 가 낮고 정차하면 `stillness` 도 차서 쓰러짐 오탐이 된다 |

★ **첫 번째가 가장 위험하다.** 경고 방송이 상시 울리면 현장이 방송을 무시하게 되고,
그 시점에 「방송 후 시정률」은 의미를 잃는다 — 이 프로젝트의 유일한 차별점이다.

---

**판별 조건 — 셋을 모두 충족해야 한다.**

| | 조건 |
|---|---|
| ① | 사람 마스크와 차량 마스크의 겹침 비율이 `occupancy_overlap_min` 이상 |
| ② | 사람의 **접지점이 차량 마스크 내부**에 있다 |
| ③ | 위 상태가 `occupancy_confirm_s` 이상 유지 |

★ **②가 판별의 핵심이다.** 차량 뒤에 서 있는 사람도 화면상 마스크는 겹치지만(가림),
발이 지면에 닿아 있으므로 접지점이 차량 영역 **밖**에 찍힌다. 탑승자는 발이 지면에
없으므로 접지점이 차량 영역 안으로 들어온다. **겹침만으로 판단하면 뒤에 선 사람을
탑승자로 오인한다** — 그 오인은 실제 위험을 통째로 놓치는 방향이라 더 나쁘다.

**해제는 `occupancy_release_s` 다.** 확정보다 길게 잡는다(기본 1.5초 대 3초) —
히스테리시스가 없으면 운전자가 몸을 기울일 때마다 탑승·하차가 반복되고, 그때마다
근접 위반이 생겼다 사라진다.

**이 모듈은 시간을 읽지 않는다**(CLAUDE.md 절대규칙 1). 부르는 쪽이 `Clock` 에서 얻은
`at_s` 를 넘긴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .homography import PointPx

__all__ = ["OccupancyTracker", "mask_overlap_ratio", "point_in_mask"]


def _polygon_area(points: tuple[PointPx, ...]) -> float:
    """신발끈 공식. 방향과 무관하게 넓이를 돌려준다."""
    total = 0.0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def point_in_mask(point: PointPx, mask: tuple[PointPx, ...]) -> bool:
    """윤곽 안에 점이 있는가. 광선 교차법 — `zones.point_in_polygon` 과 같은 방식이다.

    화면 좌표(정규화 픽셀)에서 판단한다. **지면 좌표로 바꾸지 않는다** — 탑승자는
    발이 지면에 없어서 호모그래피가 내는 값이 실제 위치가 아니기 때문이다. 이
    판별이 묻는 것은 「화면에서 차량 몸통 안에 있는가」다.
    """
    if len(mask) < 3:
        return False
    x, y = point
    inside = False
    for index in range(len(mask)):
        x1, y1 = mask[index]
        x2, y2 = mask[(index - 1) % len(mask)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def mask_overlap_ratio(person: tuple[PointPx, ...], vehicle: tuple[PointPx, ...]) -> float:
    """사람 마스크 중 차량 마스크와 겹치는 비율(0~1).

    **분모는 사람 넓이다.** 차량이 훨씬 크므로 합집합이나 차량 넓이로 나누면 탑승
    중이어도 비율이 0에 가깝게 나온다. 묻는 것은 「사람이 차량 위에 얹혀 있는가」다.

    윤곽 다각형끼리의 정확한 교집합 대신 **사람 윤곽 점의 포함 비율**로 근사한다.
    엣지가 24~48점으로 균등 솎은 윤곽을 주므로 이 근사의 오차는 점 간격 수준이고,
    임계(`occupancy_overlap_min`, 기본 0.35)가 그보다 훨씬 거칠다. 다각형 클리핑을
    넣으면 매 프레임·매 쌍마다 도는 비용이 커진다.
    """
    if len(person) < 3 or len(vehicle) < 3 or _polygon_area(person) <= 0.0:
        return 0.0
    hits = sum(1 for point in person if point_in_mask(point, vehicle))
    return hits / len(person)


@dataclass(slots=True)
class _Pending:
    """조건이 바뀐 순간과 방향. 히스테리시스를 재기 위한 것이다."""

    riding: bool
    since_s: float


@dataclass(slots=True)
class OccupancyTracker:
    """카메라 한 대의 탑승 상태. 사람 트랙마다 「어느 차량에 타고 있는가」를 들고 있다.

    `update()` 는 매 프레임 한 번 부른다. 조건을 만족하는 차량이 여럿이면 **겹침이
    가장 큰 것**을 고른다 — 사람이 두 차량에 동시에 탈 수는 없다.
    """

    confirm_s: float
    release_s: float
    overlap_min: float

    _riding: dict[int, int] = field(default_factory=dict)
    """확정된 탑승. `{사람 track_id: 차량 track_id}`"""
    _pending: dict[int, _Pending] = field(default_factory=dict)
    """아직 지속 시간을 못 채운 전이."""

    #: 탑승 판별로 억제한 후보 수. 명세 §4.1 「집계」 — 억제 비율이 과도하면 임계가
    #: 잘못된 것이므로 진단 근거가 된다.
    suppressed: int = 0

    def update(
        self,
        *,
        person_track_id: int,
        person_mask: tuple[PointPx, ...],
        person_foot: PointPx,
        vehicles: dict[int, tuple[PointPx, ...]],
        at_s: float,
    ) -> int | None:
        """이 프레임의 판정. 탑승 중이면 차량 `track_id`, 아니면 `None`.

        조건 ①②를 이 프레임에서 재고, ③(지속)은 `_pending` 으로 누적한다.
        """
        best: tuple[float, int] | None = None
        for vehicle_id, vehicle_mask in vehicles.items():
            # ★ ②를 먼저 본다. 접지점이 차량 밖이면 겹침이 아무리 커도 탑승이 아니다
            #   (뒤에 서 있는 사람). 겹침 계산이 더 비싸므로 순서도 이쪽이 낫다.
            if not point_in_mask(person_foot, vehicle_mask):
                continue
            ratio = mask_overlap_ratio(person_mask, vehicle_mask)
            if ratio < self.overlap_min:
                continue
            if best is None or ratio > best[0]:
                best = (ratio, vehicle_id)

        observed = best[1] if best else None
        current = self._riding.get(person_track_id)

        if observed == current:
            # 상태가 유지됐다. 반대 방향으로 쌓이던 것이 있으면 지운다.
            self._pending.pop(person_track_id, None)
            return current

        pending = self._pending.get(person_track_id)
        wants_riding = observed is not None
        if pending is None or pending.riding != wants_riding:
            self._pending[person_track_id] = _Pending(riding=wants_riding, since_s=at_s)
            return current

        needed = self.confirm_s if wants_riding else self.release_s
        if at_s - pending.since_s < needed:
            return current

        self._pending.pop(person_track_id, None)
        if observed is None:
            self._riding.pop(person_track_id, None)
        else:
            self._riding[person_track_id] = observed
        return observed

    def riding_on(self, person_track_id: int) -> int | None:
        """확정된 탑승 차량. 판별이 끝나지 않았으면 `None`."""
        return self._riding.get(person_track_id)

    def forget(self, person_track_id: int) -> None:
        """트랙이 끊겼다. 놔두면 새 트랙이 같은 번호를 받았을 때 남의 상태를 물려받는다."""
        self._riding.pop(person_track_id, None)
        self._pending.pop(person_track_id, None)

    def count_suppressed(self, amount: int = 1) -> None:
        self.suppressed += amount
