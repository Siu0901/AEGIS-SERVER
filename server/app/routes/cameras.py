"""카메라 캘리브레이션 (API명세서 §4.5 · FN-CFG-01).

* `GET  /cameras` — 카메라별 캘리브레이션 상태(호모그래피 포함)
* `POST /cameras/{cam_id}/calibration` — 실측 4점 → 호모그래피 산출·저장

**여기서 좌표계가 성립한다.** 이 행렬이 없으면 접지점은 픽셀에 머물고, 구역 판정도
거리 계산도 할 수 없다. 그래서 실패를 조용히 넘기지 않는다 — 점이 모자라거나 한 직선
위에 있으면 `422` 다(`aegis_vision.CalibrationError`).

**재투영 오차를 반드시 돌려준다**(§4.5 `reprojection_error_m`). 4점을 잘못 찍었는지
알 수 있는 유일한 수단이고, 그것을 모르면 이후의 모든 거리·구역 판정이 조용히 틀어진다.

**캘리브레이션이 바뀌면 지면 좌표계가 통째로 바뀐다.** 그 카메라의 모든 구역에 대해
`zone_updated`(§5.4)를 순차 발행해 대시보드 캐시를 갱신한다 — 폴리곤 자체는 그대로여도
화면에 그리는 위치가 달라진다.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request

from aegis_contracts import (
    CalibrationRequest,
    CalibrationResponse,
    CameraCalibration,
    ErrorBody,
    ErrorResponse,
    Zone,
    ZoneUpdatedMsg,
    ZoneUpdatedPayload,
)
from aegis_vision import CalibrationError, Homography
from aegis_vision.clock import Clock

__all__ = ["router"]

log = logging.getLogger("server.routes.cameras")

router = APIRouter(tags=["cameras"])


class CameraStore(Protocol):
    """`DbCameraRepository` 중 이 라우터가 쓰는 부분."""

    async def list_cameras(self) -> list[dict[str, Any]]: ...

    async def save_calibration(
        self,
        cam_id: int,
        homography: list[list[float]],
        ref_height_px_at_m: dict[str, Any] | None,
        calibrated_at: Any,
    ) -> None: ...


class ZoneLister(Protocol):
    async def list_zones(self, cam_id: int | None = None) -> list[Zone]: ...


@router.get(
    "/cameras",
    response_model=list[CameraCalibration],
    responses={503: {"model": ErrorResponse}},
)
async def list_cameras(request: Request) -> list[CameraCalibration]:
    """설정 화면이 저장된 구역을 영상 위에 다시 그리려면 호모그래피가 필요하다.

    ⚠ §4.5 에 이 조회 경로가 없다 — `docs/INDEX.md` 「명세서 확인 필요」 참조.
    """
    store = _cameras(request)
    try:
        rows = await store.list_cameras()
    except OSError as exc:
        log.warning("카메라를 읽지 못했다: %s", exc)
        raise _unavailable(f"카메라 저장소에 닿지 못했습니다: {exc}") from exc
    return [
        CameraCalibration(
            cam_id=int(row["cam_id"]),
            name=str(row["name"]),
            homography=row.get("homography"),
            ref_height_calibrated=row.get("ref_height_px_at_m") is not None,
            calibrated_at=row.get("calibrated_at"),
        )
        for row in rows
    ]


@router.post(
    "/cameras/{cam_id}/calibration",
    response_model=CalibrationResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def calibrate(
    request: Request,
    cam_id: int,
    body: CalibrationRequest,
) -> CalibrationResponse:
    """FN-CFG-01 — 화면 4점 + 실측값 → 호모그래피.

    계산은 `packages/vision` 이 한다(순수 로직). 여기서는 저장과 통지만 한다.
    """
    try:
        correspondences = [(point.px, point.m) for point in body.points]
        homography = Homography.from_correspondences(correspondences)
        error_m = homography.reprojection_error_m(correspondences)
    except CalibrationError as exc:
        # 조용히 단위행렬을 저장하지 않는다. 잘못된 캘리브레이션은 모든 거리·구역
        # 판정을 틀리게 만들면서 화면 어디에도 드러나지 않는다.
        log.warning("cam%d 캘리브레이션을 거부했다: %s", cam_id, exc)
        raise _validation(str(exc)) from exc

    reference = body.reference_person.model_dump(mode="json") if body.reference_person else None
    store = _cameras(request)
    try:
        await store.save_calibration(
            cam_id,
            homography.to_rows(),
            reference,
            _clock(request).now(),
        )
    except LookupError as exc:
        raise _not_found(str(exc)) from exc
    except OSError as exc:
        log.warning("cam%d 캘리브레이션을 저장하지 못했다: %s", cam_id, exc)
        raise _unavailable(f"카메라 저장소에 닿지 못했습니다: {exc}") from exc

    log.info(
        "cam%d 캘리브레이션 저장 — 대응점 %d개 · 재투영 오차 %.3f m%s",
        cam_id,
        len(body.points),
        error_m,
        " · 기준 신장 포함" if reference else "",
    )
    await _republish_zones(request, cam_id)
    return CalibrationResponse(
        homography=homography.to_rows(),
        reprojection_error_m=round(error_m, 4),
        ref_height_calibrated=reference is not None,
    )


async def _republish_zones(request: Request, cam_id: int) -> None:
    """§5.4 — 캘리브레이션이 바뀌면 그 카메라의 모든 구역에 `upsert` 를 순차 발행한다.

    폴리곤 값은 그대로지만 **지면 좌표계가 바뀌었으므로** 대시보드가 화면에 그리는
    위치가 달라진다. 발행하지 않으면 캐시가 옛 좌표계로 그린 채 남는다.

    실패해도 요청을 실패로 만들지 않는다 — 저장은 이미 끝났고, 대시보드는
    `GET /zones` 로 다시 받을 수 있다.
    """
    zones: ZoneLister | None = getattr(request.app.state, "zones", None)
    hub = getattr(request.app.state, "hub", None)
    if zones is None or hub is None:
        return
    try:
        items = await zones.list_zones(cam_id)
    except Exception:
        log.exception("cam%d 구역 목록을 읽지 못해 zone_updated 를 발행하지 못했다", cam_id)
        return
    for zone in items:
        await hub.broadcast(
            ZoneUpdatedMsg(
                cam_id=cam_id,
                action="upsert",
                zone=ZoneUpdatedPayload(
                    zone_id=zone.zone_id,
                    name=zone.name,
                    polygon_m=zone.polygon_m,
                    buffer_m=zone.buffer_m,
                    active=zone.active,
                ),
            )
        )
    log.info("cam%d 구역 %d건에 zone_updated 를 발행했다 (좌표계 변경)", cam_id, len(items))


def _cameras(request: Request) -> CameraStore:
    store: CameraStore | None = getattr(request.app.state, "cameras", None)
    if store is None:
        raise _unavailable("카메라 저장소가 연결되지 않았습니다")
    return store


def _clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


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
