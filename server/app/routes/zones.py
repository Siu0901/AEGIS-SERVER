"""금지구역 (API명세서 §4.5 · FN-CFG-02).

* `GET    /zones` — 오버레이가 캐시할 폴리곤 목록
* `POST   /zones` — 화면에서 그린 폴리곤을 지면 좌표로 변환해 저장
* `DELETE /zones/{zone_id}` — 삭제

금지구역 폴리곤은 매 프레임 변하지 않으므로 `overlay` 에 싣지 않는다(§5.1). 대시보드가
여기서 한 번 받아 캐시하고 `zone_updated`(§5.4)로 갱신한다. 그래서 **쓰기 경로는 반드시
`zone_updated` 를 발행해야 한다** — 발행하지 않으면 화면은 새로고침 전까지 옛 폴리곤을
그린다.

**픽셀 → 미터 변환은 서버가 한다**(§4.5). 호모그래피를 푸는 코드가 `packages/vision`
한 곳에만 있어야 하고, 프론트가 변환하면 같은 계산이 TypeScript 로 한 벌 더 생긴다.
"""

from __future__ import annotations

import logging
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request, status

from aegis_contracts import (
    ErrorBody,
    ErrorResponse,
    Zone,
    ZoneUpdatedMsg,
    ZoneUpdatedPayload,
    ZoneUpsertRequest,
)
from aegis_vision import CalibrationError, Homography

__all__ = ["router"]

log = logging.getLogger("server.routes.zones")

router = APIRouter(tags=["zones"])

#: 폴리곤 최소 꼭짓점 수. 두 점은 선분이지 구역이 아니다.
_MIN_VERTICES = 3


class ZoneStore(Protocol):
    async def list_zones(self, cam_id: int | None = None) -> list[Zone]: ...

    async def upsert(self, zone: Zone) -> None: ...

    async def delete(self, zone_id: str) -> bool: ...


class CameraReader(Protocol):
    async def get_homography(self, cam_id: int) -> list[list[float]] | None: ...


@router.get("/zones", response_model=list[Zone], responses={503: {"model": ErrorResponse}})
async def list_zones(request: Request, cam_id: int | None = None) -> list[Zone]:
    store = _zones(request)
    try:
        return await store.list_zones(cam_id)
    except OSError as exc:
        # 빈 배열로 답하지 않는다 — "구역이 없다"와 "DB 에 닿지 못했다"는 다른 사실이고,
        # 전자로 답하면 대시보드가 금지구역을 지운 채로 그린다.
        log.warning("구역을 읽지 못했다: %s", exc)
        raise _unavailable(f"구역 저장소에 닿지 못했습니다: {exc}") from exc


