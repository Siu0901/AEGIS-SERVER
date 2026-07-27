"""서버 → 대시보드 WebSocket `/ws/dashboard` 메시지.

출처: API명세서 §5 · §5.1 · §5.2 · §5.3

**구조 규약** — 모든 메시지는 평면(flat)이다. `type` 과 나머지 필드가 같은 깊이에 온다.
중첩은 배열 원소(`objects[]`, `nearby[]`)에만 허용한다.

**경로 규약** — 클라이언트로 내려가는 모든 파일 참조는 URL(`*_url`)이다.
서버 파일시스템 경로(`clip_path` · `keyframe_paths`)를 그대로 실어보내지 않는다.
"""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from ._base import Bbox, PointM, PointPx, SpecModel
from .enums import (
    AlertLevel,
    AlertState,
    ClipStatus,
    ComponentState,
    EventStatus,
    HelmetState,
    NonCameraComponent,
    Posture,
    StreamKind,
    StreamState,
    ViolationType,
    ZoneAction,
)

__all__ = [
    "AnomalyMsg",
    "CameraSystemMsg",
    "ComponentSystemMsg",
    "DashboardMessage",
    "EventCreatedMsg",
    "EventUpdatedMsg",
    "MetricMsg",
    "OverlayMsg",
    "OverlayNearby",
    "OverlayObject",
    "OverlayPerson",
    "OverlayVehicle",
    "SystemMsg",
    "ZoneUpdatedMsg",
    "ZoneUpdatedPayload",
]


# --------------------------------------------------------------------------
# §5.1 overlay
# --------------------------------------------------------------------------


class OverlayNearby(SpecModel):
    """`overlay.objects[].nearby[]` — 거리선을 그리기 위한 상대 차량. API명세서 §5.1

    `candidate.nearby[]`(§2.2)와 다른 모델이다. 저쪽은 판정 근거(`method` ·
    `depth_verified`)를 담고, 이쪽은 **화면에 선을 긋는 데 필요한 것만** 담는다.
    """

    class_: Literal["vehicle"] = Field(alias="class")
    track_id: int
    dist_m: float
    """사람↔차량 지면 거리. **거리선 라벨(예: `3.2 m`)의 원천**."""
    anchor: PointPx
    """상대 차량의 **정규화** 접지 좌표. 거리선의 반대편 끝점."""
    in_danger_zone: bool
    """위험 반경 이내 여부."""


class OverlayPerson(SpecModel):
    """`overlay.objects[]` 의 person. API명세서 §5.1

    좌표·자세·분류 필드는 §2.1 과 같은 의미·규약을 따른다. 다만 `frame` 과 달리
    **서버가 이벤트 상태를 합쳐서** 내려보낸다 — 클라이언트가 위반 여부를 스스로
    추론하지 않게 하기 위함이다(FN-UI-02 표시 규칙).
    """

    class_: Literal["person"] = Field(alias="class")
    track_id: int
    bbox: Bbox
    foot_point: PointPx
    posture: Posture

    in_zone: str | None
    """구역 밖이면 `null`. 필드 자체는 항상 실린다(§2.1 규약)."""

    helmet: HelmetState | None = None
    """게이트 미통과 · 캐시 없음이면 생략된다(§2.1 규약)."""

    violations: list[ViolationType]
    """현재 이 트랙에 걸려 있는 위반 유형. 없으면 빈 배열. **박스 색을 결정한다.**"""
    event_ids: list[str]
    """대응하는 진행 중 이벤트 ID. 클릭 시 상세로 이동."""
    alert_state: AlertState | None
    """경고 단계. 없으면 `null`. 필드 자체는 항상 실린다."""
    nearby: list[OverlayNearby]


class OverlayVehicle(SpecModel):
    """`overlay.objects[]` 의 vehicle(지게차). API명세서 §5.1"""

    class_: Literal["vehicle"] = Field(alias="class")
    track_id: int
    bbox: Bbox
    anchor: PointPx
    """**정규화** 접지 좌표. `frame` 의 `anchor_m`(미터)과 다르다."""
    moving: bool
    danger_radius_m: float

    violations: list[ViolationType]
    event_ids: list[str]
    alert_state: AlertState | None
    nearby: list[OverlayNearby]


#: `overlay.objects[]` 원소. `class` 값으로 구분되는 판별 유니온.
OverlayObject = Annotated[
    OverlayPerson | OverlayVehicle,
    Field(discriminator="class_"),
]


