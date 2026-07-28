"""mediamtx 제어 API 클라이언트.

`GET {MEDIAMTX_API}/v3/paths/list` 하나만 쓴다. 필요한 것은 경로별 `ready` 여부뿐이고,
그 이상을 읽으면 mediamtx 버전이 바뀔 때마다 깨진다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx2

__all__ = ["MediaMtxClient", "MediaMtxUnavailableError", "PathState"]

log = logging.getLogger("server.stream.mediamtx")


class MediaMtxUnavailableError(RuntimeError):
    """제어 API 에 닿지 못했다. 카메라가 끊긴 것과 **다른 사건**이다.

    구분하는 이유: mediamtx 가 죽으면 모든 카메라가 동시에 끊긴 것처럼 보이는데,
    그것을 카메라 장애로 보고하면 현장에서 엉뚱한 카메라를 확인하러 간다.
    """


@dataclass(frozen=True, slots=True)
class PathState:
    """경로 하나의 상태."""

    name: str
    ready: bool
    """퍼블리셔가 붙어 있고 재송출 가능한 상태인가."""


class MediaMtxClient:
    """제어 API 를 읽는 얇은 클라이언트."""

    def __init__(self, base_url: str, *, timeout_s: float = 2.0) -> None:
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

    async def paths(self) -> dict[str, PathState]:
        """경로명 → 상태.

        페이지네이션을 따라간다. 경로가 4개뿐이라 한 페이지에 다 들어오지만, 카메라를
        늘렸을 때 뒤쪽 경로가 조용히 사라져 "카메라 끊김"으로 오인되면 안 된다.
        """
        found: dict[str, PathState] = {}
        page = 0
        while True:
            payload = await self._get("/v3/paths/list", {"page": page, "itemsPerPage": 100})
            items = payload.get("items")
            if not isinstance(items, list):
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if isinstance(name, str):
                    found[name] = PathState(name=name, ready=bool(item.get("ready", False)))
            page_count = payload.get("pageCount")
            if not isinstance(page_count, int) or page + 1 >= page_count:
                break
            page += 1
        return found

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            msg = f"mediamtx 제어 API 실패 ({self._base_url}{path}): {exc}"
            raise MediaMtxUnavailableError(msg) from exc
        if not isinstance(payload, dict):
            msg = f"mediamtx 응답이 객체가 아니다: {type(payload).__name__}"
            raise MediaMtxUnavailableError(msg)
        return payload
