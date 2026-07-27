"""열거형과 리터럴 타입 별칭.

출처: API명세서 §2 · §4, 기능명세서 §4.2 (상태 전이표)
"""

from enum import StrEnum
from typing import Literal

__all__ = [
    "AlertState",
    "CameraState",
    "ChatRoute",
    "ClipStatus",
    "DistanceMethod",
    "EventStatus",
    "HelmetState",
    "ObjectClass",
    "Posture",
    "SearchMode",
    "TrackLostReason",
    "ViolationType",
]


class EventStatus(StrEnum):
    """이벤트 상태머신 값. 기능명세서 §4.2 상태 전이표."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    ALERTED = "alerted"
    RE_ALERTED = "re_alerted"
    LOST = "lost"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class ViolationType(StrEnum):
    """위반 유형. API명세서 §2.2 `violations[]` · §4.1 `violation_type`."""

    NO_HELMET = "no_helmet"
    ZONE_INTRUSION = "zone_intrusion"
    PROXIMITY = "proximity"
    FALL = "fall"


#: 1단계 감지 클래스. API명세서 §1.3 — 2종 고정, 런타임 추가 불가.
ObjectClass = Literal["person", "vehicle"]

#: 2단계 분류 결과. API명세서 §6.3 — `unknown` 클래스는 존재하지 않는다.
HelmetState = Literal["on", "off"]

#: 자세 판정 결과. API명세서 §6.4.
Posture = Literal["standing", "fallen", "unknown"]

#: 사람↔지게차 거리 산출 방식. API명세서 §6.5.
DistanceMethod = Literal["bbox_center", "mask_nearest"]

#: 트랙 소실 사유(진단용). API명세서 §2.3.
TrackLostReason = Literal["occluded", "out_of_view", "low_conf"]

#: 카메라 스트림 상태. API명세서 §4.6 `GET /system/status`.
CameraState = Literal["ok", "reconnecting", "down"]

#: 오버레이 박스의 경고 단계. API명세서 §5.1 `objects[].alert_state`.
#: `EventStatus` 중 **진행 중**인 값만 쓴다(종결 상태 `resolved`·`expired` 는 오지 않는다).
AlertState = Literal["active", "alerted", "re_alerted", "lost"]

#: 예약 클립 추출 상태. 기능명세서 §4.2 · §6.
ClipStatus = Literal["pending", "ready", "failed"]

#: 장면 검색 처리 경로. API명세서 §4.3.
SearchMode = Literal["sql", "vector", "hybrid"]

#: 챗봇 질의 라우팅 경로. API명세서 §4.4.
ChatRoute = Literal["sql", "vector", "vision"]