class OverlayMsg(SpecModel):
    """`overlay` — 이벤트 상태로 보강된 오버레이 데이터. API명세서 §5.1

    **금지구역 폴리곤은 이 메시지에 싣지 않는다.** 매 프레임 변하지 않으므로
    `GET /zones` 로 한 번 조회해 캐시한다.
    """

    type: Literal["overlay"] = "overlay"
    cam_id: int
    ts: AwareDatetime
    """**원본 프레임 시각.** 시간 정합의 기준이며 반드시 포함한다.
    도착 즉시 그리지 않고 이 값을 키로 지연 버퍼에 담았다가 재생 시각에 맞춰 그린다."""
    objects: list[OverlayObject]


# --------------------------------------------------------------------------
# §5.2 event_created / event_updated
# --------------------------------------------------------------------------


class EventCreatedMsg(SpecModel):
    """`event_created` — 신규 확정 이벤트. API명세서 §5.2"""

    type: Literal["event_created"] = "event_created"
    event_id: str
    cam_id: int
    violation_type: ViolationType
    """위반 유형 필드 이름은 REST(§4.1)와 동일하게 `violation_type` 을 쓴다."""
    track_id: int
    zone_id: str | None
    status: EventStatus
    confirmed_at: AwareDatetime
    alerted_at: AwareDatetime | None
    severity: AlertLevel
    """§3 `AlertCommand.level` 과 동일한 척도이며 같은 값을 쓴다."""
    keyframe_url: str


class EventUpdatedMsg(SpecModel):
    """`event_updated` — 상태 변경(경고·해소·재경고·소실·종결). API명세서 §5.2

    **변경된 필드만 싣는다.** `event_id` 와 `status` 는 항상 포함하고, 나머지는
    전이 종류에 따라 동반된다(§5.2 전이별 동반 필드).

    | 전이 | 함께 싣는 필드 |
    |---|---|
    | → `alerted` | `alerted_at` · `alert_count` · `severity` |
    | → `re_alerted` | `alerted_at`(최근) · `alert_count` |
    | → `lost` | `lost_at` |
    | `lost` → 복귀 | `track_id`(갱신된 값) · `reassoc_count` |
    | → `resolved` | `resolved_at` · `resolution_sec` |
    | → `expired` | `expired_at` |
    | 클립 준비 완료 | `clip_status` · `clip_url` |
    | 수동 정정 | `is_false_positive` · `note` |
    """

    type: Literal["event_updated"] = "event_updated"
    event_id: str
    status: EventStatus

    alerted_at: AwareDatetime | None = None
    alert_count: int | None = None
    severity: AlertLevel | None = None

    lost_at: AwareDatetime | None = None

    track_id: int | None = None
    reassoc_count: int | None = None

    resolved_at: AwareDatetime | None = None
    resolution_sec: int | None = None

    expired_at: AwareDatetime | None = None

    clip_status: ClipStatus | None = None
    clip_url: str | None = None

    is_false_positive: bool | None = None
    note: str | None = None


# --------------------------------------------------------------------------
# §5.3 metric / anomaly / system
# --------------------------------------------------------------------------


class MetricMsg(SpecModel):
    """`metric` — 지표 갱신. API명세서 §5.3

    `GET /metrics/summary`(§4.2)의 **부분집합**이다 — `fall_events` 와
    `anomaly_flags` 는 §5.3 페이로드에 없다.

    `correction_rate` 와 `undetermined_rate` 는 화면에서 **항상 병기**한다.
    """

    type: Literal["metric"] = "metric"
    period: str
    correction_rate: float
    undetermined_rate: float
    total_violations: int
    resolved: int
    unresolved: int
    undetermined: int
    avg_resolution_sec: int
    fall_events: int
    """쓰러짐은 자력 시정이 불가능하므로 시정률에서 빼고 별도로 센다."""
    anomaly_flags: int


class AnomalyMsg(SpecModel):
    """`anomaly` — 이상 탐지 플래그. API명세서 §5.3

    **경고 방송·경광등을 발동하지 않는다.** 대시보드 '주의' 알림으로만 표시한다(FN-AI-04).
    """

    type: Literal["anomaly"] = "anomaly"
    anomaly_id: int
    cam_id: int
    score: float
    detected_at: AwareDatetime
    note: str | None
    """무엇이 평소와 다른지에 대한 LLM 설명. 클라우드 미가용 시 `null`(FN-SYS-03)."""
    keyframe_url: str | None


