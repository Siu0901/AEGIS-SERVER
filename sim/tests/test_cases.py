"""시나리오 9종을 서버 상태머신에 태워 기대값과 대조한다.

`sim/cases/*.yaml` 의 `expect:` 블록이 정답이고, 대조는 `sim/case_check.py` 가 한다.
여기서는 그것을 `uv run tasks.py verify` 안으로 끌어들이는 일만 한다 — 검증이
사람이 기억해서 돌려야 하는 명령에 걸려 있으면 조만간 아무도 돌리지 않는다.

시나리오가 실제로 무엇을 지키는지는 각 yaml 파일 머리말에 적혀 있다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from aegis_contracts import EventCreatedMsg, EventStatus, EventUpdatedMsg, MetricMsg
from sim.case_check import cases_with_expectations, check_case, run_case

CASES = cases_with_expectations()

#: 시나리오 11종. 이름이 바뀌거나 사라지면 여기서 드러난다.
#:
#: 앞의 아홉은 M3(상태머신·지표), 뒤의 둘은 M4(경고·클립)에서 추가됐다.
REQUIRED = {
    "normal_resolve",
    "no_resolve",
    "reassoc_success",
    "reassoc_fail",
    "id_switch_guard",
    "gating_freeze",
    "fall_excluded",
    "false_positive",
    "dropped",
    "clip_recovery",
    "alert_muted",
}


def _transitions(published: list[Any]) -> list[EventUpdatedMsg]:
    """상태 **전이** 메시지만 고른다.

    §5.2 는 클립 준비 완료도 `event_updated` 로 알린다(`clip_status` · `clip_url`).
    그 메시지의 `status` 는 그때의 상태를 그대로 실어 나를 뿐 전이가 아니므로,
    전이 사슬을 볼 때는 빼야 한다 — 섞으면 같은 상태가 두 번 나온 것처럼 보인다.
    """
    return [
        message
        for message in published
        if isinstance(message, EventUpdatedMsg) and message.clip_status is None
    ]


def test_every_required_scenario_exists() -> None:
    """파일이 사라지면 대조가 조용히 0건이 된다. 그것을 통과로 보지 않는다."""
    assert set(CASES) >= REQUIRED, f"빠진 시나리오: {sorted(REQUIRED - set(CASES))}"


@pytest.mark.parametrize("case", CASES)
def test_case_matches_its_expectations(case: str) -> None:
    result = asyncio.run(run_case(case))
    problems = check_case(case, result)
    assert not problems, "\n".join([f"{case} 기대값 불일치:", *(f"  - {p}" for p in problems)])


def test_dashboard_sees_the_whole_transition_chain() -> None:
    """§5.2 — 확정은 `event_created`, 이후 전이는 `event_updated` 로 나간다.

    프론트는 이것만 보고 상태를 갱신하므로, 전이가 일어났는데 메시지가 안 나가면
    화면은 영원히 이전 상태에 머문다.
    """
    result = asyncio.run(run_case("normal_resolve"))
    created = [m for m in result.published if isinstance(m, EventCreatedMsg)]
    updated = _transitions(result.published)

    assert len(created) == 1
    assert created[0].status is EventStatus.ALERTED
    assert created[0].confirmed_at is not None
    # §5.2 `severity` 는 §3 `AlertCommand.level` 과 같은 열거형을 공유한다.
    assert created[0].severity == 2

    assert [m.status for m in updated] == [EventStatus.RESOLVED]
    assert updated[0].resolved_at is not None
    assert updated[0].resolution_sec is not None

    # 종결이 일어났으니 지표도 다시 나갔어야 한다(§5.3 `metric`).
    metrics = [m for m in result.published if isinstance(m, MetricMsg)]
    assert metrics and metrics[-1].correction_rate == 1.0


def test_expired_is_broadcast_as_undetermined_not_as_a_failure_to_correct() -> None:
    """재결합 실패는 미시정이 아니라 판정 불가다. 지표 메시지에도 그렇게 나가야 한다."""
    result = asyncio.run(run_case("reassoc_fail"))
    updated = _transitions(result.published)
    assert [m.status for m in updated] == [EventStatus.LOST, EventStatus.EXPIRED]

    metrics = [m for m in result.published if isinstance(m, MetricMsg)]
    assert metrics
    assert metrics[-1].undetermined == 1
    assert metrics[-1].undetermined_rate == 1.0
    assert metrics[-1].unresolved == 0
    # ★ 분모가 0 이므로 시정률은 **null** 이다. `0.0` 으로 나가면 화면에 "시정률 0%"
    # 가 뜨고, 판정 불가만 있는 구간이 "아무도 시정하지 않았다"로 읽힌다(§6.7).
    assert metrics[-1].correction_rate is None


def test_dropped_leaves_a_record_and_touches_neither_rate() -> None:
    """확정 전 소멸은 §4.2 `dropped` 로 남는다. 지우지 않고, 지표도 건드리지 않는다."""
    result = asyncio.run(run_case("dropped"))
    assert [event.status for event in result.events] == [EventStatus.DROPPED]

    updated = _transitions(result.published)
    assert [m.status for m in updated] == [EventStatus.DROPPED]
    # 확정에 닿은 적이 없으므로 `event_created` 도 경고도 없다.
    assert not [m for m in result.published if isinstance(m, EventCreatedMsg)]

    metrics = result.metrics
    assert metrics.total_violations == 0
    assert (metrics.resolved, metrics.resolved_late, metrics.unresolved) == (0, 0, 0)
    assert metrics.undetermined == 0
    # `dropped` 가 미시정으로 새면 0.0, 판정 불가로 새면 undetermined_rate 가 1.0 이다.
    assert metrics.correction_rate is None
    assert metrics.undetermined_rate is None


def test_dropped_frees_the_merge_key() -> None:
    """`dropped` 는 종결 상태다 — 병합 키(FN-EVT-01)를 점유한 채 남아 있으면
    같은 트랙의 다음 위반이 이벤트를 만들지 못한다."""
    result = asyncio.run(run_case("dropped"))
    assert result.machine.open_events(1, 3) == {}
