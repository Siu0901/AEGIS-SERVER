"""FN-SYS-04 · FN-SYS-05 — 시정률과 판정 불가율 (기능명세서 §4.8 · API명세서 §6.7).

이 파일이 지키는 것은 숫자 하나다. **`expired` 는 미시정이 아니다.** 분모에 넣으면
시스템 성능이 부당하게 낮아지고, 분자에 넣으면 지표가 부풀려져 방어할 수 없다.
"""

from __future__ import annotations

import pytest

from aegis_contracts.enums import EventStatus, ViolationType
from server.domain.metrics import MetricsRow, summarize

WINDOW = 300.0


def row(
    status: EventStatus,
    *,
    violation: ViolationType = ViolationType.NO_HELMET,
    resolution_sec: int | None = None,
    false_positive: bool = False,
    suppressed: bool = False,
) -> MetricsRow:
    return MetricsRow(
        violation_type=violation,
        status=status,
        resolution_sec=resolution_sec,
        is_false_positive=false_positive,
        alert_suppressed=suppressed,
    )


def test_empty_population_is_null_not_zero() -> None:
    """§6.7 — **분모가 0이면 `null` 이다.**

    `0.0` 은 "시정률이 0%"라는 주장이고, 실제로는 "판정 가능한 이벤트가 없다"는
    뜻이다. 둘을 같은 값으로 내보내면 아무 일도 없던 구간이 "아무도 시정하지
    않았다"로 읽힌다 — 대응이 정반대인 두 상황이다.
    """
    summary = summarize([], period="today", resolve_window_s=WINDOW)
    assert summary.correction_rate is None
    assert summary.undetermined_rate is None
    assert summary.total_violations == 0


def test_only_undetermined_leaves_the_correction_rate_null() -> None:
    """판정 불가만 있는 구간. 시정률은 `null`, 판정 불가율은 1.0 이다."""
    summary = summarize([row(EventStatus.EXPIRED)], period="today", resolve_window_s=WINDOW)
    assert summary.correction_rate is None
    assert summary.undetermined_rate == pytest.approx(1.0)
    assert summary.undetermined == 1


def test_resolved_over_the_three_exclusive_buckets() -> None:
    rows = [
        row(EventStatus.RESOLVED, resolution_sec=12),
        row(EventStatus.RESOLVED, resolution_sec=41),
        row(EventStatus.ALERTED),
        row(EventStatus.RE_ALERTED),
    ]
    summary = summarize(rows, period="today", resolve_window_s=WINDOW)
    assert summary.resolved == 2
    assert summary.resolved_late == 0
    assert summary.unresolved == 2
    assert summary.correction_rate == pytest.approx(0.5)
    # (12 + 41) / 2 = 26.5 → 짝수 쪽으로 반올림(파이썬 기본)해 26.
    assert summary.avg_resolution_sec == 26


def test_expired_leaves_the_correction_rate_untouched() -> None:
    """§6.7 의 핵심. `expired` 를 넣고 빼도 시정률이 움직이면 안 된다."""
    base = [row(EventStatus.RESOLVED, resolution_sec=10), row(EventStatus.ALERTED)]
    without = summarize(base, period="today", resolve_window_s=WINDOW)
    with_expired = summarize(
        [*base, row(EventStatus.EXPIRED), row(EventStatus.EXPIRED)],
        period="today",
        resolve_window_s=WINDOW,
    )
    assert with_expired.correction_rate == without.correction_rate == pytest.approx(0.5)
    assert with_expired.undetermined == 2
    assert with_expired.undetermined_rate == pytest.approx(2 / 4)
    assert with_expired.total_violations == 4


