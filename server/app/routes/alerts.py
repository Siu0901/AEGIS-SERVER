"""수동 방송과 경고 일시중지 (API명세서 §4.5 · FN-ALM-04 · FN-ALM-05).

* `POST /alerts/manual` — 관리자가 고른 음원을 내보낸다 (`202` + `dispatched_at`)
* `POST /alerts/mute` — 정비 작업 등으로 자동 경고를 기한부로 멈춘다
* `GET  /alerts/mute` — 지금 멈춰 있는가, 언제 풀리는가

**204 로 두었던 것을 응답 본문으로 바꿨다.** §4.5 가 두 응답을 정의하면서
「일시중지가 언제 풀리는지 화면이 다시 물어볼 경로가 없다」는 문제가 해소됐다 —
조회 경로가 없으면 새로고침 한 번에 "경고가 꺼져 있다"는 사실이 화면에서 사라진다.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from aegis_contracts import (
    ErrorBody,
    ErrorResponse,
    ManualAlertRequest,
    ManualAlertResponse,
    MuteAlertRequest,
    MuteAlertResponse,
)
from server.app.alert_service import AlertService

__all__ = ["router"]

log = logging.getLogger("server.routes.alerts")

router = APIRouter(tags=["alerts"])


@router.post(
    "/alerts/manual",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ManualAlertResponse,
    responses={503: {"model": ErrorResponse}},
)
async def manual_alert(request: Request, body: ManualAlertRequest) -> ManualAlertResponse:
    """FN-ALM-04 — 수동 방송. 일시중지 중에도 나간다(사람이 지금 누른 것이다).

    `notify_device`(기본 참)면 요청의 `level` 로 §3 `aegis/alert` 도 발행한다.
    스피커만 울리고 경광등은 끄고 싶으면 거짓으로 준다(§4.5).
    """
    dispatched_at = await _service(request).manual(body)
    return ManualAlertResponse(dispatched_at=dispatched_at)


@router.post(
    "/alerts/mute",
    response_model=MuteAlertResponse,
    responses={503: {"model": ErrorResponse}},
)
async def mute_alert(request: Request, body: MuteAlertRequest) -> MuteAlertResponse:
    """FN-ALM-05 — 경고 일시중지. `minutes: 0` 은 즉시 해제다(§4.5).

    **기한이 반드시 붙는다.** `minutes` 를 생략하면 `mute_default_duration_s`
    (기본 900초)가 붙는다 — 무기한으로 끌 수 있으면 꺼둔 것을 잊는 순간 감시가
    조용히 멎고, 그것이 오탐보다 위험하다(CLAUDE.md 절대규칙 9).
    """
    response = await _service(request).mute(body)
    log.info(
        "일시중지 요청 처리 — cam=%s muted=%s (해제 %s)",
        body.cam_id,
        response.muted,
        response.muted_until.isoformat() if response.muted_until else "-",
    )
    return response


@router.get(
    "/alerts/mute",
    response_model=MuteAlertResponse,
    responses={503: {"model": ErrorResponse}},
)
async def mute_state(
    request: Request,
    cam_id: Annotated[int | None, Query(ge=1)] = None,
) -> MuteAlertResponse:
    """FN-ALM-05 — 지금 상태. `POST` 와 **같은 형태**를 돌려준다(§4.5).

    `cam_id` 를 주면 그 카메라에 **실제로 걸리는** 창을 본다 — 전체 대상 일시중지가
    켜져 있으면 카메라별 창이 없어도 조용하다. 생략하면 전체 대상 창의 상태다.
    """
    return _service(request).mute_status(cam_id)


def _service(request: Request) -> AlertService:
    service: AlertService | None = getattr(request.app.state, "alerts", None)
    if service is None:
        # 조립이 잘못된 것이다. 성공한 척하면 "방송했다"고 믿게 된다.
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
