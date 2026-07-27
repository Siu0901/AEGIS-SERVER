"""서버 ↔ ESP32 MQTT 페이로드.

출처: API명세서 §3
"""

from pydantic import AwareDatetime

from ._base import SpecModel
from .enums import AlertLevel, ViolationType

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
    type: ViolationType
    level: AlertLevel
    """§5.2 `event_created.severity` 와 **같은 척도이며 같은 값**을 쓴다."""
    zone_id: str | None = None
    duration_s: int
    repeat: bool


class DeviceStatus(SpecModel):
    """`aegis/device/status` 페이로드. API명세서 §3"""

    device: str
    online: bool
    uptime_s: int
    last_alert: AwareDatetime | None = None
