"""클라우드 격리 — 실패를 **상태로 바꾸고 거기서 멈춘다.** FN-SYS-03

기능명세서 §4.8 · API명세서 §4.6 `cloud` · §5.3 `system`

★ **클라우드가 죽어도 안전 기능은 무영향이어야 한다.** 그 보장은 두 겹이다.

1. **경로를 섞지 않는다.** 감지 → 확정 → 경고 → 시정 판정 어디에도 클라우드 호출이
   없다. `server/domain` 은 I/O 자체가 없고(절대규칙 2), `alert_service` 와
   `infra/clip` 은 스피커·MQTT·REC 만 만진다. 이 파일이 사는 `server/ai` 는 그 경로에서
   **아무도 기다리지 않는** 곳이다.
2. **실패가 밖으로 새지 않는다.** 여기를 지나는 모든 호출은 성공하면 값을, 실패하면
   `None` 을 돌려주고 실패 사실은 `CloudRuntime` 과 §5.3 `system` 메시지로만 나간다.

`None` 을 조용한 실패로 보지 않는 이유: 실패는 **로그와 상태 두 곳에** 남기 때문이다.
호출자가 「분석이 아직 없다」와 「클라우드가 죽었다」를 구분해야 할 때 보는 곳은 반환값이
아니라 `GET /system/status` 의 `cloud` 절이다(절대규칙 9).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aegis_vision.clock import Clock
from server.ai.ports import CloudError
from server.domain.cloud_state import CloudRuntime

__all__ = ["CloudGuard"]

log = logging.getLogger("server.ai")

#: 발행자 자리. `DashboardHub.broadcast` 와 같은 모양이다.
Publisher = Callable[[Any], Awaitable[None]]


class CloudGuard:
    """클라우드 호출 하나를 감싸 상태를 갱신하고 실패를 삼킨다.

    **삼키는 것은 예외뿐이고 사실은 삼키지 않는다** — 로그 · `CloudRuntime` ·
    `system` 메시지 세 곳에 남는다.
    """

    def __init__(
        self,
        runtime: CloudRuntime,
        clock: Clock,
        publish: Publisher | None = None,
    ) -> None:
        self._runtime = runtime
        self._clock = clock
        self._publish = publish

    @property
    def enabled(self) -> bool:
        """클라우드를 부를 수 있는가. **어댑터가 없으면 부르지 않는다.**"""
        return self._runtime.available or self._runtime.last_error is None

    async def call[T](self, what: str, coro: Awaitable[T]) -> T | None:
        """성공하면 값, 실패하면 `None`. 어느 쪽이든 상태가 갱신된다."""
        try:
            result = await coro
        except CloudError as exc:
            log.warning("클라우드 %s 실패 — %s (안전 기능은 계속 동작한다)", what, exc)
            await self._emit(self._runtime.mark_failed(self._clock.now(), str(exc)))
            return None
        except Exception as exc:  # 어댑터가 놓친 예외까지 여기서 막는다
            log.exception("클라우드 %s 에서 예상 못한 실패", what)
            await self._emit(self._runtime.mark_failed(self._clock.now(), str(exc)))
            return None
        await self._emit(self._runtime.mark_ok(self._clock.now()))
        return result

    async def _emit(self, message: Any | None) -> None:
        """상태가 **변한 때만** 메시지가 온다(§5.3). 발행자가 없으면 상태만 남는다."""
        if message is not None and self._publish is not None:
            await self._publish(message)
