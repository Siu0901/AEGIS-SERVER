"""ESP32(경광등·부저)가 보고한 상태 — 순수 상태 보관소. FN-SYS-01 · FN-ALM-02

`aegis/device/status`(API명세서 §3)로 들어온 값을 들고 있다가 `GET /system/status`(§4.6)
의 `mcu` 절과 `/ws/dashboard` 의 `system`(§5.3)에 내어준다.

**I/O 가 없다**(CLAUDE.md 절대규칙 2). MQTT 구독은 `server/infra/mqtt/` 가 하고, 여기는
받은 사실만 기억한다. 시각은 인자로 받는다.

**소켓이 붙어 있다는 사실을 살아 있다는 뜻으로 쓰지 않는다.** MQTT 브로커에 서버가
연결돼 있어도 ESP32 는 전원이 나갔을 수 있다. 그래서 온라인 판정은 **마지막 상태
보고의 신선도**로 한다 — `EdgeRuntime` 이 하트비트에 하는 것과 같다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from aegis_contracts import ComponentSystemMsg, DeviceStatus, McuStatus
from aegis_contracts.enums import ComponentState

__all__ = ["DEFAULT_MCU_STALE_AFTER_S", "McuRuntime"]

#: 상태 보고가 이 시간 이상 끊기면 오프라인으로 본다.
#:
#: `sim/mcu_sim` 의 기본 발행 주기가 10초이므로 3회 연속 누락에 해당한다. 실물 ESP32 의
#: 주기가 달라지면 이 값도 함께 바꿔야 한다 — 그래서 서버 설정(`mcu_stale_after_s`)으로
#: 주입받고, 여기 있는 값은 그 기본값이다.
DEFAULT_MCU_STALE_AFTER_S = 30.0


@dataclass(slots=True)
class McuRuntime:
    """`aegis/device/status` 로 관측한 경고 장치의 현재 상태.

    장치가 여럿이면 마지막 보고가 이긴다. §4.6 `mcu` 절이 단수이므로 명세서가 상정한
    구성은 장치 하나다.
    """

    stale_after_s: float = DEFAULT_MCU_STALE_AFTER_S

    broker_connected: bool = False
    """MQTT 브로커에 서버가 붙어 있는가. **장치 생존과 다른 사실이다.**"""

    last_status: DeviceStatus | None = None
    last_seen_at: datetime | None = None

    publish_failed: int = 0
    """경고 발행에 실패한 누적 건수. 0이 아니면 경광등이 울리지 않았다는 뜻이다."""

    # ------------------------------------------------------------------
    # 관측
    # ------------------------------------------------------------------

    def apply_status(self, status: DeviceStatus, at: datetime) -> ComponentSystemMsg | None:
        """상태 보고 한 건. **변한 때만** `system` 을 돌려준다(§5.3).

        주기 보고를 그대로 방송하면 10초마다 같은 내용이 흘러 실제 변화가 묻힌다.
        """
        was = self.state(at)
        self.last_status = status
        self.last_seen_at = at
        now = self.state(at)
        if now == was:
            return None
        return ComponentSystemMsg(
            component="mcu",
            state=now,
            detail=f"{status.device} 상태 보고 (uptime {status.uptime_s}s)",
            at=at,
        )

    def broker(self, *, connected: bool, at: datetime, detail: str) -> ComponentSystemMsg | None:
        """브로커 연결이 붙거나 끊겼다.

        끊기면 장치 보고도 더 이상 오지 않으므로 마지막 값을 사실로 취급하지 않는다 —
        `last_status` 를 비워 `GET /system/status` 가 `online: false` 를 내게 한다.
        """
        if self.broker_connected == connected:
            return None
        self.broker_connected = connected
        if not connected:
            self.last_status = None
            self.last_seen_at = None
        return ComponentSystemMsg(
            component="mcu",
            state="ok" if connected else "down",
            detail=detail,
            at=at,
        )

    def publish_failure(self, at: datetime, reason: str) -> ComponentSystemMsg:
        """경고를 발행하지 못했다. **조용히 넘어가지 않는다**(CLAUDE.md 절대규칙 9).

        경광등이 울리지 않은 것은 방송이 나가지 않은 것과 같은 급의 사실이고, 소음이
        심한 구역에서는 이쪽이 유일한 경보다.
        """
        self.publish_failed += 1
        return ComponentSystemMsg(
            component="mcu",
            state="degraded",
            detail=f"경고 발행 실패 {self.publish_failed}건 (최근: {reason})",
            at=at,
        )

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    def state(self, at: datetime) -> ComponentState:
        if not self._fresh(at):
            return "down"
        return "degraded" if self.publish_failed else "ok"

    def status(self, at: datetime) -> McuStatus:
        """`GET /system/status` 의 `mcu` 절. API명세서 §4.6

        `last_seen` 은 **관측한 적이 없으면 `null`** 이다(§4.6 null 규약). 오래된 값을
        남겨두면 화면이 "한참 전에 살아 있었다"를 "지금 살아 있다"로 읽는다.
        """
        fresh = self._fresh(at)
        return McuStatus(online=fresh, last_seen=self.last_seen_at if fresh else None)

    def _fresh(self, at: datetime) -> bool:
        if self.last_seen_at is None:
            return False
        return at - self.last_seen_at <= timedelta(seconds=self.stale_after_s)