class CameraSystemMsg(SpecModel):
    """`system` — 카메라 **스트림** 상태 변화. API명세서 §5.3

    카메라는 구성요소가 아니라 **스트림 두 개**(메인 1080p / 서브 640×360)를 가진
    대상이다. 둘은 독립적으로 끊기므로 어느 쪽이 바뀌었는지를 `stream` 으로 지정한다.

    이 메시지를 받으면 대시보드는 캐시된 `GET /system/status` 의 해당 카메라
    `main_state` 또는 `sub_state` 를 갱신한다.
    """

    type: Literal["system"] = "system"
    component: Literal["camera"] = "camera"
    cam_id: int
    stream: StreamKind
    state: StreamState
    """스트림에는 "동작하나 성능 저하"가 없고 대신 "재연결 중"이 있다."""
    detail: str
    at: AwareDatetime


class ComponentSystemMsg(SpecModel):
    """`system` — 카메라 외 구성요소 상태 변화. API명세서 §5.3

    `cam_id` · `stream` 을 싣지 않는다 — 스트림이 아니라 구성요소이기 때문이다.
    """

    type: Literal["system"] = "system"
    component: NonCameraComponent
    state: ComponentState
    detail: str
    at: AwareDatetime


#: `system` — 구성요소 상태 변화. API명세서 §5.3
#:
#: **변화한 구성요소 하나만** 보낸다. 전체 스냅샷이 필요하면 `GET /system/status` 를 쓴다.
#:
#: `component` 로 판별되는 유니온이다. 두 열거형을 합집합으로 열어두지 않는다 —
#: `camera` 는 `StreamState`, 나머지는 `ComponentState` 로 각각 좁혀진다.
SystemMsg = Annotated[
    CameraSystemMsg | ComponentSystemMsg,
    Field(discriminator="component"),
]


# --------------------------------------------------------------------------
# §5.4 zone_updated
# --------------------------------------------------------------------------


class ZoneUpdatedPayload(SpecModel):
    """`zone_updated.zone` — 구역 리소스. API명세서 §5.4

    `GET /zones` 응답 원소와 같은 형태이며, 클라이언트가 캐시를 그대로 갱신할 수
    있게 하기 위한 것이다. 다만 `cam_id` 는 메시지 최상위에 있으므로 여기엔 없다.

    | `action` | 필요한 필드 |
    |---|---|
    | `upsert` | `zone_id` · `name` · `polygon_m` · `buffer_m` · `active` 전부 |
    | `delete` | `zone_id` 만 |
    """

    zone_id: str
    name: str | None = None
    polygon_m: list[PointM] | None = None
    buffer_m: float | None = None
    active: bool | None = None


class ZoneUpdatedMsg(SpecModel):
    """`zone_updated` — 금지구역 변경 통지. API명세서 §5.4

    구역 폴리곤은 매 프레임 변하지 않으므로 `overlay` 에 싣지 않는다(§5.1).
    대시보드는 `GET /zones` 로 한 번 조회해 캐시하고 이 메시지로 갱신한다.

    캘리브레이션(호모그래피)이 바뀌면 지면 좌표계 자체가 바뀌므로, 해당 카메라의
    **모든 구역에 대해 `upsert` 를 순차 발행**한다.
    """

    type: Literal["zone_updated"] = "zone_updated"
    cam_id: int
    action: ZoneAction
    zone: ZoneUpdatedPayload

    @model_validator(mode="after")
    def _upsert_carries_full_zone(self) -> Self:
        """폴리곤 없는 `upsert` 는 대시보드 캐시를 손상시키므로 수신 측에서 거부한다(§5.4)."""
        if self.action != "upsert":
            return self
        missing = [
            name
            for name in ("name", "polygon_m", "buffer_m", "active")
            if getattr(self.zone, name) is None
        ]
        if missing:
            msg = f"action='upsert' 면 zone 에 {', '.join(missing)} 가 있어야 한다"
            raise ValueError(msg)
        return self


#: `/ws/dashboard` 로 내려가는 모든 메시지. `type` 값으로 구분되는 판별 유니온.
DashboardMessage = Annotated[
    OverlayMsg
    | EventCreatedMsg
    | EventUpdatedMsg
    | MetricMsg
    | AnomalyMsg
    | SystemMsg
    | ZoneUpdatedMsg,
    Field(discriminator="type"),
]
