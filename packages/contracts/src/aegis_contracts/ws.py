"""서버 → 대시보드 WebSocket `/ws/dashboard` 메시지.

출처: API명세서 §5

명세서가 전체 JSON을 제시한 것은 `event_updated` 하나뿐이고 나머지 다섯은
`type` 과 한 줄 설명만 주어져 있다. 여기서는 그 설명이 가리키는 기존 스키마를
그대로 재사용했으며(예: `metric` → `MetricsSummary`), 필드를 새로 창작하지 않았다.
각 모델의 docstring 에 근거를 적어 두었다.
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from ._base import SpecModel
from .edge import DetectedObject
from .enums import EventStatus
from .rest import EventSummary, MetricsSummary, SystemStatus

__all__ = [
    "AnomalyMsg",
    "DashboardMessage",
    "EventCreatedMsg",
    "EventUpdatedMsg",
    "MetricMsg",
    "OverlayMsg",
    "SystemMsg",
]


class OverlayMsg(SpecModel):
    """`overlay` — 엣지 `frame` 을 가공한 오버레이 좌표. API명세서 §5

    **원본 프레임 시각 `ts` 를 반드시 포함한다.** 클라이언트는 이 값을 키로
    지연 버퍼에 적재했다가 재생 중인 프레임 시각에 맞춰 렌더링한다(§5 오버레이 시간 정합).
    도착 즉시 그리면 박스가 사람보다 앞서 움직인다.

    `objects` 는 §5의 "엣지 `frame` 을 가공한" 이라는 정의에 따라 `frame.objects`
    와 동일한 구조를 사용한다.
    """

    type: Literal["overlay"] = "overlay"
    cam_id: int
    ts: AwareDatetime
    objects: list[DetectedObject]


class EventCreatedMsg(SpecModel):
    """`event_created` — 신규 확정 이벤트 요약. API명세서 §5

    "요약"은 `GET /events` 목록 항목(§4.1 `EventSummary`)과 같은 형태다.
    """

    type: Literal["event_created"] = "event_created"
    event: EventSummary


class EventUpdatedMsg(SpecModel):
    """`event_updated` — 상태 변경(경고·해소·재경고). API명세서 §5

    명세서 예시가 제시한 필드만 싣는다. 해소가 아닌 전이에서는
    `resolved_at` · `resolution_sec` 가 `null` 이다.
    """

    type: Literal["event_updated"] = "event_updated"
    event_id: str
    status: EventStatus
    resolved_at: AwareDatetime | None = None
    resolution_sec: int | None = None


class MetricMsg(SpecModel):
    """`metric` — 지표 갱신. API명세서 §5

    페이로드는 `GET /metrics/summary`(§4.2 `MetricsSummary`)와 동일하다.
    """

    type: Literal["metric"] = "metric"
    summary: MetricsSummary


class AnomalyMsg(SpecModel):
    """`anomaly` — 이상 탐지 플래그. API명세서 §5

    필드는 `anomalies` 테이블(기능명세서 §6)을 따른다.
    **이상 탐지는 경고 방송·경광등을 발동하지 않고 대시보드 '주의' 알림으로만 표시한다**(FN-AI-04).
    """

    type: Literal["anomaly"] = "anomaly"
    id: int
    cam_id: int
    score: float
    keyframe_path: str | None = None
    llm_note: str | None = None
    detected_at: AwareDatetime


class SystemMsg(SpecModel):
    """`system` — 구성요소 상태 변화. API명세서 §5

    페이로드는 `GET /system/status`(§4.6 `SystemStatus`)와 동일하다.
    """

    type: Literal["system"] = "system"
    status: SystemStatus


#: `/ws/dashboard` 로 내려가는 모든 메시지. `type` 값으로 구분되는 판별 유니온.
DashboardMessage = Annotated[
    OverlayMsg | EventCreatedMsg | EventUpdatedMsg | MetricMsg | AnomalyMsg | SystemMsg,
    Field(discriminator="type"),
]
