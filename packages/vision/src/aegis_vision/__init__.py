"""AEGIS 순수 로직 — 호모그래피 · 접지점 · 구역 · 거리 · 자세.

**하드웨어 의존이 0이며 I/O가 없다.** DB · 네트워크 · 파일 · 시간 전부 금지이고
순수 함수만 둔다(CLAUDE.md 절대규칙 2). 시간이 필요하면 `clock.Clock` 을 주입받는다.

M0 에서는 `clock` 만 존재한다. 나머지 로직은 M6 에서 채운다.
"""

from .clock import Clock, FakeClock, RealClock

__all__ = ["Clock", "FakeClock", "RealClock"]
