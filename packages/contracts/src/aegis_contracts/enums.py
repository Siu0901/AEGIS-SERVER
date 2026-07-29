"""열거형과 리터럴 타입 별칭.

출처: API명세서 §2 · §4, 기능명세서 §4.2 (상태 전이표)
"""

from enum import StrEnum
from typing import Literal

__all__ = [
    "AlertLevel",
    "AlertState",
    "AttachmentKind",
    "ChatRoute",
    "ClipExtractStatus",
    "ClipStatus",
    "ComponentState",
    "DistanceMethod",
    "DistributionBy",
    "EventStatus",
    "HelmetState",
    "MetricBucket",
    "MetricName",
    "NonCameraComponent",
    "ObjectClass",
    "Posture",
    "RepeatSubject",
    "SearchMode",
    "StreamKind",
    "StreamState",
    "SystemComponent",
    "TrackLostReason",
    "ViolationType",
    "ZoneAction",
]


class EventStatus(StrEnum):
    """이벤트 상태머신 값. 기능명세서 §4.2 상태 전이표.

    종결 상태는 셋이며 **뜻이 서로 다르다**:

    | 값 | 뜻 | 지표 |
    |---|---|---|
    | `resolved` | 위반 소멸이 지속되어 시정으로 인정 | 분모(창 안이면 분자도) |
    | `expired` | 경고까지 갔으나 추적이 끊겨 시정 여부를 못 봄 | 판정 불가 — 분모·분자 제외 |
    | `dropped` | **확정 전** 후보 단계에서 조건이 사라져 소멸 | 전량 제외 (진단용) |

    `dropped` 를 `expired` 로 합치지 않는다 — `expired` 는 "위반이었음이 확정된 뒤
    관측을 놓쳤다"는 뜻이라, 확정된 적도 없는 후보를 섞으면 판정 불가율이 오염된다.
    """

    CANDIDATE = "candidate"
    ACTIVE = "active"
    ALERTED = "alerted"
    RE_ALERTED = "re_alerted"
    LOST = "lost"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    DROPPED = "dropped"


class ViolationType(StrEnum):
    """위반 유형. API명세서 §2.2 · §4.1 · §5.2 의 `violation_type`.

    §5.1 `overlay.objects[].violations` 만 **배열**이다 — 한 트랙에 이벤트가 여럿
    걸릴 수 있어 화면이 합쳐 보여주기 때문이다. 후보·이벤트는 유형 하나에 1:1이다.
    """

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

#: 카메라 **스트림** 상태. API명세서 §2.4 `sub_state` · §4.6 `main_state`·`sub_state`
#: · §5.3 `component == "camera"` 인 경우의 `state`.
#:
#: 연결이 있거나, 재시도 중이거나, 끊김.
#:
#: `ComponentState` 와 **통합하지 않는다.** 스트림에는 "동작하나 성능 저하"라는 중간
#: 상태가 없고 대신 "재연결 중"이 있다(§4.6 「상태 값이 두 종류인 이유」).
StreamState = Literal["ok", "reconnecting", "down"]

#: 오버레이 박스의 경고 단계. API명세서 §5.1 `objects[].alert_state`.
#: `EventStatus` 중 **진행 중**인 값만 쓴다(종결 상태 `resolved`·`expired` 는 오지 않는다).
#:
#: **`candidate` 와 `null` 은 다르다.** `candidate` 는 위반 조건이 관측됐으나 아직
#: 확정 전이고, `null` 은 이 트랙에 진행 중 이벤트가 아예 없다는 뜻이다. 대시보드는
#: `candidate` 를 **위반 색(적색)으로 그리지 않는다** — 확정 전이므로 위반으로 단정할
#: 수 없다. 다만 확정 진행 중임은 구분 가능하게 표시한다(§5.1).
AlertState = Literal["candidate", "active", "alerted", "re_alerted", "lost"]

#: 위험 등급. API명세서 §3 `AlertCommand.level` · §5.2 `severity` — **같은 척도, 같은 값**.
#: 1=주의(부저 없음) / 2=경고 / 3=긴급(연속 부저). **`fall` 은 항상 3** 이다.
AlertLevel = Literal[1, 2, 3]

#: 상태 변화를 보고하는 구성요소. API명세서 §5.3 `system.component`.
SystemComponent = Literal["edge", "camera", "mcu", "cloud_api", "storage", "db"]

#: `camera` 를 뺀 구성요소. API명세서 §5.3
#:
#: 카메라만 따로 두는 이유: 카메라는 구성요소가 아니라 **스트림 두 개를 가진 대상**이라
#: `cam_id` · `stream` 이 함께 필요하고 상태 값 집합도 다르다.
NonCameraComponent = Literal["edge", "mcu", "cloud_api", "storage", "db"]

#: 어느 스트림인지. API명세서 §5.3 `system.stream`.
#: `main` = 1920×1080 라이브·녹화(서버 관측) / `sub` = 640×360 추론(엣지 관측).
StreamKind = Literal["main", "sub"]

#: 구성요소 상태. API명세서 §5.3 — **`component != "camera"` 인 경우**.
#: 정상 / 동작하나 성능·한도 저하 / 사용 불가.
ComponentState = Literal["ok", "degraded", "down"]

#: 구역 변경 종류. API명세서 §5.4 `zone_updated.action`.
ZoneAction = Literal["upsert", "delete"]

#: 시계열 지표 이름. API명세서 §4.2 `GET /metrics/timeseries`.
MetricName = Literal["violations", "correction_rate", "avg_resolution_sec", "undetermined_rate"]

#: 시계열 버킷 단위. API명세서 §4.2.
MetricBucket = Literal["hour", "day", "week"]

#: 분포 집계 축. API명세서 §4.2 `GET /metrics/distribution`.
DistributionBy = Literal["violation_type", "zone", "camera", "hour_of_day"]

#: 반복 위반 집계 대상. API명세서 §4.2 `GET /metrics/repeat`.
#: **작업자 개인 단위 누적은 하지 않는다** — `track` 은 세션 내 추적 번호일 뿐 신원이 아니다.
RepeatSubject = Literal["zone", "camera", "track"]

#: 챗봇 응답 첨부 종류. API명세서 §4.4.
AttachmentKind = Literal["clip", "image", "table", "event_ref"]

#: 예약 클립 추출 상태. 기능명세서 §4.2 · §6.
#: **서버가 보는 잡의 상태**다 — 예약됐는지, 파일이 준비됐는지, 실패했는지.
ClipStatus = Literal["pending", "ready", "failed"]

#: REC 구간 추출 결과. API명세서 §4.7 `POST /clips` 의 `status`.
#:
#: `ClipStatus` 와 **다른 축이다.** 이쪽은 요청 구간이 녹화에 얼마나 남아 있었는지를
#: 말한다 — 전부 있었는지(`ready`), 일부만이었는지(`partial`), 보존 기간이 지나
#: 하나도 없었는지(`not_found`). 두 열거형을 합치지 않는다.
ClipExtractStatus = Literal["ready", "partial", "not_found"]

#: 장면 검색 처리 경로. API명세서 §4.3.
SearchMode = Literal["sql", "vector", "hybrid"]

#: 챗봇 질의 라우팅 경로. API명세서 §4.4.
ChatRoute = Literal["sql", "vector", "vision"]
