"""`GET /system/status` (API명세서 §4.6 · FN-SYS-01).

M1 에서 실제로 관측되는 값은 둘뿐이다.

* `cameras[].main_state` — mediamtx 폴링으로 서버가 직접 본다(`server/infra/stream`)
* `storage` — **REC 의 `GET /status`(§4.7)를 호출해 전달한다**

나머지(엣지·MCU·클라우드)는 해당 마일스톤에서 붙는다. 그때까지 **관측한 적 없는 값을
그럴듯한 숫자로 채우지 않는다.** `fps: 0.0` 은 "엣지가 도는데 처리량이 0"이라는 뜻이고
실제 장애와 구분되지 않으며, `edge_offset_ms: 0` 은 "완벽히 동기화됨"이라는 강한 주장이다.
둘 다 `null` 로 둔다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from aegis_contracts import (
    CameraStatus,
    CloudStatus,
    EdgeStatus,
    McuStatus,
    StorageStatus,
    SystemStatus,
    TimeSyncStatus,
)
from server.infra.rec_client import RecUnavailableError

__all__ = ["router"]

log = logging.getLogger("server.routes.system")

router = APIRouter(tags=["system"])


@router.get("/system/status", response_model=SystemStatus)
async def system_status(request: Request) -> SystemStatus:
    """구성요소 상태 스냅샷. 변화분만 필요하면 `/ws/dashboard` 의 `system` 을 쓴다(§5.3)."""
    state = request.app.state
    main_states = state.stream_watcher.states()

    return SystemStatus(
        edge=EdgeStatus(
            # 엣지는 M2(시뮬레이터) · M9(실물)에서 붙는다.
            online=False,
            gpu_util=0.0,
            cls_cache_hit_rate=0.0,
            depth_calls_per_min=0,
            # FN-SYS-06 — 거부된 엣지 메시지 누적. `/ws/edge` 가 생기면 실제로 올라간다.
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
            )
            for cam_id in sorted(main_states)
        ],
        mcu=McuStatus(online=False, last_seen=None),
        cloud=CloudStatus(available=False, quota_used=0.0),
        storage=await _storage(state),
        time_sync=TimeSyncStatus(edge_offset_ms=None),
    )


async def _storage(state: object) -> StorageStatus:
    """§4.7 REC 응답을 §4.6 `storage` 로 옮긴다.

    **서버 디스크를 조회하지 않는다.** 운용 시 녹화 디스크는 엣지 SSD 이고, 서버
    노트북의 여유 공간은 녹화와 아무 상관이 없다. 그 숫자를 여기 실으면 엣지 SSD 가
    가득 찼는데도 대시보드는 여유롭다고 표시한다.

    §4.6 의 `storage` 는 두 필드뿐이라 §4.7 의 다섯 값 중 그만큼만 옮긴다.
    """
    client = getattr(state, "rec_client", None)
    if client is None:
        return StorageStatus(retention_days=None, free_gb=None)
    try:
        rec = await client.status()
    except RecUnavailableError as exc:
        log.warning("REC 상태를 읽지 못해 storage 를 null 로 보고한다: %s", exc)
        return StorageStatus(retention_days=None, free_gb=None)
    return StorageStatus(
        retention_days=rec.storage.retention_days,
        free_gb=rec.storage.free_gb,
    )
