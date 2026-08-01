"""챗봇 · 브리핑 · 주간 보고서. FN-AI-08 · 09 · 10 · API명세서 §4.4

| 경로 | 기능 |
|---|---|
| `POST /assistant/chat` | 라우팅(sql · vector · vision) 후 해당 경로 실행 |
| `POST /assistant/briefing` | 지금 프레임 → 현장 브리핑 |
| `POST /reports/weekly` | 기간 집계 → 주간 보고서 생성 예약 |

★ **통계 숫자는 `GET /metrics/summary` 와 같은 코드가 만든다.** 여기서 다시 세면
챗봇과 개요 화면이 서로 다른 시정률을 말하게 되고, 어느 쪽이 맞는지 가릴 방법이 없다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time

from fastapi import APIRouter, HTTPException, Request

from aegis_contracts import (
    BriefingRequest,
    BriefingResponse,
    ChatRequest,
    ChatResponse,
    ErrorBody,
    ErrorResponse,
    WeeklyReportRequest,
    WeeklyReportResponse,
)
from server.ai.service import AiService
from server.app.event_service import EventService

__all__ = ["router"]

log = logging.getLogger("server.routes.assistant")

router = APIRouter(tags=["assistant"])

#: 보고서 생성 예상 시간(초). §4.4 예시가 20 이다. 실제 생성은 배경에서 돈다.
REPORT_ESTIMATED_SEC = 20


@router.post(
    "/assistant/chat",
    response_model=ChatResponse,
    responses={503: {"model": ErrorResponse}},
)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """§4.4 — 질의 하나. `route` 로 어느 경로가 실제로 돌았는지 알린다.

    ★ **집계를 여기서 미리 만들지 않는다.** 전에는 라우팅 전에 `summary()` 를 한 번
    불러 넘겼는데, 그 값은 **항상 오늘치**였다 — 「이번 주 위반 몇 건」이라고 물어도
    오늘 숫자가 나갔고 문장은 그럴듯해서 아무도 알아채지 못했다. 이제 서비스가
    질문에서 기간을 뽑아 그 구간으로 집계한다.
    """
    service = _ai(request)
    try:
        return await service.chat(body)
    except (OSError, RuntimeError) as exc:
        log.warning("챗봇 응답이 실패했다: %s", exc)
        raise _error("답변을 만들지 못했습니다", str(exc)) from exc


@router.delete(
    "/assistant/chat/{session_id}",
    status_code=204,
    responses={503: {"model": ErrorResponse}},
)
async def clear_chat(request: Request, session_id: str) -> None:
    """세션 하나의 대화를 지운다. 화면의 「대화 지우기」가 부른다.

    §4.4 에 없는 경로다. `session_id` 를 받아 서버가 대화를 들고 있게 된 이상 그것을
    비울 자리도 있어야 한다 — 없으면 사용자가 화제를 바꾸고 싶을 때 브라우저를 새로
    열어야 한다. (`docs/INDEX.md` 「명세서 확인 필요」)
    """
    _ai(request).forget(session_id)


@router.post(
    "/assistant/briefing",
    response_model=BriefingResponse,
    responses={503: {"model": ErrorResponse}},
)
async def briefing(request: Request, body: BriefingRequest) -> BriefingResponse:
    """FN-AI-09 — 지금 이 순간의 현장 요약.

    **프레임을 못 가져오면 「이상 없음」이라고 하지 않는다.** 보지 않고 판단한 것이
    되기 때문이다. 그 사실을 그대로 문장에 적는다.
    """
    service = _ai(request)
    try:
        return await service.briefing(body.cam_ids)
    except (OSError, RuntimeError) as exc:
        log.warning("브리핑이 실패했다: %s", exc)
        raise _error("현장 상황을 요약하지 못했습니다", str(exc)) from exc


@router.post(
    "/reports/weekly",
    response_model=WeeklyReportResponse,
    status_code=202,
    responses={503: {"model": ErrorResponse}},
)
async def weekly_report(request: Request, body: WeeklyReportRequest) -> WeeklyReportResponse:
    """FN-AI-10 — 주간 보고서 생성을 **예약**한다. 응답은 즉시 나간다(§4.4).

    보고서 본문은 배경에서 만들어지고, 완성되면 `GET /reports/{id}` 로 받는다.
    동기로 만들면 요청이 LLM 왕복만큼 매달리고, 그동안 브라우저는 무엇이 되고 있는지
    알 수 없다.
    """
    service = _ai(request)
    from_ = datetime.combine(body.from_, time.min, tzinfo=UTC)
    to = datetime.combine(body.to, time.max, tzinfo=UTC)
    report_id = await service.start_weekly_report(from_, to)
    return WeeklyReportResponse(
        report_id=report_id,
        status="generating",
        estimated_sec=REPORT_ESTIMATED_SEC,
    )


@router.get(
    "/reports/{report_id}",
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def read_report(request: Request, report_id: str) -> dict[str, object]:
    """예약한 보고서를 받는다. 아직이면 `status = "generating"` 이다.

    §4.4 는 생성 요청만 정의하고 조회 경로를 적지 않았다. `report_id` 를 돌려주는
    이상 그것으로 받아올 자리가 필요하므로 같은 이름 공간에 둔다 —
    `docs/INDEX.md` 「명세서 확인 필요」에 올려 두었다.
    """
    service = _ai(request)
    report = service.report(report_id)
    if report is None:
        raise _not_found(f"보고서를 찾을 수 없습니다: {report_id}")
    return report


def _ai(request: Request) -> AiService:
    service: AiService | None = getattr(request.app.state, "ai", None)
    if service is None:
        raise _error("지능 기능이 연결되지 않았습니다")
    return service


def _events(request: Request) -> EventService:
    service: EventService | None = getattr(request.app.state, "event_service", None)
    if service is None:
        raise _error("이벤트 저장소가 연결되지 않았습니다")
    return service


def _error(message: str, reason: str | None = None) -> HTTPException:
    return _envelope(503, "NOT_FOUND", message, reason)


def _not_found(message: str) -> HTTPException:
    return _envelope(404, "NOT_FOUND", message, None)


def _envelope(status: int, code: str, message: str, reason: str | None) -> HTTPException:
    body = ErrorResponse(
        error=ErrorBody.model_validate(
            {"code": code, "message": message, "detail": {"reason": reason} if reason else None}
        )
    )
    return HTTPException(status_code=status, detail=body.model_dump(mode="json"))
