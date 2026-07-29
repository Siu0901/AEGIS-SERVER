"""`GET /system/status` (API명세서 §4.6 · FN-SYS-01).

관측 주체가 절마다 다르다.

| 절 | 관측 주체 |
|---|---|
| `cameras[].main_state` | 서버 — mediamtx 폴링(`server/infra/stream`) |
| `cameras[].recording` · `storage` | REC — `GET /status`(§4.7)를 **그대로 전달**한다 |
| `edge` · `cameras[].sub_state` · `fps` | 엣지 — `heartbeat`(§2.4) (`edge_state.py`) |
| `edge.msg_rejected_total` | 서버가 직접 센다 (FN-SYS-06) |
| `mcu` | ESP32 — `aegis/device/status`(§3) (`server/domain/mcu_state.py`) |
| `cloud` | 클라우드 호출의 마지막 결과 (`server/domain/cloud_state.py` · FN-SYS-03) |

**관측한 적 없는 값을 그럴듯한 숫자로 채우지 않는다**(§4.6 null 규약). `fps: 0.0` 은
"엣지가 도는데 처리량이 0", `edge_offset_ms: 0` 은 "완벽히 동기화됨"이라는 **다른 주장**
이라 실제 장애와 구분되지 않는다. 예외는 서버가 직접 세는 `edge.msg_rejected_total`
(0 시작)과, "모름"이라는 값이 없는 `sub_state`(`"down"`)뿐이다.

**FN-SYS-03 — `cloud` 가 어떤 값이어도 안전 기능은 이 응답을 읽지 않는다.** 감지 →
확정 → 경고 → 시정 판정 어디에도 클라우드 호출이 없으므로, 여기 `available: false` 가
찍히는 것은 **분석 기능만 멈췄다는 표시**다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from aegis_contracts import (
    RecStatusResponse,
    StorageStatus,
    SystemStatus,
    TimeSyncStatus,
)
from aegis_vision.clock import Clock
from server.domain.cloud_state import CloudRuntime
from server.domain.edge_state import EdgeRuntime
from server.domain.mcu_state import McuRuntime
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

    edge: EdgeRuntime = state.edge
    mcu: McuRuntime = state.mcu
    cloud: CloudRuntime = state.cloud
    clock: Clock = state.clock
    now = clock.now()

    # REC 이 죽었으면 "녹화하지 않는다"가 아니라 "알 수 없다"다. 카메라별로 REC 이
    # 보고한 값만 싣고, 목록에 없는 카메라도 `null` 로 둔다.
    recording = {camera.cam_id: camera.recording for camera in rec.cameras} if rec else {}

    return SystemStatus(
        # FN-SYS-06 — `msg_rejected_total` 은 서버가 직접 세므로 여기만 0 으로 시작한다.
        edge=edge.status(now),
        cameras=[
            edge.camera(
                cam_id,
                now,
                main_state=main_states.get(cam_id, "down"),
                # REC 의 §4.7 값을 그대로 전달한다. 메인 스트림 상태로 추론하지 않는다 —
                # 라이브가 보이는 것과 녹화되는 것은 다른 프로세스의 일이다.
                recording=recording.get(cam_id),
            )
            for cam_id in sorted(main_states)
        ],
        # FN-ALM-02 · FN-SYS-01 — `aegis/device/status`(§3)의 신선도로 판정한다.
        # 브로커에 서버가 붙어 있다는 사실은 장치가 살아 있다는 뜻이 아니다.
        mcu=mcu.status(now),
        # FN-SYS-03 — 클라우드 호출의 마지막 결과. 아직 불러본 적이 없으면
        # `available: false` · `quota_used: null` 이다("쓸 수 있다"로 낙관하지 않는다).
        cloud=cloud.status(),
        storage=_storage(rec),
        # 엣지 시각 오프셋(FN-SYS-02)은 `heartbeat` 에 실리지 않는다(§2.4). 관측 수단이
        # 생기기 전까지 `null` 이다 — 0 은 "완벽히 동기화됨"이라는 다른 주장이다.
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