def test_late_resolution_gets_its_own_bucket() -> None:
    """창(300초)을 넘겨 해소된 건은 분자에서 빠지되 모집단에는 남는다(§6.7).

    **`unresolved` 에 섞지 않는다.** "시정은 했으나 늦었다"와 "아직 안 했다"는
    현장에서 의미가 다르고, 합쳐두면 응답만 보고 원인을 구분할 수 없다.
    """
    summary = summarize(
        [
            row(EventStatus.RESOLVED, resolution_sec=10),
            row(EventStatus.RESOLVED, resolution_sec=901),
        ],
        period="today",
        resolve_window_s=WINDOW,
    )
    assert summary.resolved == 1
    assert summary.resolved_late == 1
    assert summary.unresolved == 0
    assert summary.correction_rate == pytest.approx(0.5)


def test_the_three_buckets_are_mutually_exclusive_and_sum_to_the_denominator() -> None:
    """§6.7 — `resolved` · `resolved_late` · `unresolved` 의 합이 분모다.

    응답만 보고 `correction_rate = resolved / (resolved + resolved_late + unresolved)`
    가 성립해야 한다. 성립하지 않으면 화면이 서버와 다른 숫자를 계산할 수 있다.
    """
    summary = summarize(
        [
            row(EventStatus.RESOLVED, resolution_sec=10),
            row(EventStatus.RESOLVED, resolution_sec=20),
            row(EventStatus.RESOLVED, resolution_sec=901),
            row(EventStatus.ALERTED),
            row(EventStatus.EXPIRED),
        ],
        period="today",
        resolve_window_s=WINDOW,
    )
    denominator = summary.resolved + summary.resolved_late + summary.unresolved
    assert (summary.resolved, summary.resolved_late, summary.unresolved) == (2, 1, 1)
    assert summary.correction_rate == pytest.approx(summary.resolved / denominator)
    assert summary.total_violations == denominator + summary.undetermined
    assert summary.undetermined_rate == pytest.approx(1 / 5)


def test_dropped_is_excluded_from_both_rates() -> None:
    """§4.2 — 확정 전 소멸(`dropped`)은 시정률에도 판정 불가율에도 들어가지 않는다.

    `expired` 로 샜다면 판정 불가율이 오르고, 분모에 남았다면 시정률이 내려간다.
    레코드는 존재하지만 두 비율 중 어느 것도 움직이면 안 된다.
    """
    base = [row(EventStatus.RESOLVED, resolution_sec=10), row(EventStatus.EXPIRED)]
    without = summarize(base, period="today", resolve_window_s=WINDOW)
    with_dropped = summarize(
        [*base, row(EventStatus.DROPPED), row(EventStatus.DROPPED)],
        period="today",
        resolve_window_s=WINDOW,
    )
    assert with_dropped.correction_rate == without.correction_rate == pytest.approx(1.0)
    assert with_dropped.undetermined_rate == without.undetermined_rate == pytest.approx(0.5)
    assert with_dropped.total_violations == without.total_violations == 2


def test_fall_is_counted_separately_and_never_in_the_denominator() -> None:
    """쓰러진 사람은 방송을 듣고 스스로 시정할 수 없다."""
    summary = summarize(
        [
            row(EventStatus.RESOLVED, resolution_sec=10),
            row(EventStatus.ALERTED, violation=ViolationType.FALL),
            row(EventStatus.EXPIRED, violation=ViolationType.FALL),
        ],
        period="today",
        resolve_window_s=WINDOW,
    )
    assert summary.fall_events == 2
    assert summary.correction_rate == pytest.approx(1.0)
    assert summary.undetermined == 0
    assert summary.total_violations == 1


def test_false_positive_is_excluded_entirely() -> None:
    """오탐은 시스템이 틀린 것이다. 분모에 남기면 작업자가 시정하지 않은 것이 된다."""
    summary = summarize(
        [
            row(EventStatus.RESOLVED, resolution_sec=10),
            row(EventStatus.ALERTED, false_positive=True),
            row(EventStatus.EXPIRED, false_positive=True),
        ],
        period="today",
        resolve_window_s=WINDOW,
    )
    assert summary.correction_rate == pytest.approx(1.0)
    assert summary.undetermined == 0
    assert summary.total_violations == 1


