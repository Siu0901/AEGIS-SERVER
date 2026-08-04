"""서버 연동 — REST 로 설정을 받고 `/ws/edge` 로 메시지를 올린다.

**엣지가 자기 파일에 적지 않는 것들이 있다.** 호모그래피·구역·정책·위험반경은 현장에서
화면으로 바뀌는 값이라 서버가 원천이다(§4.5). 캘리브레이션을 다시 하면 엣지도 새
행렬을 받아야 하므로, 주기적으로 다시 읽는다.

**메시지는 반드시 `aegis_contracts` 로 만든다.** dict 를 손으로 조립하지 않는다 —
서버가 스키마 검증에 실패한 메시지를 버리면 감지된 위반이 소리 없이 사라진다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx2
import websockets

from aegis_contracts import Policies
from aegis_contracts.edge import EdgeMessage
from aegis_contracts.rest import CameraCalibration, VehicleClass, Zone
from aegis_vision import CalibrationError, Homography, ReferenceHeight, ZoneShape

__all__ = ["CameraSetup", "EdgeSocket", "fetch_setup"]

log = logging.getLogger(__name__)

#: 설정 조회 타임아웃. 서버가 죽어 있어도 엣지가 멈추지 않아야 한다.
_TIMEOUT_S = 5.0


@dataclass(slots=True)
class CameraSetup:
    """카메라 한 대가 판정에 쓰는 서버측 설정.

    **호모그래피가 없으면 이 카메라는 돌 수 없다.** 거리도 구역도 지면 좌표가 있어야
    나오므로, 없으면 프레임을 흘려보내지 않고 설정 화면에서 캘리브레이션하라고 로그를
    남긴다 — 좌표 없이 박스만 올리면 화면에는 뭔가 도는 것처럼 보인다.
    """

    homography: Homography | None = None
    reference: ReferenceHeight | None = None
    zones: tuple[ZoneShape, ...] = ()
    zone_ids: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.homography is not None


@dataclass(slots=True)
class Setup:
    """서버에서 받은 설정 한 벌."""

    policies: Policies
    cameras: dict[int, CameraSetup] = field(default_factory=dict)
    danger_radius_m: dict[str, float] = field(default_factory=dict)

    def danger_for(self, class_name: str, fallback: float) -> float:
        return self.danger_radius_m.get(class_name, fallback)


async def fetch_setup(rest_url: str) -> Setup:
    """정책 · 카메라(호모그래피) · 구역 · 위험반경을 한 번에 읽는다.

    **실패를 기본값으로 덮지 않는다.** 서버에 닿지 못하면 예외를 올려 부르는 쪽이
    재시도하게 한다 — 조용히 계약 기본값으로 돌면 현장에서 조정한 임계값이 무시된
    채로 판정이 돌고, 그 사실이 어디에도 드러나지 않는다(절대규칙 9).
    """
    base = rest_url.rstrip("/")
    async with httpx2.AsyncClient(timeout=_TIMEOUT_S) as client:
        policies_raw, cameras_raw, zones_raw, classes_raw = [
            (await client.get(f"{base}/{path}")).raise_for_status().json()
            for path in ("policies", "cameras", "zones", "vehicle-classes")
        ]

    policies = Policies.model_validate(policies_raw)
    setup = Setup(policies=policies)

    for item in cameras_raw:
        camera = CameraCalibration.model_validate(item)
        setup.cameras[camera.cam_id] = _camera_setup(camera)

    for item in zones_raw:
        zone = Zone.model_validate(item)
        if not zone.active:
            continue
        target = setup.cameras.setdefault(zone.cam_id, CameraSetup())
        target.zones = (
            *target.zones,
            ZoneShape(
                zone_id=zone.zone_id,
                polygon_m=tuple(zone.polygon_m),
                buffer_m=zone.buffer_m,
            ),
        )

    for item in classes_raw:
        vehicle = VehicleClass.model_validate(item)
        if vehicle.active:
            setup.danger_radius_m[vehicle.class_name] = vehicle.danger_radius_m

    return setup


def _camera_setup(camera: CameraCalibration) -> CameraSetup:
    if camera.homography is None:
        log.warning(
            "cam%d 에 캘리브레이션이 없다 — 설정 화면에서 4점을 찍어야 거리·구역이 나온다",
            camera.cam_id,
        )
        return CameraSetup()
    try:
        homography = Homography.from_matrix(camera.homography)
    except CalibrationError:
        log.exception("cam%d 의 호모그래피를 쓸 수 없다", camera.cam_id)
        return CameraSetup()

    reference = None
    if camera.ref_height is not None:
        reference = ReferenceHeight(
            px_height=camera.ref_height.height_px,
            at_m=(camera.ref_height.at_m[0], camera.ref_height.at_m[1]),
        )
    else:
        log.warning(
            "cam%d 에 기준 인물이 없다 — 쓰러짐 판정(FN-DET-10)이 돌지 않는다",
            camera.cam_id,
        )
    return CameraSetup(homography=homography, reference=reference)


class EdgeSocket:
    """`/ws/edge` 송신. 끊기면 다시 연결한다.

    **보내지 못한 메시지를 쌓아 두지 않는다.** 좌표는 그 순간의 사실이라 나중에
    보내면 오버레이가 과거를 그린다. 끊긴 동안의 것은 버리고, 버린 수를 로그에 남긴다.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._socket: websockets.ClientConnection | None = None
        self._dropped = 0

    async def connect(self) -> None:
        self._socket = await websockets.connect(self._url)
        log.info("서버 연결 — %s", self._url)

    async def close(self) -> None:
        if self._socket is not None:
            await self._socket.close()
            self._socket = None

    @property
    def dropped(self) -> int:
        return self._dropped

    async def send(self, message: EdgeMessage) -> bool:
        """메시지 하나. 보냈으면 `True`.

        `exclude_unset` 로 **설정하지 않은 필드는 싣지 않는다** — `helmet` 게이트
        미통과 시 「필드 자체를 생략」하는 규약(§6.3)이 이 방식으로 표현된다.
        """
        if self._socket is None:
            self._dropped += 1
            return False
        payload = message.model_dump_json(by_alias=True, exclude_unset=True)
        try:
            await self._socket.send(payload)
        except websockets.WebSocketException:
            log.warning("송신 실패 — 연결이 끊겼다")
            self._socket = None
            self._dropped += 1
            return False
        return True
