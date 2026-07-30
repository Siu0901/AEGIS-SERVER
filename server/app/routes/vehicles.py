"""클래스별 위험 반경 (API명세서 §4.5 · FN-CFG-05).

* `GET   /vehicle-classes`
* `PATCH /vehicle-classes/{name}`

위험 반경은 **장비를 따라다니는 동적 영역**이고, 근접 임계값(`proximity_threshold_m`,
정책 키)은 **즉시 경고 기준**이다. 둘은 2단계로 동작하므로 저장 위치도 화면도 다르다(§4.5).
지게차 기본값은 3.0m 다(제조현장 실내 통행 기준).

**클래스를 새로 만들지 않는다.** 감지 클래스는 `person` · `vehicle` 2종 고정이고
(CLAUDE.md 절대규칙 11), 런타임에 추가하는 경로가 있으면 그 규칙이 무너진다.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request

from aegis_contracts import ErrorBody, ErrorResponse, VehicleClass, VehicleClassPatch

__all__ = ["router"]

log = logging.getLogger("server.routes.vehicles")

router = APIRouter(tags=["vehicle-classes"])


class VehicleClassStore(Protocol):
    async def list_vehicle_classes(self) -> list[VehicleClass]: ...

    async def patch(self, class_name: str, changes: dict[str, Any]) -> VehicleClass | None: ...


@router.get(
    "/vehicle-classes",
    response_model=list[VehicleClass],
    responses={503: {"model": ErrorResponse}},
)
async def list_vehicle_classes(request: Request) -> list[VehicleClass]:
    store = _store(request)
    try:
        return await store.list_vehicle_classes()
    except OSError as exc:
        log.warning("위험 반경을 읽지 못했다: %s", exc)
        raise _unavailable(f"차량 클래스 저장소에 닿지 못했습니다: {exc}") from exc


@router.patch(
    "/vehicle-classes/{class_name}",
    response_model=VehicleClass,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def patch_vehicle_class(
    request: Request,
    class_name: str,
    body: VehicleClassPatch,
) -> VehicleClass:
    """FN-CFG-05 — 위험 반경·사용 여부 조정.

    **반경은 양수여야 한다.** 0 이하를 허용하면 위험 영역이 사라지고, 그 사실은 화면
    어디에도 드러나지 않은 채 근접 판정만 조용히 멎는다.
    """
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise _validation("갱신할 필드가 없습니다 (danger_radius_m · active)")
    radius = changes.get("danger_radius_m")
    if radius is not None and radius <= 0:
        raise _validation(f"위험 반경은 0보다 커야 합니다: {radius}")

    store = _store(request)
    try:
        updated = await store.patch(class_name, changes)
    except OSError as exc:
        log.warning("위험 반경을 저장하지 못했다: %s", exc)
        raise _unavailable(f"차량 클래스 저장소에 닿지 못했습니다: {exc}") from exc
    if updated is None:
        raise _not_found(f"등록되지 않은 클래스입니다: {class_name}")

    log.info("위험 반경 변경 — %s %s", class_name, changes)
    return updated


def _store(request: Request) -> VehicleClassStore:
    store: VehicleClassStore | None = getattr(request.app.state, "vehicle_classes", None)
    if store is None:
        raise _unavailable("차량 클래스 저장소가 연결되지 않았습니다")
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


def _validation(message: str) -> HTTPException:
    return _error("VALIDATION_ERROR", message, 422)
