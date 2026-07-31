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
    CameraPatch,
    ErrorBody,
    ErrorResponse,
    RefHeight,
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
        ref_height: dict[str, Any] | None,
        calibrated_at: Any,
        calib_points: list[dict[str, Any]] | None = None,
        reproj_error_m: float | None = None,
    ) -> None: ...

    async def patch_camera(self, cam_id: int, changes: dict[str, Any]) -> dict[str, Any] | None: ...


class ZoneStore(Protocol):
    """캘리브레이션이 바뀌면 이 라우터가 구역의 지면 좌표를 다시 계산해 저장한다."""

    async def list_zones(self, cam_id: int | None = None) -> list[Zone]: ...

    async def upsert(self, zone: Zone) -> None: ...


def _camera(row: dict[str, Any]) -> CameraCalibration:
    """§6 `cameras` 한 행 → §4.5 응답.

    ★ `ref_height` 은 **객체 그대로** 나간다 — `{height_px, at_m}`(기능명세서 §6).
    예전에는 높이 하나만 냈는데, 그러면 설정 화면이 기준점을 다시 그릴 수 없고
    다른 거리의 기대 높이도 구할 수 없다(같은 사람도 멀수록 화면상 높이가 줄어든다).
    """
    reference = row.get("ref_height")
    return CameraCalibration(
        cam_id=int(row["cam_id"]),
        name=str(row["name"]),
        rtsp_main=str(row["rtsp_main"]),
        rtsp_sub=str(row["rtsp_sub"]),
        homography=row.get("homography"),
        calib_points=row.get("calib_points"),
        reproj_error_m=row.get("reproj_error_m"),
        ref_height=None if reference is None else RefHeight.model_validate(reference),
        calibrated_at=row.get("calibrated_at"),
    )


@router.get(
    "/cameras",
    response_model=list[CameraCalibration],
    responses={503: {"model": ErrorResponse}},
)
async def list_cameras(request: Request) -> list[CameraCalibration]:
    """카메라 설정과 저장된 캘리브레이션. API명세서 §4.5

    설정 화면이 **새로고침 뒤에도** 구역과 기준점을 다시 그리려면 이 경로가 필요하다.
    """
    store = _cameras(request)
    try:
        rows = await store.list_cameras()
    except OSError as exc:
        log.warning("카메라를 읽지 못했다: %s", exc)
        raise _unavailable(f"카메라 저장소에 닿지 못했습니다: {exc}") from exc
    return [_camera(row) for row in rows]


@router.patch(
    "/cameras/{cam_id}",
    response_model=CameraCalibration,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def patch_camera(request: Request, cam_id: int, body: CameraPatch) -> CameraCalibration:
    """카메라 표시 이름과 RTSP 주소를 고친다. API명세서 §4.5

    **캘리브레이션은 여기서 건드리지 않는다.** 행렬과 대응점이 따로 갱신될 수 있으면
    둘이 어긋난 카메라가 생기고, 그때 화면이 보여주는 기준점은 실제로 쓰인 점이 아니다.
    """
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise _validation("고칠 항목이 없습니다")
    store = _cameras(request)
    try:
        row = await store.patch_camera(cam_id, changes)
    except OSError as exc:
        log.warning("cam%d 를 수정하지 못했다: %s", cam_id, exc)
        raise _unavailable(f"카메라 저장소에 닿지 못했습니다: {exc}") from exc
    if row is None:
        raise _not_found(f"등록되지 않은 카메라입니다: {cam_id}")
    log.info("cam%d 설정 변경 — %s", cam_id, ", ".join(sorted(changes)))
    return _camera(row)


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

    # 요청은 `px_height`(§4.5), 저장은 `height_px`(기능명세서 §6). 이름이 다른 두 규약을
    # 경계에서 한 번만 바꾼다 — 안쪽으로 흘려보내면 어느 쪽 이름인지 매번 따져야 한다.
    reference = (
        RefHeight(
            height_px=body.reference_person.px_height, at_m=body.reference_person.at_m
        ).model_dump(mode="json")
        if body.reference_person
        else None
    )
    store = _cameras(request)
    try:
        await store.save_calibration(
            cam_id,
            homography.to_rows(),
            reference,
            _clock(request).now(),
            calib_points=[point.model_dump(mode="json") for point in body.points],
            reproj_error_m=round(error_m, 4),
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
    await _recompute_zones(request, cam_id, homography)
    return CalibrationResponse(
        homography=homography.to_rows(),
        reprojection_error_m=round(error_m, 4),
        ref_height_calibrated=reference is not None,
    )


async def _recompute_zones(request: Request, cam_id: int, homography: Homography) -> None:
    """★ 캘리브레이션이 갱신되면 **픽셀 폴리곤을 기준으로 `polygon_m` 을 다시 계산**한다.

    API명세서 §4.5 — 사용자가 화면에서 그린 위치가 원본이다. 미터를 그대로 두면 화면의
    도형과 판정에 쓰이는 도형이 서로 다른 좌표계에 놓이고, 그 어긋남은 **구역 판정이
    조용히 틀리는 형태로만** 드러난다.

    다시 계산한 뒤 §5.4 `zone_updated`(`upsert`)를 순차 발행한다 — 발행하지 않으면
    대시보드 캐시가 옛 좌표계로 그린 채 남는다.

    실패해도 요청을 실패로 만들지 않는다 — 캘리브레이션 저장은 이미 끝났고, 대시보드는
    `GET /zones` 로 따라잡을 수 있다.
    """
    zones: ZoneStore | None = getattr(request.app.state, "zones", None)
    hub = getattr(request.app.state, "hub", None)
    if zones is None:
        return
    try:
        items = await zones.list_zones(cam_id)
    except Exception:
        log.exception("cam%d 구역 목록을 읽지 못해 좌표를 다시 계산하지 못했다", cam_id)
        return

    recomputed = 0
    for zone in items:
        updated = zone
        if zone.polygon:
            polygon_m = [
                (round(x, 3), round(y, 3)) for x, y in homography.polygon_to_ground(zone.polygon)
            ]
            updated = zone.model_copy(update={"polygon_m": polygon_m})
            try:
                await zones.upsert(updated)
                recomputed += 1
            except Exception:
                log.exception("구역 %s 의 지면 좌표를 저장하지 못했다", zone.zone_id)
                continue
        else:
            # 픽셀 폴리곤이 없는 옛 구역이다(마이그레이션 0007 이전에 저장된 것).
            # 미터를 픽셀로 되돌려 다시 계산할 수는 있지만, 그것은 **옛 호모그래피가
            # 맞았다고 가정**하는 일이다. 지어내지 않고 그대로 두고 알린다.
            log.warning(
                "구역 %s 에 픽셀 폴리곤이 없어 지면 좌표를 다시 계산하지 못했다 — "
                "설정 화면에서 다시 그려야 한다",
                zone.zone_id,
            )
        if hub is not None:
            await hub.broadcast(
                ZoneUpdatedMsg(
                    cam_id=cam_id,
                    action="upsert",
                    zone=ZoneUpdatedPayload(
                        zone_id=updated.zone_id,
                        name=updated.name,
                        polygon_m=updated.polygon_m,
                        buffer_m=updated.buffer_m,
                        active=updated.active,
                    ),
                )
            )
    log.info(
        "cam%d 구역 %d건 중 %d건의 지면 좌표를 다시 계산하고 zone_updated 를 발행했다",
        cam_id,
        len(items),
        recomputed,
    )


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
