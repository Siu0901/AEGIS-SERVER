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
) -> MetricsRow:
    return MetricsRow(
        violation_type=violation,
        status=status,
        resolution_sec=resolution_sec,
        is_false_positive=false_positive,
    )


def test_empty_population_is_zero_not_a_crash() -> None:
    summary = summarize([], period="today", resolve_window_s=WINDOW)
    assert summary.correction_rate == 0.0
    assert summary.undetermined_rate == 0.0
    assert summary.total_violations == 0


def test_resolved_over_resolved_plus_unresolved() -> None:
    rows = [
        row(EventStatus.RESOLVED, resolution_sec=12),
        row(EventStatus.RESOLVED, resolution_sec=41),
        row(EventStatus.ALERTED),
        row(EventStatus.RE_ALERTED),
    ]
    summary = summarize(rows, period="today", resolve_window_s=WINDOW)
    assert summary.resolved == 2
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


def test_late_resolution_stays_in_the_denominator_only() -> None:
    """창(300초)을 넘겨 해소된 건은 분자에서 빠지되 모집단에는 남는다(§6.7)."""
    summary = summarize(
        [
            row(EventStatus.RESOLVED, resolution_sec=10),
            row(EventStatus.RESOLVED, resolution_sec=901),
        ],
        period="today",
        resolve_window_s=WINDOW,
    )
    assert summary.resolved == 1
    assert summary.unresolved == 1
    assert summary.correction_rate == pytest.approx(0.5)


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
    assert summary.correction_rate == 0.0


def test_resolved_without_a_duration_is_not_credited() -> None:
    """`resolution_sec` 이 비어 있으면 창 안이었다고 주장할 근거가 없다."""
    summary = summarize([row(EventStatus.RESOLVED)], period="today", resolve_window_s=WINDOW)
    assert summary.resolved == 0
    assert summary.unresolved == 1
