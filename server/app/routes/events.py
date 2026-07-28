"""`GET /events` · `GET /events/{event_id}` (API명세서 §4.1 · FN-REC-04).

M2 에서 여기 쌓이는 것은 **후보 단계 이벤트**뿐이다(`status = "candidate"`).
확정·경고·해소 시각과 클립·키프레임은 각각 M3 에서 채워진다 — 지금 그 자리를
그럴듯한 값으로 메우면 시정률의 원천 데이터가 처음부터 오염된다.

`PATCH /events/{event_id}`(수동 정정 · FN-EVT-05)는 M4 다.
"""

from __future__ import annotations

import logging
from typing import Annotated, Protocol

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime

from aegis_contracts import (
    ErrorBody,
    ErrorResponse,
    EventDetail,
    EventListQuery,
    EventListResponse,
    EventStatus,
    EventSummary,
    ViolationType,
)

__all__ = ["router"]

log = logging.getLogger("server.routes.events")

router = APIRouter(tags=["events"])


class EventReader(Protocol):
    """이 라우터가 요구하는 조회 능력. 구현은 `server/infra/db/repository.py`."""

    async def list_events(self, query: EventListQuery) -> tuple[list[EventSummary], str | None]: ...

    async def get(self, event_id: str) -> EventDetail | None: ...


@router.get(
    "/events",
    response_model=EventListResponse,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def list_events(
    request: Request,
    from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to: AwareDatetime | None = None,
    cam_id: int | None = None,
    type: ViolationType | None = None,  # noqa: A002 — §4.1 이 정한 쿼리 파라미터 이름이다
    status: EventStatus | None = None,
    zone_id: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> EventListResponse:
    """이벤트 목록. 쿼리 파라미터는 §4.1 그대로다."""
    query = EventListQuery.model_validate(
        {
            "from": from_,
            "to": to,
            "cam_id": cam_id,
            "type": type,
            "status": status,
            "zone_id": zone_id,
            "limit": limit,
            "cursor": cursor,
        }
    )
    reader = _reader(request)
    try:
        items, next_cursor = await reader.list_events(query)
    except ValueError as exc:
        # 깨진 커서. 조용히 첫 장으로 되돌리면 클라이언트가 같은 장을 무한히 돈다.
        raise _error(400, "VALIDATION_ERROR", str(exc), {"cursor": cursor}) from exc
    except OSError as exc:
        raise _unavailable(exc) from exc
    return EventListResponse(items=items, next_cursor=next_cursor)


@router.get(
    "/events/{event_id}",
    response_model=EventDetail,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def get_event(request: Request, event_id: str) -> EventDetail:
    try:
        event = await _reader(request).get(event_id)
    except OSError as exc:
        raise _unavailable(exc) from exc
    if event is None:
        raise _error(404, "NOT_FOUND", "요청한 이벤트가 존재하지 않습니다", {"event_id": event_id})
    return event


def _reader(request: Request) -> EventReader:
    reader: EventReader | None = getattr(request.app.state, "events", None)
    if reader is None:
        # 조립이 잘못된 것이지 사용자의 잘못이 아니다. 빈 목록으로 덮지 않는다 —
        # "이벤트가 없다"와 "저장소가 없다"는 화면에서 구분되어야 한다.
        raise _error(503, "NOT_FOUND", "이벤트 저장소가 연결되지 않았습니다")
    return reader


def _unavailable(exc: Exception) -> HTTPException:
    log.warning("이벤트 저장소에 닿지 못했다: %s", exc)
    return _error(503, "NOT_FOUND", "이벤트 저장소에 닿지 못했습니다", {"reason": str(exc)})


def _error(
    http_status: int,
    code: str,
    message: str,
    detail: dict[str, object] | None = None,
) -> HTTPException:
    """§1.4 오류 봉투. FastAPI 기본 `{"detail": ...}` 형태를 쓰지 않는다."""
    body = ErrorResponse(
        error=ErrorBody.model_validate({"code": code, "message": message, "detail": detail})
    )
    return HTTPException(status_code=http_status, detail=body.model_dump(mode="json"))
