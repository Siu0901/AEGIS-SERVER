"""경고 음원 매핑 (API명세서 §4.5 · FN-CFG-03).

* `GET /alert-sounds` — 유형별 음원·등급·표시 이름 전량
* `PUT /alert-sounds/{violation_type}` — `file_path` · `level` · `label` · `active` 갱신

**파일명과 등급이 코드에 없다**(CLAUDE.md 절대규칙 6). 그래서 설정 화면이 이 두
엔드포인트로만 매핑을 읽고 고친다. §6 이 `alert_sounds` 테이블을 정의하면서 등급까지
관리자가 바꾸는 값이 됐고, 그 값이 §3 `AlertCommand.level` 과 §5.2 `severity` 의 원천이다.

**`fall` 의 등급은 3 미만으로 내릴 수 없다**(§3 · §4.5). 쓰러짐은 대상자가 스스로
시정할 수 없는 유일한 유형이라, 등급을 낮추면 긴급 상황에서 부저가 울리지 않는다.
안전 하한은 설정 대상이 아니므로 `422` 로 거부한다.
"""

from __future__ import annotations

import logging
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request

from aegis_contracts import AlertSound, AlertSoundPatch, ErrorBody, ErrorResponse
from server.domain.alerts import LevelFloorError, check_level

__all__ = ["router"]

log = logging.getLogger("server.routes.sounds")

router = APIRouter(tags=["alert-sounds"])


class SoundStore(Protocol):
    """`DbSoundRepository` 중 이 라우터가 쓰는 부분."""

    async def list_sounds(self) -> list[AlertSound]: ...

    async def patch_sound(
        self, violation_type: str, changes: dict[str, object]
    ) -> AlertSound | None: ...


@router.get(
    "/alert-sounds",
    response_model=list[AlertSound],
    responses={503: {"model": ErrorResponse}},
)
async def list_alert_sounds(request: Request) -> list[AlertSound]:
    """FN-CFG-03 — **꺼진 항목도 함께** 돌려준다.

    꺼진 것을 감추면 설정 화면에서 다시 켤 방법이 없다.
    """
    store = _store(request)
    try:
        return await store.list_sounds()
    except OSError as exc:
        # 빈 배열로 답하지 않는다 — "등록된 음원이 없다"와 "DB 에 닿지 못했다"는 다른
        # 사실이고, 전자로 답하면 화면이 매핑을 지운 것처럼 보인다.
        log.warning("음원 매핑을 읽지 못했다: %s", exc)
        raise _unavailable(f"음원 저장소에 닿지 못했습니다: {exc}") from exc


@router.put(
    "/alert-sounds/{violation_type}",
    response_model=AlertSound,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def update_alert_sound(
    request: Request,
    violation_type: str,
    body: AlertSoundPatch,
) -> AlertSound:
    """FN-CFG-03 — 지정한 필드만 갱신한다.

    갱신은 **즉시 반영되지 않고 다음 새로고침 주기에 반영된다**(`SOUND_REFRESH_SECONDS`).
    경고 경로에 DB 왕복을 넣지 않기 위해서다 — 확정 → 방송 1초 예산(FN-ALM-01)에
    DB 지연이 끼어들면 안 된다. 그래서 여기서 저장한 뒤 캐시를 **직접 갱신해** 준다.
    """
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise _validation("갱신할 필드가 없습니다 (file_path · level · label · active)", 422)
    if (level := changes.get("level")) is not None:
        try:
            check_level(violation_type, level)
        except LevelFloorError as exc:
            raise _validation(str(exc), 422) from exc

    store = _store(request)
    try:
        updated = await store.patch_sound(violation_type, changes)
    except OSError as exc:
        log.warning("음원 매핑을 저장하지 못했다: %s", exc)
        raise _unavailable(f"음원 저장소에 닿지 못했습니다: {exc}") from exc
    if updated is None:
        raise _not_found(f"등록되지 않은 음원 키입니다: {violation_type}")

    log.info("음원 매핑 변경 — %s %s", violation_type, changes)
    await _refresh(request)
    return updated


async def _refresh(request: Request) -> None:
    """경고 집행자와 상태머신이 새 매핑·등급을 바로 쓰게 한다(FN-CFG-04 「재시작 없이」).

    주기 갱신만 믿으면 화면에서 등급을 바꾼 뒤 최대 60초 동안 옛 값으로 경고가 나간다.
    실패해도 요청을 실패로 만들지 않는다 — 저장은 이미 끝났고, 주기 갱신이 따라잡는다.
    """
    alerts = getattr(request.app.state, "alerts", None)
    if alerts is None:
        return
    try:
        await alerts.refresh_sounds()
    except Exception:
        log.exception("음원 매핑 즉시 반영에 실패했다 — 주기 갱신을 기다린다")
        return
    service = getattr(request.app.state, "event_service", None)
    if service is not None:
        service.machine.set_severity(alerts.severity_map())


def _store(request: Request) -> SoundStore:
    store: SoundStore | None = getattr(request.app.state, "sounds", None)
    if store is None:
        raise _unavailable("음원 저장소가 연결되지 않았습니다")
    return store


def _error(code: str, message: str, status_code: int) -> HTTPException:
    body = ErrorResponse(
        error=ErrorBody.model_validate({"code": code, "message": message, "detail": None})
    )
    return HTTPException(status_code=status_code, detail=body.model_dump(mode="json"))


def _unavailable(message: str) -> HTTPException:
    return _error("NOT_FOUND", message, 503)


def _not_found(message: str) -> HTTPException:
    return _error("NOT_FOUND", message, 404)


def _validation(message: str, status_code: int) -> HTTPException:
    return _error("VALIDATION_ERROR", message, status_code)
