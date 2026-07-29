"""FN-EVT-07 ② 재결합 — 끊긴 트랙과 새로 나타난 트랙을 잇는 **순수 판단**.

기능명세서 §4.2 · API명세서 §2.3

**I/O 가 없다**(CLAUDE.md 절대규칙 2). 여기서 나오는 것은 "어느 `lost` 이벤트에
이 트랙을 이어 붙일 것인가"라는 판단 하나이며, 이벤트를 실제로 되살리는 것은
`event_machine.EventMachine` 이고 저장은 저장소가 한다.

**재결합은 이벤트를 살려두는 처리이지 시정을 인정하는 처리가 아니다.**
결합에 성공해도 위반이 사라져 보이면 해소 타이머를 0부터 다시 채운다 —
그 규칙은 상태머신 쪽에 있다(FN-EVT-03 · 추적 ID 스위치 방어).

**반경은 고정값이 아니라 경과 시간에 비례한다.** 고정 반경은 작게 잡으면 정상적인
재결합이 실패하고, 크게 잡으면 인접한 다른 작업자를 잘못 흡수한다. 시간 비례 방식은
"1초 만에 다시 나타났다면 1.5m 이내에 있어야 한다"는 물리적 제약을 그대로 옮긴 것이다.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

__all__ = ["LostTrack", "ReassocMatch", "match_lost_track", "reassoc_radius_m"]


@dataclass(frozen=True, slots=True)
class LostTrack:
    """재결합 후보가 되는 `lost` 이벤트 하나. 카메라 안에서만 의미가 있다."""

    event_id: str
    track_id: int
    """소실 당시의 트랙 번호. 결합에 성공하면 `prev_track_ids` 로 내려간다."""
    lost_at: datetime
    """마지막으로 관측된 시각. 시간 창 `Δt` 의 기준이다(§2.3 `last_ts`)."""
    last_foot_point_m: tuple[float, float]
    """마지막 지면 실좌표. **재결합 반경 판정의 기준점**이다."""


@dataclass(frozen=True, slots=True)
class ReassocMatch:
    """결합 결과. 진단(로그·`reassoc_count` 근거)을 위해 판정에 쓴 수치를 함께 든다."""

    event_id: str
    elapsed_s: float
    distance_m: float
    radius_m: float


def reassoc_radius_m(elapsed_s: float, *, max_speed_ms: float, cap_m: float) -> float:
    """`min(reassoc_max_speed_ms × Δt, reassoc_radius_cap_m)`. 기능명세서 §4.2

    상한을 두는 이유는 시간 창(`reassoc_window_s`)이 길어질수록 반경이 무한히 넓어져
    카메라 반대편의 다른 작업자까지 후보가 되기 때문이다.
    """
    return min(max(elapsed_s, 0.0) * max_speed_ms, cap_m)


def match_lost_track(
    *,
    appeared_at: datetime,
    foot_point_m: tuple[float, float],
    lost: Iterable[LostTrack],
    window_s: float,
    max_speed_ms: float,
    cap_m: float,
) -> ReassocMatch | None:
    """새로 나타난 트랙 하나를 `lost` 이벤트에 잇는다. 없으면 `None`.

    Args:
        appeared_at: 새 트랙이 관측된 시각.
        foot_point_m: 새 트랙의 지면 실좌표(m).
        lost: **같은 카메라**의 `lost` 이벤트들. `track_id` 는 카메라 안에서만
            유효하므로 호출자가 카메라 단위로 걸러서 넘긴다.
        window_s: `reassoc_window_s`.
        max_speed_ms: `reassoc_max_speed_ms`.
        cap_m: `reassoc_radius_cap_m`.

    **후보가 복수이면 지면 거리가 최소인 하나만 1:1로 결합한다.** 두 사람이 동시에
    가려졌다가 나오는 상황에서 하나의 새 트랙을 둘 다에 붙이면 이벤트가 복제된다.
    """
    best: ReassocMatch | None = None
    for track in lost:
        elapsed_s = (appeared_at - track.lost_at).total_seconds()
        if elapsed_s < 0.0 or elapsed_s > window_s:
            continue
        radius_m = reassoc_radius_m(elapsed_s, max_speed_ms=max_speed_ms, cap_m=cap_m)
        distance_m = math.dist(foot_point_m, track.last_foot_point_m)
        if distance_m > radius_m:
            continue
        if best is None or distance_m < best.distance_m:
            best = ReassocMatch(
                event_id=track.event_id,
                elapsed_s=elapsed_s,
                distance_m=distance_m,
                radius_m=radius_m,
            )
    return best
