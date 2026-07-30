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

__all__ = ["MINIMUM_LEVEL", "AlertIntent", "LevelFloorError", "SoundEntry", "check_level"]

#: 위반 유형별 **위험 등급 하한**. API명세서 §3
#:
#: `fall` 만 있다. 쓰러짐은 대상자가 스스로 시정할 수 없는 유일한 유형이고, 등급을
#: 낮추면 긴급 상황에서 부저가 울리지 않는다. **안전 하한은 설정 대상이 아니다** —
#: 관리자가 다른 유형의 등급을 조정하는 것은 현장 판단이지만 이것은 아니다.
MINIMUM_LEVEL: dict[ViolationType, AlertLevel] = {ViolationType.FALL: 3}


class LevelFloorError(ValueError):
    """안전 하한보다 낮은 등급을 설정하려 했다. API 는 이것을 422 로 돌려준다(§4.5)."""


def check_level(violation_type: str, level: AlertLevel) -> None:
    """등급이 하한 이상인지. 미달이면 `LevelFloorError`.

    **순수 함수다.** 설정 API(FN-CFG-03)와 DB 읽기 경로가 같은 규칙을 쓰도록 여기 둔다 —
    한쪽에만 두면 다른 경로로 들어온 값이 규칙을 비켜 간다.
    """
    try:
        floor = MINIMUM_LEVEL.get(ViolationType(violation_type))
    except ValueError:
        # 수동 방송용 키(`custom_notice` 등)다. 위반 유형이 아니므로 하한이 없다.
        return
    if floor is not None and level < floor:
        msg = (
            f"{violation_type} 의 위험 등급은 {floor} 미만으로 설정할 수 없다"
            f"(요청 {level}). 쓰러짐은 대상자가 스스로 시정할 수 없어 "
            "등급을 낮추면 긴급 상황에서 부저가 울리지 않는다(API명세서 §3)"
        )
        raise LevelFloorError(msg)


@dataclass(frozen=True, slots=True)
class SoundEntry:
    """`alert_sounds` 한 행. 기능명세서 §6 · FN-CFG-03

    **위험 등급이 DB 에 있다는 것이 중요하다.** §6 이 "관리자가 설정 화면에서 유형별
    음원과 **등급**을 바꿀 수 있다(절대규칙 6)"고 적었으므로, 코드에 박힌 표가 아니라
    이 값이 §3 `AlertCommand.level` 과 §5.2 `severity` 의 원천이다. 상태머신은 이
    매핑을 **주입받아** 순수성을 지킨다(절대규칙 2) — DB 를 직접 읽지 않는다.
    """

    file_path: str
    """`assets/audio/` 기준 상대 경로. 루트를 벗어나는 값은 재생 단계에서 거부된다."""

    level: AlertLevel
    """`1` | `2` | `3`. `fall` 은 항상 3(§3)."""

    label: str | None
    """설정 화면 표시 이름. 미지정이면 `None` — `''`("빈 이름을 지정했다")와 다르다."""


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
