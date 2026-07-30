"""REC 컴포넌트 클라이언트 (API명세서 §4.7).

**서버가 녹화에 닿는 유일한 통로다.** 개발 중에는 REC 이 같은 기계에서 돌지만
파일 경로로 읽지 않는다 — M9 에 젯슨 SSD 로 옮길 때 고쳐야 하는 값이
`RECORDER_BASE` 하나뿐이어야 하기 때문이다(기능명세서 §4.4).

세 엔드포인트를 쓴다.

| 호출 | 언제 | FN |
|---|---|---|
| `GET /status` | 10초 주기 · `GET /system/status` · **세그먼트 길이 조회** | FN-SYS-01 |
| `GET /keyframe` | 확정 **즉시** (스냅샷 버퍼에서 나온다) | FN-REC-03 |
| `POST /clips` | `confirmed_at + post_roll + 세그먼트 길이 + margin` **예약 실행** | FN-REC-03 |

**클립은 확정 즉시 뽑지 않는다.** 그 순간에는 사후 구간이 아직 녹화되지 않았다
(기능명세서 §4.4). 예약과 상태 관리는 `server/infra/clip/` 이 한다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

import httpx2
from pydantic import ValidationError

from aegis_contracts import ClipRequest, ClipResponse, RecStatusResponse

__all__ = ["ClipExtractor", "RecClient", "RecUnavailableError", "StorageReader"]

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


class ClipExtractor(Protocol):
    """클립 예약 추출(FN-REC-03)이 요구하는 REC 능력. §4.7

    `StorageReader` 와 나눈 이유는 부르는 시점이 다르기 때문이다 — 상태는 10초마다
    폴링하고, 이쪽은 이벤트가 났을 때만 부른다. `status()` 가 양쪽에 다 있는 이유는
    **세그먼트 길이가 예약 실행 시각의 한 항**이기 때문이다(기능명세서 §4.4) — 상태
    폴링이 아직 한 번도 성공하지 않았어도 예약을 실행하려면 그 값을 알아야 한다.
    """

    async def status(self) -> RecStatusResponse: ...

    async def keyframe(self, cam_id: int, at: datetime) -> bytes: ...

    async def create_clip(self, request: ClipRequest) -> ClipResponse: ...

    async def download(self, url: str) -> bytes: ...


class RecClient:
    """REC HTTP API 를 읽는 얇은 클라이언트."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 3.0,
        extract_timeout_s: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx2.AsyncClient(base_url=self._base_url, timeout=timeout_s)
        # 상태 조회와 추출은 예산이 다르다. 20초짜리 클립을 여러 세그먼트에서 이어붙여
        # 잘라내는 데 3초는 모자라고, 그 타임아웃이 곧 `clip_status = failed` 가 된다.
        self._extract_timeout_s = extract_timeout_s

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

    async def keyframe(self, cam_id: int, at: datetime) -> bytes:
        """`GET /keyframe` — JPEG 한 장. FN-REC-03

        확정 **즉시** 부른다. 그 시각의 프레임은 REC 의 스냅샷 버퍼(최근 60초)에 있으므로
        사후 구간을 기다릴 필요가 없고(기능명세서 §4.4), 클립이 준비될 때까지 대시보드가
        대신 보여줄 그림이다.
        """
        try:
            response = await self._client.get(
                "/keyframe",
                params={"cam_id": cam_id, "at": at.isoformat()},
                timeout=self._extract_timeout_s,
            )
            response.raise_for_status()
        except httpx2.HTTPError as exc:
            msg = (
                f"키프레임을 받지 못했다 (cam={cam_id} at={at.isoformat()}): "
                f"{type(exc).__name__}: {exc}"
            )
            raise RecUnavailableError(msg) from exc
        return bytes(response.content)

    async def create_clip(self, request: ClipRequest) -> ClipResponse:
        """`POST /clips` — 구간 추출. FN-REC-03

        **비-`ready` 를 예외로 만들지 않는다.** `partial` · `not_found` 는 REC 이 정상
        동작한 결과이고(§4.7), 그 `reason` 이 `clip_status = failed` 의 원인 기록이 된다.
        예외로 바꾸면 "보존 기간 경과"와 "REC 이 죽음"이 같은 모양이 되어 구분이 사라진다.
        """
        try:
            response = await self._client.post(
                "/clips",
                json=request.model_dump(mode="json", by_alias=True),
                timeout=self._extract_timeout_s,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            msg = f"클립 추출 요청이 실패했다 ({request.event_id}): {type(exc).__name__}: {exc}"
            raise RecUnavailableError(msg) from exc
        try:
            return ClipResponse.model_validate(payload)
        except ValidationError as exc:
            msg = f"REC 클립 응답이 API명세서 §4.7 과 다르다: {exc}"
            raise RecUnavailableError(msg) from exc

    async def download(self, url: str) -> bytes:
        """`download_url` 이 가리키는 파일을 받아온다.

        URL 은 `RECORDER_BASE` 기준 **상대 경로**다(§4.7). 절대 URL 이 오면 거부한다 —
        REC 이 알려준 주소로 아무 데나 요청을 보내면, 운용 시 엣지에 있는 그 프로세스가
        서버의 요청 경로를 결정하게 된다.
        """
        if "://" in url:
            msg = f"download_url 은 RECORDER_BASE 기준 상대 경로여야 한다: {url!r}"
            raise RecUnavailableError(msg)
        try:
            response = await self._client.get(url, timeout=self._extract_timeout_s)
            response.raise_for_status()
        except httpx2.HTTPError as exc:
            msg = f"클립 파일을 받지 못했다 ({url}): {type(exc).__name__}: {exc}"
            raise RecUnavailableError(msg) from exc
        return bytes(response.content)
