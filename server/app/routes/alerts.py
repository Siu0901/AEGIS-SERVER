"""수동 방송과 경고 일시중지 (API명세서 §4.5 · FN-ALM-04 · FN-ALM-05).

* `POST /alerts/manual` — 관리자가 고른 음원을 내보낸다
* `POST /alerts/mute` — 정비 작업 등으로 그 카메라의 자동 경고를 기한부로 멈춘다

**응답 본문이 없다(204).** §4.5 는 두 요청 본문만 정의하고 응답 스키마를 두지 않았다.
없는 계약을 지어내면 `packages/contracts` 가 명세서와 1:1 이라는 규칙이 깨지므로,
성공을 상태 코드로만 알린다. 일시중지가 언제 풀리는지를 화면이 다시 물어볼 경로가
없다는 문제는 `docs/INDEX.md` 「명세서 확인 필요」에 올려 두었다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from aegis_contracts import ErrorBody, ErrorResponse, ManualAlertRequest, MuteAlertRequest
from server.app.alert_service import AlertService

__all__ = ["router"]

log = logging.getLogger("server.routes.alerts")

router = APIRouter(tags=["alerts"])


@router.post(
    "/alerts/manual",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={503: {"model": ErrorResponse}},
)
async def manual_alert(request: Request, body: ManualAlertRequest) -> Response:
    """FN-ALM-04 — 수동 방송. 일시중지 중에도 나간다(사람이 지금 누른 것이다)."""
    await _service(request).manual(body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/alerts/mute",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={503: {"model": ErrorResponse}},
)
async def mute_alert(request: Request, body: MuteAlertRequest) -> Response:
    """FN-ALM-05 — 경고 일시중지. `minutes` 를 0 이하로 주면 즉시 해제한다.

    **기한이 반드시 붙는다.** 무기한으로 끌 수 있으면 꺼둔 것을 잊는 순간 감시가
    조용히 멎는다 — 그것이 오탐보다 위험하다(CLAUDE.md 절대규칙 9).
    """
    window = await _service(request).mute(body)
    log.info(
        "일시중지 요청 처리 — cam=%s %d분 (해제 %s)",
        body.cam_id,
        body.minutes,
        window.until.isoformat(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _service(request: Request) -> AlertService:
    service: AlertService | None = getattr(request.app.state, "alerts", None)
    if service is None:
        # 조립이 잘못된 것이다. 204 로 성공한 척하면 "방송했다"고 믿게 된다.
        body = ErrorResponse(
            error=ErrorBody.model_validate(
                {
                    "code": "NOT_FOUND",
                    "message": "경고 집행자가 연결되지 않았습니다",
                    "detail": None,
                }
            )
        )
        raise HTTPException(status_code=503, detail=body.model_dump(mode="json"))
    return service
