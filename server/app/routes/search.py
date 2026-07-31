"""`POST /search/scenes` — 자연어 장면 검색. FN-AI-02 · API명세서 §4.3

★ **하이브리드다.** 구조화 조건(기간·카메라·유형)은 SQL 로 먼저 좁히고, 자유 문장만
임베딩 유사도로 순위화한다. 판단은 전부 `server/ai/search.py` 와 저장소가 하고,
여기서는 요청을 넘기고 오류 봉투를 씌울 뿐이다.

**클라우드가 없어도 503 이 아니다.** 조건이 전부 구조화되어 있으면 SQL 만으로 답이
나오고, 응답의 `mode` 가 실제로 돈 경로를 말한다 — 화면은 그 값을 보고 「유사도순」인지
「시간순」인지 표시한다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from aegis_contracts import (
    ErrorBody,
    ErrorResponse,
    SceneSearchRequest,
    SceneSearchResponse,
)
from server.ai.service import AiService

__all__ = ["router"]

log = logging.getLogger("server.routes.search")

router = APIRouter(tags=["search"])


@router.post(
    "/search/scenes",
    response_model=SceneSearchResponse,
    responses={503: {"model": ErrorResponse}},
)
async def search_scenes(request: Request, body: SceneSearchRequest) -> SceneSearchResponse:
    """§4.3 — 질의 하나를 경로에 맞게 처리하고 결과를 유사도(또는 시간)순으로 돌려준다."""
    service: AiService | None = getattr(request.app.state, "ai", None)
    if service is None:
        raise _error("지능 기능이 연결되지 않았습니다")
    try:
        return await service.search(body)
    except (OSError, RuntimeError) as exc:
        log.warning("장면 검색이 실패했다: %s", exc)
        raise _error("장면을 검색하지 못했습니다", str(exc)) from exc


def _error(message: str, reason: str | None = None) -> HTTPException:
    body = ErrorResponse(
        error=ErrorBody.model_validate(
            {
                "code": "NOT_FOUND",
                "message": message,
                "detail": {"reason": reason} if reason else None,
            }
        )
    )
    return HTTPException(status_code=503, detail=body.model_dump(mode="json"))
