"""엣지가 보고한 상태 — 순수 상태 보관소. FN-SYS-01 · FN-SYS-06

`heartbeat`(API명세서 §2.4)로 들어온 값과 거부된 메시지 집계를 들고 있다가
`GET /system/status`(§4.6)와 `/ws/dashboard` 의 `system`(§5.3)에 내어준다.

**I/O 가 없다**(CLAUDE.md 절대규칙 2). 시각은 인자로 받고, 발행할 메시지는
만들어서 돌려줄 뿐 직접 보내지 않는다. 보내는 것은 `server/app/ws_edge.py` 다.

**관측한 적 없는 값을 0으로 채우지 않는다**(§4.6 null 규약). 하트비트가 오기
전이거나 끊긴 뒤에는 게이지가 전부 `null` 이고 `sub_state` 는 `"down"` 이다 —
`fps: 0.0` 은 "엣지가 도는데 처리량이 0"이라는 **다른 주장**이라 장애와 구분되지 않는다.
예외는 `msg_rejected_total` 하나다. 서버가 직접 세므로 관측 주체가 항상 있고 0에서 시작한다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aegis_contracts import (
    CameraStatus,
    CameraSystemMsg,
    ComponentSystemMsg,
    EdgeStatus,
    HeartbeatMsg,
)
from aegis_contracts.enums import ComponentState, StreamState

__all__ = ["DEFAULT_STALE_AFTER_S", "EdgeRuntime"]

#: 하트비트가 이 시간 이상 끊기면 보고값을 더 이상 사실로 취급하지 않는다.
#:
#: §2.4 가 5초 주기를 규정하므로 3회 연속 누락에 해당한다. 소켓이 붙어 있어도
#: 추론 루프가 멎으면 마지막 하트비트가 그대로 남아 **정상으로 보인다** — 그 상태가
#: 가장 위험하므로 시간으로 만료시킨다.
DEFAULT_STALE_AFTER_S = 15.0


@dataclass(slots=True)
class EdgeRuntime:
    """`/ws/edge` 로 관측한 엣지의 현재 상태.

    한 번에 엣지 하나만 붙는다고 본다(현장 노트북 1대 : 젯슨 1대). 여러 대가 붙으면
    마지막 하트비트가 이긴다 — 그 구성은 명세서에 없다.
    """

    stale_after_s: float = DEFAULT_STALE_AFTER_S

    connected: bool = False
    """`/ws/edge` 소켓이 붙어 있는가. 서버가 직접 아는 사실이다."""

    last_heartbeat: HeartbeatMsg | None = None
    last_heartbeat_at: datetime | None = None

    rejected: Counter[tuple[str, str]] = field(default_factory=Counter)
    """`edge_msg_rejected_total{type, reason}` — API명세서 §2.2 · FN-SYS-06."""

    # ------------------------------------------------------------------
    # 관측
    # ------------------------------------------------------------------

    def connect(self, at: datetime) -> ComponentSystemMsg:
        self.connected = True
        return ComponentSystemMsg(component="edge", state="ok", detail="엣지 연결됨", at=at)

    def disconnect(self, at: datetime) -> list[ComponentSystemMsg | CameraSystemMsg]:
        """끊기면 엣지와 **서브 스트림 전부**를 내린다.

        서브 스트림은 엣지만 관측한다(§5.3 `stream` 표). 엣지가 없으면 그 값을 계속
        들고 있을 근거가 사라지므로 마지막 값을 유지하지 않고 `down` 으로 내린다.
        """
        cams = sorted(self.camera_states())
        self.connected = False
        self.last_heartbeat = None
        self.last_heartbeat_at = None
        out: list[ComponentSystemMsg | CameraSystemMsg] = [
            ComponentSystemMsg(component="edge", state="down", detail="엣지 연결 종료", at=at)
        ]
        out += [
            CameraSystemMsg(
                cam_id=cam_id,
                stream="sub",
                state="down",
                detail="엣지 연결 종료 — 서브 스트림을 관측하는 주체가 없다",
                at=at,
            )
            for cam_id in cams
        ]
        return out

    def apply_heartbeat(
        self, message: HeartbeatMsg, at: datetime
    ) -> list[ComponentSystemMsg | CameraSystemMsg]:
        """하트비트를 반영하고 **변한 것만** `system` 으로 알린다(§5.3).

        매 하트비트를 그대로 방송하면 5초마다 같은 내용이 흘러 실제 변화가 묻힌다.
        """
        before = self.camera_states()
        was_fresh = self._fresh(at)

        self.last_heartbeat = message
        self.last_heartbeat_at = at

        out: list[ComponentSystemMsg | CameraSystemMsg] = []
        if not was_fresh:
            out.append(
                ComponentSystemMsg(
                    component="edge", state=self._state(), detail="하트비트 수신", at=at
                )
            )
        out += [
            CameraSystemMsg(
                cam_id=camera.cam_id,
                stream="sub",
                state=camera.sub_state,
                detail=f"엣지 처리 {camera.fps:.1f}fps",
                at=at,
            )
            for camera in message.cameras
            if before.get(camera.cam_id) != camera.sub_state
        ]
        return out

    def reject(self, kind: str, reason: str, at: datetime) -> ComponentSystemMsg:
        """스키마 검증에 실패한 메시지 한 건을 집계한다. FN-SYS-06

        **조용히 버리지 않는다.** 감지된 위반이 검증 단계에서 소리 없이 사라지는 것은
        오탐보다 위험하므로, 세는 동시에 대시보드에 상태 변화로 밀어 넣는다.
        """
        self.rejected[(kind, reason)] += 1
        return ComponentSystemMsg(
            component="edge",
            state="degraded",
            detail=f"엣지 메시지 거부 {self.msg_rejected_total}건 (최근: {kind}/{reason})",
            at=at,
        )

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    @property
    def msg_rejected_total(self) -> int:
        return sum(self.rejected.values())

    def camera_states(self) -> dict[int, StreamState]:
        if self.last_heartbeat is None:
            return {}
        return {camera.cam_id: camera.sub_state for camera in self.last_heartbeat.cameras}

    def status(self, at: datetime) -> EdgeStatus:
        """`GET /system/status` 의 `edge` 절. API명세서 §4.6"""
        fresh = self._fresh(at)
        beat = self.last_heartbeat if fresh else None
        return EdgeStatus(
            online=self.connected,
            gpu_util=beat.gpu_util if beat else None,
            cls_cache_hit_rate=beat.cls_cache_hit_rate if beat else None,
            depth_calls_per_min=beat.depth_calls_per_min if beat else None,
            msg_rejected_total=self.msg_rejected_total,
        )

    def camera(
        self,
        cam_id: int,
        at: datetime,
        *,
        main_state: StreamState,
        recording: bool | None,
    ) -> CameraStatus:
        """`GET /system/status` 의 `cameras[]` 한 줄. 메인은 서버가, 서브는 엣지가 본다."""
        beat = self.last_heartbeat if self._fresh(at) else None
        health = next((c for c in beat.cameras if c.cam_id == cam_id), None) if beat else None
        return CameraStatus(
            cam_id=cam_id,
            main_state=main_state,
            # 엣지가 없으면 `"down"` 이다 — `StreamState` 에 "모름"이 없고, 연결되지
            # 않은 것은 사실이다(§4.6 null 규약의 예외 두 가지 중 하나).
            sub_state=health.sub_state if health else "down",
            fps=health.fps if health else None,
            recording=recording,
        )

    def _fresh(self, at: datetime) -> bool:
        if self.last_heartbeat_at is None:
            return False
        return at - self.last_heartbeat_at <= timedelta(seconds=self.stale_after_s)

    def _state(self) -> ComponentState:
        # 한 건이라도 거부됐으면 정상이라고 말하지 않는다. 엣지 코드의 결함이므로
        # 저절로 낫지 않고, 연결이 새로 맺어질 때까지 그대로 남는다(§2.2).
        return "degraded" if self.rejected else "ok"
