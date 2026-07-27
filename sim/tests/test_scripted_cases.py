"""시나리오 파일이 계약 스키마로 검증되는지 확인한다.

시뮬레이터가 실물과 구분되지 않으려면 케이스 파일이 `aegis_contracts` 를 통과해야 한다.
서버도 브로커도 필요 없는 검사다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sim.edge_sim.scripted import CASES_DIR, load_case

START = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)

CASE_NAMES = sorted(path.stem for path in CASES_DIR.glob("*.yaml"))


def test_at_least_one_case_exists() -> None:
    assert CASE_NAMES


@pytest.mark.parametrize("case", CASE_NAMES)
def test_case_loads_and_validates(case: str) -> None:
    timeline = load_case(case, START)
    assert timeline
    # 시각 순 정렬은 재생기가 의존하는 불변식이다.
    assert [item.at_s for item in timeline] == sorted(item.at_s for item in timeline)


@pytest.mark.parametrize("case", CASE_NAMES)
def test_timestamps_are_derived_from_start(case: str) -> None:
    """`ts` 는 시나리오가 적지 않고 시작 시각 + 경과로 주입된다."""
    for item in load_case(case, START):
        stamp = getattr(item.message, "ts", None) or item.message.last_ts
        assert (stamp - START).total_seconds() == pytest.approx(item.at_s)


def test_unknown_case_names_available_options() -> None:
    with pytest.raises(FileNotFoundError, match="사용 가능"):
        load_case("존재하지_않는_케이스", START)
