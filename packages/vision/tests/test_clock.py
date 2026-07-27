"""`Clock` 주입 규약 검증.

상태머신 테스트가 3초 · 10초 · 15초 · 30초 · 300초 타이머를 순간이동시킬 수 있어야
하므로, 여기가 깨지면 이후 모든 검증이 성립하지 않는다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aegis_vision.clock import Clock, FakeClock, RealClock


def test_real_clock_satisfies_protocol() -> None:
    assert isinstance(RealClock(), Clock)


def test_fake_clock_satisfies_protocol() -> None:
    assert isinstance(FakeClock(), Clock)


def test_real_clock_returns_aware_utc() -> None:
    """API명세서 §1.2 — 저장은 UTC."""
    assert RealClock().now().tzinfo is not None


def test_fake_clock_does_not_move_on_its_own() -> None:
    clock = FakeClock()
    first = clock.now()
    assert clock.now() == first
    assert clock.monotonic() == 0.0


@pytest.mark.parametrize("seconds", [3.0, 10.0, 15.0, 30.0, 300.0])
def test_advance_moves_both_clocks(seconds: float) -> None:
    clock = FakeClock()
    before = clock.now()
    clock.advance(seconds)
    assert (clock.now() - before).total_seconds() == seconds
    assert clock.monotonic() == seconds


def test_advance_accumulates() -> None:
    clock = FakeClock()
    clock.advance(3.0)
    clock.advance(7.0)
    assert clock.monotonic() == 10.0


def test_advance_rejects_rewind() -> None:
    with pytest.raises(ValueError, match="음수"):
        FakeClock().advance(-1.0)


def test_set_moves_wall_clock_only() -> None:
    """엣지–서버 시각 어긋남(`edge_offset_ms`) 재현용."""
    clock = FakeClock()
    clock.advance(5.0)
    clock.set(datetime(2030, 1, 1, tzinfo=UTC))
    assert clock.now() == datetime(2030, 1, 1, tzinfo=UTC)
    assert clock.monotonic() == 5.0


@pytest.mark.parametrize("method", ["init", "set"])
def test_naive_datetime_is_rejected(method: str) -> None:
    naive = datetime(2026, 8, 14, 5, 37)  # noqa: DTZ001 — 거부되는지 확인하려고 일부러 naive
    with pytest.raises(ValueError, match="tz-aware"):
        if method == "init":
            FakeClock(start=naive)
        else:
            FakeClock().set(naive)
