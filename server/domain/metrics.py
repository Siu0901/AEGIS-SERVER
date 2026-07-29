"""FN-SYS-04 · FN-SYS-05 — 「방송 후 시정률」과 「판정 불가율」 산출.

기능명세서 §4.8 · API명세서 §4.2 · §6.7

```
correction_rate    = resolved / (resolved + unresolved)
undetermined_rate  = expired  / (resolved + unresolved + expired)
```

**이 모듈이 이 프로젝트의 유일한 차별점이다.** 상용 제품은 "감지 → 알림"에서 끝나
이 숫자가 존재할 수 없다. 그래서 여기서는 값을 크게 만드는 방향이 아니라 **방어할 수
있는 방향**을 택한다.

| 종결 상태 | 분자 | 분모 | 근거 |
|---|---|---|---|
| `resolved` (`resolve_window_s` 내) | ○ | ○ | 시정 성공 |
| `resolved` (창 초과) | ✕ | ○ | 늦은 시정 |
| `alerted` · `re_alerted` 미해소 | ✕ | ○ | 미시정 |
| `expired` (재결합 실패) | ✕ | **✕** | **판정 불가** — 따로 집계 |
| `is_false_positive` | ✕ | ✕ | 전량 제외 |
| `fall` | ✕ | ✕ | 자력 시정 불가, 따로 카운트 |

**`expired` 를 분모에서도 빼는 이유**: 추적이 끊긴 이벤트는 시정하지 않은 것이 아니라
시정 여부를 **관측하지 못한** 것이다. 미시정으로 계산하면 시스템 성능이 부당하게 낮아지고,
시정으로 계산하면 지표가 부풀려져 근거를 댈 수 없다. 모집단에서 빼되 그 비율을 함께
공개하는 것이 통계적으로 정확하며 외부 검증이 가능한 형태가 된다.

**경고 전 이벤트(`candidate` · `active`)와 유예 중(`lost`)은 모집단이 아니다.**
지표 이름이 「**방송 후** 시정률」이므로 방송이 나가지 않은 건은 분모에 들어갈 수 없고,
`lost` 는 아직 `resolved` 도 `expired` 도 아닌 진행 중 상태다.

**I/O 가 없다**(CLAUDE.md 절대규칙 2). 행을 읽어오는 것은 저장소의 일이다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from aegis_contracts import MetricsSummary
from aegis_contracts.enums import EventStatus, ViolationType

__all__ = ["DENOMINATOR_STATUSES", "MetricsRow", "summarize"]

#: 시정률 **분모**에 들어가는 상태. §6.7
#:
#: `lost` 가 없는 것은 의도다 — 유예 중인 이벤트는 아직 결론이 나지 않았고,
#: 결론이 나면 `resolved` 또는 `expired` 로 여기 다시 들어온다.
DENOMINATOR_STATUSES: frozenset[EventStatus] = frozenset(
    {EventStatus.ALERTED, EventStatus.RE_ALERTED, EventStatus.RESOLVED}
)


@dataclass(frozen=True, slots=True)
class MetricsRow:
    """집계에 필요한 이벤트 한 건의 최소 정보.

    `EventSummary` 를 그대로 받지 않는 이유는 저장소가 지표를 위해 이벤트 전량을
    모델로 만들 필요가 없기 때문이다 — 네 칸이면 §6.7 표를 전부 판정할 수 있다.
    """

    violation_type: ViolationType
    status: EventStatus
    resolution_sec: int | None
    """`alerted_at` → `resolved_at` 소요 초. 해소되지 않았으면 `None`."""
    is_false_positive: bool


def summarize(
    rows: Iterable[MetricsRow],
    *,
    period: str,
    resolve_window_s: float,
    anomaly_flags: int = 0,
) -> MetricsSummary:
    """§4.2 `GET /metrics/summary` 본문을 만든다.

    Args:
        rows: 집계 기간 안의 이벤트들.
        period: 응답에 그대로 실리는 기간 이름(`today` 등).
        resolve_window_s: 이 시간 안에 해소된 건만 **분자**에 넣는다(§6.7).
        anomaly_flags: 이상 탐지 플래그 수(FN-AI-04 · M8). 아직 세지 않으면 0.

    `resolved` 필드는 **분자**(창 안에 해소된 건수)이고 `unresolved` 는 **분모 − 분자**다.
    그래야 응답만 보고도 `correction_rate = resolved / (resolved + unresolved)` 라는
    §4.2 의 식이 그대로 성립한다. 늦은 시정(창 초과 해소)은 §6.7 표대로 분자에서
    빠지므로 `unresolved` 쪽에 남는다.
    """
    numerator = 0
    denominator = 0
    undetermined = 0
    fall_events = 0
    durations: list[int] = []

    for row in rows:
        if row.is_false_positive:
            # 오탐으로 정정된 건은 전량 제외한다(FN-EVT-05). 분모에 남기면
            # 시스템이 틀렸다는 사실이 "시정하지 않았다"로 둔갑한다.
            continue
        if row.violation_type is ViolationType.FALL:
            # 쓰러진 사람은 방송을 듣고 스스로 시정할 수 없다. 따로 센다.
            fall_events += 1
            continue

        if row.status is EventStatus.EXPIRED:
            undetermined += 1
            continue
        if row.status not in DENOMINATOR_STATUSES:
            continue

        denominator += 1
        # `resolution_sec` 이 비어 있는 `resolved` 는 레코드가 깨진 것이다. 분자에
        # 넣지 않는다 — 창 안에 시정됐다고 주장할 근거가 없다.
        if row.status is EventStatus.RESOLVED and row.resolution_sec is not None:
            durations.append(row.resolution_sec)
            if row.resolution_sec <= resolve_window_s:
                numerator += 1

    unresolved = denominator - numerator
    total = denominator + undetermined
    return MetricsSummary(
        period=period,
        correction_rate=_ratio(numerator, denominator),
        undetermined_rate=_ratio(undetermined, total),
        total_violations=total,
        resolved=numerator,
        unresolved=unresolved,
        undetermined=undetermined,
        avg_resolution_sec=round(sum(durations) / len(durations)) if durations else 0,
        fall_events=fall_events,
        anomaly_flags=anomaly_flags,
    )


def _ratio(numerator: int, denominator: int) -> float:
    """모집단이 비면 **0.0** 이다.

    표본이 없다는 사실은 `total_violations` · `undetermined` 가 0인 것으로 드러난다.
    비율만 보고 판단하지 않도록 화면은 시정률과 판정 불가율을 항상 병기한다(§6.7).
    """
    return numerator / denominator if denominator else 0.0
