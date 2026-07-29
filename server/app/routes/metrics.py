"""`GET /metrics/summary` — 「방송 후 시정률」과 「판정 불가율」. API명세서 §4.2 · §6.7

**두 숫자는 항상 함께 나간다.** 시정률만 떼어 보여주면 추적이 끊긴 이벤트가 몇 건인지
알 수 없어 그 숫자를 검증할 수 없다 — `방송 후 시정률 87% (판정 불가 5%)` 형태가
표기 규칙이다(FN-SYS-04/05).

시계열(`/metrics/timeseries`) · 분포(`/metrics/distribution`) · 반복
(`/metrics/repeat`)은 분석 화면(FN-UI-05)과 함께 붙는다.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime

from aegis_contracts import ErrorBody, ErrorResponse, MetricsSummary
from server.app.event_service import EventService

__all__ = ["router"]

log = logging.getLogger("server.routes.metrics")

router = APIRouter(tags=["metrics"])


@router.get(
    "/metrics/summary",
    response_model=MetricsSummary,
    responses={503: {"model": ErrorResponse}},
)
async def metrics_summary(
    request: Request,
    from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to: AwareDatetime | None = None,
) -> MetricsSummary:
    """구간을 주지 않으면 **오늘**(UTC 자정 기준)이다.

    §4.2 는 `period` 를 응답 필드로만 정의하고 쿼리 파라미터를 적지 않았다. 다른 지표
    엔드포인트와 같은 `from` · `to` 를 받고, 주지 않으면 `period = "today"` 로 답한다.
    """
    service: EventService | None = getattr(request.app.state, "event_service", None)
    if service is None:
        raise _error(503, "이벤트 저장소가 연결되지 않았습니다")
    try:
        return await service.summary(from_=from_, to=to)
    except (OSError, RuntimeError) as exc:
        log.warning("지표를 계산하지 못했다: %s", exc)
        raise _error(503, "지표를 계산하지 못했습니다", str(exc)) from exc


def _error(http_status: int, message: str, reason: str | None = None) -> HTTPException:
    """§1.4 오류 봉투. FastAPI 기본 `{"detail": ...}` 형태를 쓰지 않는다."""
    body = ErrorResponse(
        error=ErrorBody.model_validate(
            {
                "code": "NOT_FOUND",
                "message": message,
                "detail": {"reason": reason} if reason else None,
            }
        )
    )
    return HTTPException(status_code=http_status, detail=body.model_dump(mode="json"))
