"""`GET /zones` (API명세서 §4.5).

**M2 에는 조회만 있다.** 구역 편집(`POST /zones` · FN-CFG-02)은 설정 화면과 함께
M6 에서 붙는다. 지금 조회가 먼저 필요한 이유는 오버레이 때문이다 — 금지구역
폴리곤은 매 프레임 변하지 않으므로 `overlay` 에 싣지 않고(§5.1), 대시보드가 여기서
한 번 받아 캐시한 뒤 `zone_updated`(§5.4)로 갱신하도록 되어 있다.
"""

from __future__ import annotations

import logging
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request

from aegis_contracts import ErrorBody, ErrorResponse, Zone

__all__ = ["router"]

log = logging.getLogger("server.routes.zones")

router = APIRouter(tags=["zones"])


class ZoneReader(Protocol):
    async def list_zones(self, cam_id: int | None = None) -> list[Zone]: ...


@router.get("/zones", response_model=list[Zone], responses={503: {"model": ErrorResponse}})
async def list_zones(request: Request, cam_id: int | None = None) -> list[Zone]:
    reader: ZoneReader | None = getattr(request.app.state, "zones", None)
    if reader is None:
        raise _unavailable("구역 저장소가 연결되지 않았습니다")
    try:
        return await reader.list_zones(cam_id)
    except OSError as exc:
        # 빈 배열로 답하지 않는다 — "구역이 없다"와 "DB 에 닿지 못했다"는 다른 사실이고,
        # 전자로 답하면 대시보드가 금지구역을 지운 채로 그린다.
        log.warning("구역을 읽지 못했다: %s", exc)
        raise _unavailable(f"구역 저장소에 닿지 못했습니다: {exc}") from exc


def _unavailable(message: str) -> HTTPException:
    body = ErrorResponse(
        error=ErrorBody.model_validate({"code": "NOT_FOUND", "message": message, "detail": None})
    )
    return HTTPException(status_code=503, detail=body.model_dump(mode="json"))