@router.post(
    "/zones",
    response_model=Zone,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def upsert_zone(request: Request, body: ZoneUpsertRequest) -> Zone:
    """FN-CFG-02 — 구역 저장. 같은 `zone_id` 면 덮어쓴다.

    폴리곤은 화면 픽셀(`polygon`)이나 지면 미터(`polygon_m`) 중 하나로 온다. 픽셀로
    오면 **그 카메라의 호모그래피로 서버가 변환한다** — 캘리브레이션이 없으면 변환할
    수 없으므로 `422` 로 거부하고, 그 사실이 화면에 그대로 드러나야 한다.
    """
    polygon_m = await _resolve_polygon(request, body)
    zone = Zone(
        zone_id=body.zone_id,
        cam_id=body.cam_id,
        name=body.name,
        polygon_m=polygon_m,
        buffer_m=body.buffer_m,
        active=body.active,
    )
    store = _zones(request)
    try:
        await store.upsert(zone)
    except OSError as exc:
        log.warning("구역을 저장하지 못했다: %s", exc)
        raise _unavailable(f"구역 저장소에 닿지 못했습니다: {exc}") from exc

    log.info(
        "구역 저장 — %s (cam%d · 꼭짓점 %d · buffer %.2fm · %s)",
        zone.zone_id,
        zone.cam_id,
        len(zone.polygon_m),
        zone.buffer_m,
        "사용" if zone.active else "사용 안 함",
    )
    await _publish(
        request,
        ZoneUpdatedMsg(
            cam_id=zone.cam_id,
            action="upsert",
            zone=ZoneUpdatedPayload(
                zone_id=zone.zone_id,
                name=zone.name,
                polygon_m=zone.polygon_m,
                buffer_m=zone.buffer_m,
                active=zone.active,
            ),
        ),
    )
    return zone


@router.delete(
    "/zones/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def delete_zone(request: Request, zone_id: str, cam_id: int) -> None:
    """FN-CFG-02 — 구역 삭제. `cam_id` 는 §5.4 `zone_updated` 최상위에 필요하다.

    삭제된 구역을 알리지 않으면 대시보드가 없는 구역을 계속 그리고, 그 안에 사람이
    들어가도 아무 일이 없는 화면이 된다.
    """
    store = _zones(request)
    try:
        removed = await store.delete(zone_id)
    except OSError as exc:
        log.warning("구역을 삭제하지 못했다: %s", exc)
        raise _unavailable(f"구역 저장소에 닿지 못했습니다: {exc}") from exc
    if not removed:
        raise _not_found(f"존재하지 않는 구역입니다: {zone_id}")
    log.info("구역 삭제 — %s (cam%d)", zone_id, cam_id)
    await _publish(
        request,
        ZoneUpdatedMsg(
            cam_id=cam_id,
            action="delete",
            zone=ZoneUpdatedPayload(zone_id=zone_id),
        ),
    )


async def _resolve_polygon(request: Request, body: ZoneUpsertRequest) -> list[tuple[float, float]]:
    """요청의 폴리곤을 지면 좌표로 만든다. 픽셀로 왔으면 여기서 변환한다."""
    if (body.polygon is None) == (body.polygon_m is None):
        raise _validation("polygon(픽셀) 과 polygon_m(미터) 중 정확히 하나만 보내야 합니다")

    if body.polygon is None:
        # 위 검사가 "둘 중 하나"를 보장하므로 여기서는 `polygon_m` 이 반드시 있다.
        polygon_m = [(float(x), float(y)) for x, y in body.polygon_m or []]
    else:
        matrix = await _homography(request, body.cam_id)
        try:
            homography = Homography.from_matrix(matrix)
            polygon_m = [
                (round(x, 3), round(y, 3))
                for x, y in homography.polygon_to_ground(
                    [(float(x), float(y)) for x, y in body.polygon]
                )
            ]
        except CalibrationError as exc:
            raise _validation(f"폴리곤을 지면 좌표로 바꾸지 못했습니다: {exc}") from exc

    if len(polygon_m) < _MIN_VERTICES:
        raise _validation(
            f"구역 꼭짓점이 {len(polygon_m)}개입니다 — {_MIN_VERTICES}개 이상 필요합니다"
        )
    return polygon_m


async def _homography(request: Request, cam_id: int) -> list[list[float]]:
    cameras: CameraReader | None = getattr(request.app.state, "cameras", None)
    if cameras is None:
        raise _unavailable("카메라 저장소가 연결되지 않았습니다")
    try:
        matrix = await cameras.get_homography(cam_id)
    except OSError as exc:
        raise _unavailable(f"카메라 저장소에 닿지 못했습니다: {exc}") from exc
    if matrix is None:
        # 캘리브레이션 없이 그린 폴리곤은 미터로 바꿀 방법이 없다. 픽셀 값을 미터인
        # 척 저장하면 구역 판정이 통째로 틀리면서 아무도 그 사실을 모른다.
        raise _validation(
            f"cam{cam_id} 의 캘리브레이션이 없습니다 — 먼저 4점 캘리브레이션을 하세요(FN-CFG-01)"
        )
    return matrix


async def _publish(request: Request, message: ZoneUpdatedMsg) -> None:
    hub = getattr(request.app.state, "hub", None)
    if hub is None:
        return
    try:
        await hub.broadcast(message)
    except Exception:
        # 저장은 이미 끝났다. 통지 실패로 요청을 실패시키면 화면은 저장이 안 된 줄 안다.
        log.exception("zone_updated 발행에 실패했다 — 대시보드는 GET /zones 로 따라잡는다")


def _zones(request: Request) -> ZoneStore:
    store: ZoneStore | None = getattr(request.app.state, "zones", None)
    if store is None:
        raise _unavailable("구역 저장소가 연결되지 않았습니다")
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