def test_events_before_the_broadcast_are_not_in_the_population() -> None:
    """지표 이름이 「**방송 후** 시정률」이다. 경고가 나가지 않은 건은 모집단이 아니다.

    `lost` 도 마찬가지다 — 아직 `resolved` 도 `expired` 도 아닌 진행 중 상태이며,
    결론이 나면 둘 중 하나로 여기 다시 들어온다.
    """
    summary = summarize(
        [row(EventStatus.CANDIDATE), row(EventStatus.ACTIVE), row(EventStatus.LOST)],
        period="today",
        resolve_window_s=WINDOW,
    )
    assert summary.total_violations == 0
    assert summary.correction_rate is None


def test_resolved_without_a_duration_is_not_credited() -> None:
    """`resolution_sec` 이 비어 있으면 창 안이었다고 주장할 근거가 없다.

    `unresolved`(아직 해소 안 됨)도 사실이 아니므로 늦은 시정 쪽에 둔다 — 분모에는
    들어가고 분자에서는 빠지는 자리다.
    """
    summary = summarize([row(EventStatus.RESOLVED)], period="today", resolve_window_s=WINDOW)
    assert summary.resolved == 0
    assert summary.resolved_late == 1
    assert summary.unresolved == 0
    assert summary.correction_rate == pytest.approx(0.0)


# --- §4.8 방송 없이 확정된 이벤트 -------------------------------------------


def test_a_suppressed_event_is_excluded_from_both_ratios() -> None:
    """★ §4.8 — 「**방송 후** 시정률」이므로 방송이 없었던 건은 모집단이 아니다.

    작업자에게 알린 적이 없으니 시정할 기회도 없었고, 이를 미시정으로 세면 시스템
    성능을 부당하게 깎는다. `expired` 와 같은 원칙으로 제외하고 건수를 공개한다.
    """
    summary = summarize(
        [row(EventStatus.ALERTED, suppressed=True)], period="today", resolve_window_s=WINDOW
    )

    assert summary.correction_rate is None
    assert summary.undetermined_rate is None
    assert summary.total_violations == 0
    assert summary.unresolved == 0
    assert summary.suppressed == 1


def test_a_suppressed_event_does_not_dilute_a_broadcast_one() -> None:
    """섞였을 때가 진짜 시험이다 — 새면 `1.00` 이 `0.50` 이 된다.

    `sim/cases/alert_suppressed.yaml` 이 같은 성질을 서버 전체 경로에서 잠근다.
    """
    rows = [
        row(EventStatus.RESOLVED, resolution_sec=12),
        row(EventStatus.ALERTED, suppressed=True),
    ]
    summary = summarize(rows, period="today", resolve_window_s=WINDOW)

    assert summary.correction_rate == pytest.approx(1.0)
    assert summary.total_violations == 1
    assert summary.suppressed == 1


def test_a_resolved_but_suppressed_event_is_not_counted_as_a_success_either() -> None:
    """해소됐어도 분자에 넣지 않는다.

    방송을 듣지 않은 사람이 스스로 그만둔 것을 「방송 후 시정」으로 세면 지표가
    자기 이름과 어긋난다 — 그 숫자로는 방송의 효과를 주장할 수 없다.
    """
    summary = summarize(
        [row(EventStatus.RESOLVED, resolution_sec=8, suppressed=True)],
        period="today",
        resolve_window_s=WINDOW,
    )

    assert summary.resolved == 0
    assert summary.correction_rate is None
    assert summary.suppressed == 1
    # 평균 시정 시간에도 섞이지 않는다 — 방송 기준 시각이 없는 건이다.
    assert summary.avg_resolution_sec == 0


def test_a_false_positive_wins_over_suppression() -> None:
    """오탐으로 정정된 건은 **어느 칸에도** 들어가지 않는다.

    `suppressed` 로 세면 "방송만 안 나갔다"로 읽혀 오탐이었다는 사실이 사라진다.
    """
    summary = summarize(
        [row(EventStatus.ALERTED, suppressed=True, false_positive=True)],
        period="today",
        resolve_window_s=WINDOW,
    )

    assert summary.suppressed == 0
    assert summary.total_violations == 0
