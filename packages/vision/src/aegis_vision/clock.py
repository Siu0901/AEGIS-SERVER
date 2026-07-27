"""시간 주입 프로토콜.

CLAUDE.md 절대규칙 1 — **시간을 직접 읽지 않는다.** `datetime.now()` / `time.time()`
호출은 이 모듈의 `RealClock` 안에만 존재하며, 다른 모든 코드는 `Clock` 을 주입받는다.

이 규칙이 있는 이유는 테스트가 3초(확정) · 10초(해소) · 15초(소실 유예) · 30초(쿨다운) ·
300초(시정 창) 타이머를 순간이동시켜야 하기 때문이다. 규칙이 깨지면 상태머신 검증
자체가 불가능해진다.

    clock = FakeClock()
    machine = EventMachine(clock=clock)
    clock.advance(3.0)      # 확정 타이머 만료

`now()` 와 `monotonic()` 을 함께 두는 이유: 기록용 시각(DB · 메시지 `ts`)은 벽시계가
필요하고, 경과시간 측정은 NTP 보정에 흔들리지 않는 단조 시계가 필요하다.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "FakeClock", "RealClock"]


@runtime_checkable
class Clock(Protocol):
    """주입 가능한 시계."""

    def now(self) -> datetime:
        """현재 벽시계 시각. **항상 UTC aware** 여야 한다(API명세서 §1.2)."""
        ...

    def monotonic(self) -> float:
        """경과시간 측정용 단조 증가 초. 벽시계 보정에 영향받지 않는다."""
        ...


class RealClock:
    """실제 시스템 시계.

    프로덕션 조립 지점(FastAPI 의존성, 시뮬레이터 진입점)에서만 생성한다.
    **이 프로젝트에서 `datetime.now()` / `time.monotonic()` 을 호출해도 되는 유일한 곳이다.**
    """

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    """테스트용 시계. `advance()` 로만 시간이 흐른다.

    `start` 를 주지 않으면 고정된 기준 시각에서 출발하므로 테스트가 결정적이다.
    """

    _DEFAULT_START = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)

    def __init__(self, start: datetime | None = None, *, monotonic_start: float = 0.0) -> None:
        base = self._DEFAULT_START if start is None else start
        if base.tzinfo is None:
            msg = "FakeClock 의 start 는 tz-aware 여야 한다 (UTC 권장)"
            raise ValueError(msg)
        self._now = base
        self._monotonic = monotonic_start

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        """시간을 앞으로 감는다. 되감기는 지원하지 않는다."""
        if seconds < 0:
            msg = "FakeClock.advance 는 음수를 받지 않는다"
            raise ValueError(msg)
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds

    def set(self, moment: datetime) -> None:
        """벽시계만 특정 시각으로 옮긴다. 단조 시계는 건드리지 않는다.

        엣지–서버 시각 차이(`time_sync.edge_offset_ms`)처럼 벽시계만 어긋나는
        상황을 재현할 때 쓴다.
        """
        if moment.tzinfo is None:
            msg = "FakeClock.set 은 tz-aware datetime 을 받는다 (UTC 권장)"
            raise ValueError(msg)
        self._now = moment
