"""`GET /system/status` (API명세서 §4.6 · FN-SYS-01).

M1 에서 실제로 관측되는 값은 둘뿐이다.

* `cameras[].main_state` — mediamtx 폴링으로 서버가 직접 본다(`server/infra/stream`)
* `cameras[].recording` 과 `storage` — **REC 의 `GET /status`(§4.7)를 그대로 전달한다**

나머지(엣지·MCU·클라우드)는 해당 마일스톤에서 붙는다. 그때까지 **관측한 적 없는 값을
그럴듯한 숫자로 채우지 않는다**(§4.6 null 규약). `fps: 0.0` 은 "엣지가 도는데 처리량이 0",
`edge_offset_ms: 0` 은 "완벽히 동기화됨"이라는 **다른 주장**이라 실제 장애와 구분되지 않는다.
전부 `null` 로 둔다. 예외는 서버가 직접 세는 `edge.msg_rejected_total`(0 시작)과,
"모름"이라는 값이 없는 `sub_state`(`"down"`)뿐이다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from aegis_contracts import (
    CameraStatus,
    CloudStatus,
    EdgeStatus,
    McuStatus,
    RecStatusResponse,
    StorageStatus,
    SystemStatus,
    TimeSyncStatus,
)
from server.infra.rec_client import RecUnavailableError, StorageReader

__all__ = ["router"]

log = logging.getLogger("server.routes.system")

router = APIRouter(tags=["system"])

#: REC 에 닿지 못했을 때의 `storage`. 다섯 필드가 전부 `null` 이다(§4.6).
_STORAGE_UNKNOWN = StorageStatus(
    total_gb=None,
    used_gb=None,
    free_gb=None,
    retention_days=None,
    oldest_segment_at=None,
)


@router.get("/system/status", response_model=SystemStatus)
async def system_status(request: Request) -> SystemStatus:
    """구성요소 상태 스냅샷. 변화분만 필요하면 `/ws/dashboard` 의 `system` 을 쓴다(§5.3)."""
    state = request.app.state
    main_states = state.stream_watcher.states()
    rec = await _rec_status(state)

    # REC 이 죽었으면 "녹화하지 않는다"가 아니라 "알 수 없다"다. 카메라별로 REC 이
    # 보고한 값만 싣고, 목록에 없는 카메라도 `null` 로 둔다.
    recording = {camera.cam_id: camera.recording for camera in rec.cameras} if rec else {}

    return SystemStatus(
        edge=EdgeStatus(
            # 엣지는 M2(시뮬레이터) · M9(실물)에서 붙는다. 게이지는 관측 주체가 없으므로 null.
            online=False,
            gpu_util=None,
            cls_cache_hit_rate=None,
            depth_calls_per_min=None,
            # FN-SYS-06 — 거부된 엣지 메시지 누적. 서버가 직접 세므로 여기만 0 으로 시작한다.
            msg_rejected_total=0,
        ),
        cameras=[
            CameraStatus(
                cam_id=cam_id,
                main_state=main_states.get(cam_id, "down"),
                # 서브는 엣지가 관측해 `heartbeat` 로 전한다(§2.4). 엣지가 없으니 down.
                sub_state="down",
                # 엣지의 실제 처리 fps. 관측 주체가 없으므로 null.
                fps=None,
                # REC 의 §4.7 값을 그대로 전달한다. 메인 스트림 상태로 추론하지 않는다 —
                # 라이브가 보이는 것과 녹화되는 것은 다른 프로세스의 일이다.
                recording=recording.get(cam_id),
            )
            for cam_id in sorted(main_states)
        ],
        mcu=McuStatus(online=False, last_seen=None),
        cloud=CloudStatus(available=False, quota_used=None),
        storage=_storage(rec),
        time_sync=TimeSyncStatus(edge_offset_ms=None),
    )


async def _rec_status(state: object) -> RecStatusResponse | None:
    """REC 의 `GET /status`(§4.7). 닿지 못하면 `None`.

    한 응답에서 `storage` 와 카메라별 `recording` 을 **함께** 꺼낸다. 두 번 부르면
    같은 화면 안에서 "녹화 중인데 저장소는 응답 없음" 같은 어긋난 조합이 나온다.
    """
    client: StorageReader | None = getattr(state, "rec_client", None)
    if client is None:
        return None
    try:
        return await client.status()
    except RecUnavailableError as exc:
        log.warning("REC 상태를 읽지 못해 storage·recording 을 null 로 보고한다: %s", exc)
        return None


def _storage(rec: RecStatusResponse | None) -> StorageStatus:
    """§4.7 `storage` 절을 §4.6 으로 **가공 없이** 옮긴다. 같은 5필드다.

    **서버 디스크를 조회하지 않는다.** 운용 시 녹화 디스크는 엣지 SSD 이고, 서버
    노트북의 여유 공간은 녹화와 아무 상관이 없다. 그 숫자를 여기 실으면 엣지 SSD 가
    가득 찼는데도 대시보드는 여유롭다고 표시한다.
    """
    if rec is None:
        return _STORAGE_UNKNOWN
    return StorageStatus(**rec.storage.model_dump())
