"""JSONL 로그 재생 — **인터페이스만 있고 구현은 나중이다.**

실물 젯슨이 붙은 뒤(M9) 현장에서 받은 `/ws/edge` 트래픽을 그대로 다시 흘려보내
서버 상태머신을 회귀 검증하기 위한 소스다. `scripted` 와 같은
`list[ScheduledMessage]` 를 돌려주므로 `main.py` 는 둘을 구분하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .scripted import ScheduledMessage

__all__ = ["load_log"]


def load_log(path: str | Path, start: datetime) -> list[ScheduledMessage]:
    """JSONL 로그를 재생 가능한 메시지 목록으로 바꾼다.

    각 줄은 `/ws/edge` 로 실제 오갔던 메시지 하나이며, 첫 줄의 타임스탬프를 0초로
    삼아 상대 오프셋을 계산할 예정이다. `start` 는 재생 시각의 기준점이다.

    Raises:
        NotImplementedError: 아직 구현하지 않았다.
    """
    msg = "logreplay 는 아직 구현되지 않았다 (M9 예정). 지금은 --mode scripted 를 쓴다."
    raise NotImplementedError(msg)
