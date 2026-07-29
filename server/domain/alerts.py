"""경고 발동 의도 — 상태머신이 "지금 경고를 내보내라"고 말하는 방법. FN-ALM-01 · 02

기능명세서 §4.3 · API명세서 §3

**I/O 가 없다**(CLAUDE.md 절대규칙 2). 여기 있는 것은 판단뿐이고, wav 를 틀고 MQTT 를
쏘는 것은 `server/app/alert_service.py` 다.

`AlertCommand`(§3)를 그대로 쓰지 않는 이유는 `duration_s` 때문이다. 그 값은 **경광등이
몇 초 동안 켜져 있을지**를 정하는 장치 쪽 운용값이지 상태 전이 규칙이 아니다. 상태머신이
그것까지 들고 있으면 「언제 경고하는가」와 「경광등을 몇 초 켜는가」가 한 곳에 섞인다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aegis_contracts import ViolationType
from aegis_contracts.enums import AlertLevel

__all__ = ["AlertIntent"]


@dataclass(frozen=True, slots=True)
class AlertIntent:
    """경고 한 번. 확정(`alerted`)과 재경고(`re_alerted`)에서 나온다."""

    event_id: str
    cam_id: int
    violation_type: ViolationType
    """재생할 음원을 고르는 키이자 §3 `AlertCommand.type`."""

    level: AlertLevel
    """§3 `AlertCommand.level` · §5.2 `severity` — **같은 척도, 같은 값**. `fall` 은 항상 3."""

    zone_id: str | None
    repeat: bool
    """재경고인가. ESP32 는 이 값으로 점멸 패턴을 달리해 상습 상황을 구분한다(§3)."""

    at: datetime
    """경고를 발동하기로 판정한 **관측 시각**. 서버 수신 시각이 아니다.

    확정 → 방송 1초 이내(FN-ALM-01)를 재는 기준점이 이 값이다.
    """
