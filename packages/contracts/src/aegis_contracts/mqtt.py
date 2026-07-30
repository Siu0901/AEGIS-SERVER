"""서버 ↔ ESP32 MQTT 페이로드.

출처: API명세서 §3
"""

from pydantic import AwareDatetime

from ._base import SpecModel
from .enums import AlertCommandType, AlertLevel

__all__ = ["ALERT_TOPIC", "DEVICE_STATUS_TOPIC", "AlertCommand", "DeviceStatus"]

#: 서버 발행 → ESP32 구독.
ALERT_TOPIC = "aegis/alert"

#: ESP32 발행 → 서버 구독.
DEVICE_STATUS_TOPIC = "aegis/device/status"


class AlertCommand(SpecModel):
    """`aegis/alert` 페이로드. API명세서 §3

    `level` 은 1=주의(부저 없음) / 2=경고 / 3=긴급(연속 부저)이며
    **`fall` 은 항상 3** 이다.
    """

    event_id: str
    """자동 경고는 `EV-YYYYMMDD-NNNN`, 수동 방송은 `MANUAL-cam{N}-{ISO8601}` 다(§3).
    후자는 **조회 가능한 이벤트가 아니다**."""
    type: AlertCommandType
    """점멸 패턴 선택자. 위반 유형 넷 + 수동 방송의 `manual`(§3)."""
    level: AlertLevel
    """§5.2 `event_created.severity` 와 **같은 척도이며 같은 값**을 쓴다."""
    zone_id: str | None = None
    duration_s: int
    """경광등·부저 지속 시간. 정책 키 `alert_duration_s`(기본 5)에서 읽는다(§3)."""
    repeat: bool


class DeviceStatus(SpecModel):
    """`aegis/device/status` 페이로드. API명세서 §3"""

    device: str
    online: bool
    uptime_s: int
    last_alert: AwareDatetime | None = None
