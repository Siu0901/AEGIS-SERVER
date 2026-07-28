"""`GET /policies` (API명세서 §4.5).

**M2 에는 조회만 있다.** `PATCH /policies`(임계값 정책 관리 · FN-CFG-04)는 설정
화면과 함께 M6 에서 붙는다.

조회가 먼저 필요한 이유는 오버레이 때문이다. 재생 경로별 지연 버퍼
(`overlay_buffer_webrtc_ms` · `overlay_buffer_hls_ms`)와 `overlay_stale_ms` 는
프론트가 박스를 언제 그릴지 정하는 값인데, **임계값을 코드에 하드코딩하지 않는다**
(CLAUDE.md 절대규칙 6). 값의 원본은 DB `policies` 테이블 하나이며 프론트는 이
엔드포인트로만 읽는다.
"""

from __future__ import annotations

import logging
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request

from aegis_contracts import ErrorBody, ErrorResponse, Policies

__all__ = ["router"]

log = logging.getLogger("server.routes.policies")

router = APIRouter(tags=["policies"])


class PolicyReader(Protocol):
    async def load(self) -> Policies: ...


@router.get("/policies", response_model=Policies, responses={503: {"model": ErrorResponse}})
async def get_policies(request: Request) -> Policies:
    reader: PolicyReader | None = getattr(request.app.state, "policies", None)
    if reader is None:
        raise _unavailable("정책 저장소가 연결되지 않았습니다")
    try:
        return await reader.load()
    except OSError as exc:
        # 계약의 기본값으로 대신 답하지 않는다. 그 기본값은 **시드의 원천**이지
        # 런타임 값이 아니며, 현장에서 조정한 임계값과 다를 수 있다. 조용히 다른
        # 값으로 답하면 화면은 정상으로 보이는데 동작만 어긋난다.
        log.warning("정책값을 읽지 못했다: %s", exc)
        raise _unavailable(f"정책 저장소에 닿지 못했습니다: {exc}") from exc


def _unavailable(message: str) -> HTTPException:
    body = ErrorResponse(
        error=ErrorBody.model_validate({"code": "NOT_FOUND", "message": message, "detail": None})
    )
    return HTTPException(status_code=503, detail=body.model_dump(mode="json"))
