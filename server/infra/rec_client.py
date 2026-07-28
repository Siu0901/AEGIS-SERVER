"""REC 컴포넌트 클라이언트 (API명세서 §4.7).

**서버가 녹화에 닿는 유일한 통로다.** 개발 중에는 REC 이 같은 기계에서 돌지만
파일 경로로 읽지 않는다 — M9 에 젯슨 SSD 로 옮길 때 고쳐야 하는 값이
`RECORDER_BASE` 하나뿐이어야 하기 때문이다(기능명세서 §4.4).

M1 에서 쓰는 것은 `GET /status` 하나다. `POST /clips` · `GET /keyframe` 은 클립 예약
추출(FN-REC-03, M3)에서 붙인다.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Protocol, Self

import httpx2
from pydantic import ValidationError

from aegis_contracts import RecStatusResponse

__all__ = ["RecClient", "RecUnavailableError", "StorageReader"]

log = logging.getLogger("server.rec")


class RecUnavailableError(RuntimeError):
    """REC 에 닿지 못했거나 응답이 계약(§4.7)과 다르다."""


class StorageReader(Protocol):
    """앱이 요구하는 REC 클라이언트. 테스트가 가짜를 끼워 넣을 자리다.

    `main` 이 아니라 여기 두는 이유는 **라우트도 이 타입이 필요하기 때문**이다
    (`app.state.rec_client` 를 꺼내 쓴다). `main` 에 두면 라우트 → main → 라우트로
    순환 import 가 된다.
    """

    async def status(self) -> RecStatusResponse: ...
    async def aclose(self) -> None: ...


class RecClient:
    """REC HTTP API 를 읽는 얇은 클라이언트."""

    def __init__(self, base_url: str, *, timeout_s: float = 3.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx2.AsyncClient(base_url=self._base_url, timeout=timeout_s)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def status(self) -> RecStatusResponse:
        """`GET /status`. 서버는 이 값을 §4.6 `storage` 에 실어 나른다.

        응답을 계약으로 검증한다. REC 이 다른 모양을 돌려주기 시작하면 그 순간 알아야
        한다 — 조용히 통과시키면 대시보드가 오래된 용량을 계속 보여주게 된다.
        """
        try:
            response = await self._client.get("/status")
            response.raise_for_status()
            payload = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            # 예외 클래스명을 반드시 함께 남긴다. ConnectError 처럼 str() 이 비어 있는
            # 예외가 있어서, 메시지만 찍으면 "REC 에 닿지 못했다: " 로 끝나 원인이
            # 사라진다. 실제로 그 로그 한 줄 때문에 IPv6 문제를 한참 못 찾았다.
            msg = f"REC 에 닿지 못했다 ({self._base_url}/status): {type(exc).__name__}: {exc}"
            raise RecUnavailableError(msg) from exc
        try:
            return RecStatusResponse.model_validate(payload)
        except ValidationError as exc:
            msg = f"REC 응답이 API명세서 §4.7 과 다르다: {exc}"
            raise RecUnavailableError(msg) from exc
