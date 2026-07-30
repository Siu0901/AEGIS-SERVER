"""정책값 (API명세서 §4.5 · FN-CFG-04).

* `GET   /policies` — 임계값·타이머 전량
* `PATCH /policies` — 지정한 키만 갱신

값의 원본은 DB `policies` 테이블 하나이며, 코드에 임계값을 하드코딩하지 않는다
(CLAUDE.md 절대규칙 6). 프론트도 오버레이 지연 버퍼(`overlay_buffer_*`)를 여기서만 읽는다.

**★ 변경이 재시작 없이 반영되어야 한다.** M7 튜닝은 확정 3초 · 해소 10초 · 쿨다운 30초를
현장에서 돌려가며 맞추는 작업인데, 재시작해야 먹으면 그 반복이 불가능하다. 그래서 저장
직후 상태머신·경고 집행자·클립 예약에 **직접 밀어 넣는다** — 주기 갱신(`POLICY_REFRESH_SECONDS`)
을 기다리지 않는다.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request

from aegis_contracts import ErrorBody, ErrorResponse, Policies, PolicyPatch

__all__ = ["router"]

log = logging.getLogger("server.routes.policies")

router = APIRouter(tags=["policies"])


class PolicyStore(Protocol):
    async def load(self) -> Policies: ...

    async def patch(self, changes: dict[str, Any]) -> Policies: ...


@router.get("/policies", response_model=Policies, responses={503: {"model": ErrorResponse}})
async def get_policies(request: Request) -> Policies:
    store = _store(request)
    try:
        return await store.load()
    except OSError as exc:
        # 계약의 기본값으로 대신 답하지 않는다. 그 기본값은 **시드의 원천**이지
        # 런타임 값이 아니며, 현장에서 조정한 임계값과 다를 수 있다. 조용히 다른
        # 값으로 답하면 화면은 정상으로 보이는데 동작만 어긋난다.
        log.warning("정책값을 읽지 못했다: %s", exc)
        raise _unavailable(f"정책 저장소에 닿지 못했습니다: {exc}") from exc


@router.patch(
    "/policies",
    response_model=Policies,
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def patch_policies(request: Request, body: PolicyPatch) -> Policies:
    """FN-CFG-04 — 지정한 키만 갱신하고 **즉시 반영**한다.

    응답은 갱신 후의 정책 전량이다. 부분 응답을 주면 화면이 나머지 값을 옛 값으로
    들고 있게 되고, 그 상태에서 다음 저장이 옛 값을 되돌려 쓴다.
    """
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise _validation("갱신할 정책 키가 없습니다")

    store = _store(request)
    try:
        updated = await store.patch(changes)
    except OSError as exc:
        log.warning("정책값을 저장하지 못했다: %s", exc)
        raise _unavailable(f"정책 저장소에 닿지 못했습니다: {exc}") from exc

    summary = ", ".join(f"{key}={value}" for key, value in sorted(changes.items()))
    log.info("정책 변경 — %s", summary)
    _apply(request, updated)
    return updated


def _apply(request: Request, policies: Policies) -> None:
    """새 임계값을 돌고 있는 부품들에 밀어 넣는다(재시작 없이 · FN-CFG-04).

    상태머신·경고 집행자·클립 예약이 **같은 순간에 같은 값**을 쓰게 한다. 각자 DB 를
    다시 읽게 두면 읽는 시점이 갈려 한동안 서로 다른 임계값으로 판정한다.
    """
    state = request.app.state
    service = getattr(state, "event_service", None)
    if service is not None:
        service.machine.set_policies(policies)
    alerts = getattr(state, "alerts", None)
    if alerts is not None:
        alerts.set_policies(policies)
    clips = getattr(state, "clips", None)
    if clips is not None:
        clips.set_policies(policies)


def _store(request: Request) -> PolicyStore:
    store: PolicyStore | None = getattr(request.app.state, "policies", None)
    if store is None:
        raise _unavailable("정책 저장소가 연결되지 않았습니다")
    return store


def _error(code: str, message: str, status_code: int) -> HTTPException:
    body = ErrorResponse(
        error=ErrorBody.model_validate({"code": code, "message": message, "detail": None})
    )
    return HTTPException(status_code=status_code, detail=body.model_dump(mode="json"))


def _unavailable(message: str) -> HTTPException:
    return _error("NOT_FOUND", message, 503)


def _validation(message: str) -> HTTPException:
    return _error("VALIDATION_ERROR", message, 422)
