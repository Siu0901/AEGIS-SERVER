"""`/ws/dashboard` — 서버 → 대시보드 WebSocket (API명세서 §5).

M1 에서 실제로 흐르는 것은 `system`(§5.3) 하나다. `overlay` · `event_*` · `metric` 은
M2 이후에 같은 허브로 붙는다.

메시지는 전부 `packages/contracts` 의 모델로 만든다(CLAUDE.md 절대규칙 5).
직렬화는 `by_alias=True` 로 한다 — `class` 처럼 파이썬 예약어를 피한 별칭이 있고,
별칭을 빼먹으면 계약과 다른 키가 나간다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

from aegis_contracts import SpecModel

__all__ = ["DashboardHub"]

log = logging.getLogger("server.ws.dashboard")


class DashboardHub:
    """접속한 대시보드들에게 메시지를 뿌린다."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        log.info("대시보드 접속 (총 %d)", len(self._clients))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)
        log.info("대시보드 종료 (총 %d)", len(self._clients))

    async def broadcast(self, message: SpecModel) -> None:
        """계약 모델 하나를 모든 접속자에게 보낸다.

        보내다 실패한 연결은 목록에서 뺀다. 죽은 소켓을 붙들고 있으면 다음 방송이
        그 소켓에서 막혀 **살아 있는 대시보드까지 갱신이 멈춘다.**
        """
        payload: dict[str, Any] = message.model_dump(mode="json", by_alias=True)
        async with self._lock:
            targets = list(self._clients)
        dead: list[WebSocket] = []
        for client in targets:
            try:
                await client.send_json(payload)
            except (RuntimeError, OSError) as exc:
                log.debug("대시보드 전송 실패 — 연결을 정리한다: %s", exc)
                dead.append(client)
        if dead:
            async with self._lock:
                self._clients.difference_update(dead)
