"""REST API 요청·응답 모델.

출처: API명세서 §1.4 (오류) · §4 (전 절)

Base URL: `http://<server-host>:8000/api/v1`
"""

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field

from ._base import Homography, PointM, PointPx, SpecModel
from .enums import (
    ChatRoute,
    DistributionBy,
    EventStatus,
    MetricBucket,
    MetricName,
    Posture,
    RepeatSubject,
    SearchMode,
    StreamState,
    ViolationType,
)

__all__ = [
    "BriefingRequest",
    "BriefingResponse",
    "CalibrationPoint",
    "CalibrationRequest",
    "CalibrationResponse",
    "CameraStatus",
    "ChatAttachment",
    "ChatRequest",
    "ChatResponse",
    "ChatSource",
    "ClipAttachment",
    "CloudStatus",
    "DistributionBucket",
    "EdgeStatus",
    "ErrorBody",
    "ErrorCode",
    "ErrorResponse",
    "EventDetail",
    "EventListQuery",
    "EventListResponse",
    "EventPatchRequest",
    "EventRefAttachment",
    "EventSummary",
    "ImageAttachment",
    "ManualAlertRequest",
    "McuStatus",
    "MetricsDistributionQuery",
    "MetricsDistributionResponse",
    "MetricsRepeatQuery",
    "MetricsRepeatResponse",
    "MetricsSummary",
    "MetricsTimeseriesQuery",
    "MetricsTimeseriesResponse",
    "MuteAlertRequest",
    "NearbySnapshot",
    "ReferencePerson",
    "RegulationRef",
    "RepeatItem",
    "SceneSearchFilters",
    "SceneSearchItem",
    "SceneSearchRequest",
    "SceneSearchResponse",
    "SimilarIncident",
    "StorageStatus",
    "SystemStatus",
    "TableAttachment",
    "TimeSyncStatus",
    "TimelineEntry",
    "TimeseriesPoint",
    "VehicleClass",
    "VehicleClassPatch",
    "WeeklyReportRequest",
    "WeeklyReportResponse",
    "Zone",
]

# --------------------------------------------------------------------------
# §1.4 오류 응답
# --------------------------------------------------------------------------

#: API명세서 §1.4 오류 코드표.
ErrorCode = Literal[
    "VALIDATION_ERROR",
    "NOT_FOUND",
    "EDGE_OFFLINE",
    "CLOUD_UNAVAILABLE",
    "QUOTA_EXCEEDED",
]


class ErrorBody(SpecModel):
    """오류 본문. API명세서 §1.4"""

    code: ErrorCode
    message: str
    detail: dict[str, Any] | None = None


class ErrorResponse(SpecModel):
    """오류 응답 봉투. API명세서 §1.4"""

    error: ErrorBody


# --------------------------------------------------------------------------
# §4.1 이벤트
# --------------------------------------------------------------------------


class EventListQuery(SpecModel):
    """`GET /events` 쿼리 파라미터. API명세서 §4.1"""

    from_: AwareDatetime | None = Field(default=None, alias="from")
    to: AwareDatetime | None = None
    cam_id: int | None = None
    type: ViolationType | None = None
    status: EventStatus | None = None
    zone_id: str | None = None
    limit: int | None = None
    cursor: str | None = None


class EventSummary(SpecModel):
    """`GET /events` 목록 항목. API명세서 §4.1"""

    event_id: str
    cam_id: int
    track_id: int
    violation_type: ViolationType
    zone_id: str | None
    status: EventStatus
    detected_at: AwareDatetime
    """최초 후보 관측 시각."""
    confirmed_at: AwareDatetime | None
    """확정 시각. 확정 전이면 `null`."""
    alerted_at: AwareDatetime | None
    """경고 발동 시각."""
    resolved_at: AwareDatetime | None
    resolution_sec: int | None
    """`alerted_at` → `resolved_at` 소요 초. **시정률 지표의 원천**."""
    alert_count: int
    min_distance_m: float | None
    posture: Posture | None
    repeat_count_7d: int
    """동일 트랙·구역의 최근 7일 유사 이벤트 수."""
    thumbnail_url: str | None


class NearbySnapshot(SpecModel):
    """확정 시점의 주변 지게차 상태 스냅샷. API명세서 §4.1

    `candidate.nearby[]`(§2.2)와 달리 `method` 필드가 없다 — 명세서 예시 그대로다.
    """

    class_: Literal["vehicle"] = Field(alias="class")
    track_id: int
    dist_m: float
    depth_verified: bool
    moving: bool
    within_danger_radius: bool


class RegulationRef(SpecModel):
    """사전 매핑 테이블로 연결된 규정 조항(LLM 생성 아님). API명세서 §4.1 · FN-AI-06"""

    code: str
    title: str


class SimilarIncident(SpecModel):
    """임베딩 유사도로 매칭된 과거 사고사례. API명세서 §4.1 · FN-AI-07"""

    title: str
    source: str
    similarity: float


class TimelineEntry(SpecModel):
    """이벤트 상태 전이 타임라인 항목. API명세서 §4.1"""

    at: AwareDatetime
    state: EventStatus


class EventDetail(EventSummary):
    """`GET /events/{event_id}`. 목록 필드에 아래가 추가된다. API명세서 §4.1"""

    clip_url: str | None
    keyframe_urls: list[str] = Field(default_factory=list)
    helmet_conf: float | None
    stillness_s: float | None
    height_ratio: float | None
    depth_verified: bool | None
    nearby_snapshot: list[NearbySnapshot] = Field(default_factory=list)
    llm_analysis: str | None
    """클라우드 분석 결과. 미생성 시 `null`(실시간 기능과 무관)."""
    regulation_refs: list[RegulationRef] = Field(default_factory=list)
    similar_incidents: list[SimilarIncident] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)


class EventPatchRequest(SpecModel):
    """`PATCH /events/{event_id}`. API명세서 §4.1

    `force_resolve` 는 시스템이 놓친 시정을 수동 종결한다.
    **`fall` 이벤트는 관리자 확인으로 종결하는 것이 기본 절차다.**
    """

    is_false_positive: bool | None = None
    note: str | None = None
    force_resolve: bool | None = None


class EventListResponse(SpecModel):
    """`GET /events` 응답. API명세서 §4.1"""

    items: list[EventSummary]
    next_cursor: str | None = None


# --------------------------------------------------------------------------
# §4.2 지표
# --------------------------------------------------------------------------


class MetricsSummary(SpecModel):
    """`GET /metrics/summary`. API명세서 §4.2 · §6.7

    `correction_rate` 와 `undetermined_rate` 는 **항상 병기**한다.
    `expired` 는 시정률 분모·분자 모두에서 제외되고 `undetermined` 로 따로 집계된다.
    """

    period: str
    correction_rate: float
    undetermined_rate: float
    total_violations: int
    resolved: int
    unresolved: int
    undetermined: int
    avg_resolution_sec: int
    fall_events: int
    anomaly_flags: int


class MetricsTimeseriesQuery(SpecModel):
    """`GET /metrics/timeseries` 쿼리 파라미터. API명세서 §4.2"""

    metric: MetricName
    bucket: MetricBucket
    from_: AwareDatetime | None = Field(default=None, alias="from")
    to: AwareDatetime | None = None


class TimeseriesPoint(SpecModel):
    """`GET /metrics/timeseries` 의 한 점. API명세서 §4.2"""

    t: str
    """버킷 시작 시각. 표기는 `bucket` 에 따라 다르다(`day` → `2026-08-12`)."""
    value: float
    """지표값. 비율 지표는 0~1, 건수 지표는 정수."""
    n: int
    """해당 버킷의 모집단 크기.

    **표본이 작을 때 비율을 신뢰하지 않기 위해** 함께 제공한다. 시정률 3건 중 3건이
    100%로 보이는 것을 막는 값이므로 화면에서 함께 노출한다.
    """


class MetricsTimeseriesResponse(SpecModel):
    """`GET /metrics/timeseries` 응답. API명세서 §4.2"""

    metric: MetricName
    bucket: MetricBucket
    points: list[TimeseriesPoint]


class MetricsDistributionQuery(SpecModel):
    """`GET /metrics/distribution` 쿼리 파라미터. API명세서 §4.2"""

    by: DistributionBy
    from_: AwareDatetime | None = Field(default=None, alias="from")
    to: AwareDatetime | None = None


class DistributionBucket(SpecModel):
    """`GET /metrics/distribution` 의 한 구간. API명세서 §4.2"""

    key: str
    """집계 키. `by=hour_of_day` 면 `0`~`23` 을 쓴다."""
    label: str
    count: int
    ratio: float


class MetricsDistributionResponse(SpecModel):
    """`GET /metrics/distribution` 응답. API명세서 §4.2

    `by=hour_of_day` 는 시간대 히트맵(FN-UI-05)의 데이터원이 된다.
    """

    by: DistributionBy
    buckets: list[DistributionBucket]


class MetricsRepeatQuery(SpecModel):
    """`GET /metrics/repeat` 쿼리 파라미터. API명세서 §4.2"""

    days: int = 7
    limit: int = 10


class RepeatItem(SpecModel):
    """`GET /metrics/repeat` 의 한 항목. API명세서 §4.2"""

    subject: RepeatSubject
    key: str
    label: str
    violation_type: ViolationType
    count: int
    """기간 내 반복 횟수."""
    last_at: AwareDatetime


class MetricsRepeatResponse(SpecModel):
    """`GET /metrics/repeat` 응답. API명세서 §4.2

    **작업자 개인 단위 누적은 하지 않는다.** `track` 은 세션 내 추적 번호일 뿐
    신원이 아니며, 카메라를 벗어나면 유효하지 않다.
    """

    days: int
    items: list[RepeatItem]


# --------------------------------------------------------------------------
# §4.3 영상 검색
# --------------------------------------------------------------------------


class SceneSearchFilters(SpecModel):
    """`POST /search/scenes` 필터. API명세서 §4.3"""

    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    cam_id: int | None = None


class SceneSearchRequest(SpecModel):
    """`POST /search/scenes` 요청. API명세서 §4.3"""

    query: str
    top_k: int
    filters: SceneSearchFilters


class SceneSearchItem(SpecModel):
    """`POST /search/scenes` 결과 항목. API명세서 §4.3"""

    event_id: str
    similarity: float
    """질의 임베딩과 키프레임 임베딩의 코사인 유사도."""
    title: str
    cam_id: int
    occurred_at: AwareDatetime
    thumbnail_url: str
    clip_url: str


class SceneSearchResponse(SpecModel):
    """`POST /search/scenes` 응답. API명세서 §4.3"""

    mode: SearchMode
    """서버가 질의를 분석해 자동 선택한 처리 경로."""
    items: list[SceneSearchItem]


# --------------------------------------------------------------------------
# §4.4 챗봇 · 보고서
# --------------------------------------------------------------------------


class ChatSource(SpecModel):
    """챗봇 응답 근거. API명세서 §4.4"""

    type: str
    detail: str


class ClipAttachment(SpecModel):
    """`attachments[]` 의 클립 첨부. API명세서 §4.4"""

    kind: Literal["clip"] = "clip"
    event_id: str
    clip_url: str
    thumbnail_url: str
    label: str


class ImageAttachment(SpecModel):
    """`attachments[]` 의 이미지 첨부. API명세서 §4.4"""

    kind: Literal["image"] = "image"
    image_url: str
    label: str


class TableAttachment(SpecModel):
    """`attachments[]` 의 표 첨부 — SQL 집계 결과 표시용. API명세서 §4.4"""

    kind: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[Any]]
    label: str


class EventRefAttachment(SpecModel):
    """`attachments[]` 의 이벤트 링크 — 상세 화면으로 이동. API명세서 §4.4"""

    kind: Literal["event_ref"] = "event_ref"
    event_id: str
    label: str


#: `attachments[]` 원소. `kind` 값으로 구분되는 판별 유니온. API명세서 §4.4
#: 모든 첨부는 **URL 규약**을 따른다 — 서버 파일 경로를 싣지 않는다.
ChatAttachment = Annotated[
    ClipAttachment | ImageAttachment | TableAttachment | EventRefAttachment,
    Field(discriminator="kind"),
]


class ChatRequest(SpecModel):
    """`POST /assistant/chat` 요청. API명세서 §4.4"""

    session_id: str
    message: str


class ChatResponse(SpecModel):
    """`POST /assistant/chat` 응답. API명세서 §4.4"""

    route: ChatRoute
    answer: str
    attachments: list[ChatAttachment] = Field(default_factory=list)
    sources: list[ChatSource] = Field(default_factory=list)


class BriefingRequest(SpecModel):
    """`POST /assistant/briefing` 요청. API명세서 §4.4"""

    cam_ids: list[int]


class BriefingResponse(SpecModel):
    """`POST /assistant/briefing` 응답. API명세서 §4.4"""

    summary: str
    captured_at: AwareDatetime


class WeeklyReportRequest(SpecModel):
    """`POST /reports/weekly` 요청. API명세서 §4.4"""

    from_: date = Field(alias="from")
    to: date


class WeeklyReportResponse(SpecModel):
    """`POST /reports/weekly` 응답. API명세서 §4.4"""

    report_id: str
    status: str
    estimated_sec: int


# --------------------------------------------------------------------------
# §4.5 설정
# --------------------------------------------------------------------------


class CalibrationPoint(SpecModel):
    """지면 캘리브레이션 대응점 1쌍. API명세서 §4.5"""

    px: PointPx
    """화면에서 클릭한 지점(정규화 좌표)."""
    m: PointM
    """그 지점의 실제 지면 좌표(m). 줄자 실측. 첫 점을 원점(0,0)으로 권장."""


class ReferencePerson(SpecModel):
    """높이 비율 기준 보정용(선택). API명세서 §4.5

    미입력 시 카메라 기하로 기대 높이를 추정한다.
    """

    px_height: float
    at_m: PointM


class CalibrationRequest(SpecModel):
    """`POST /cameras/{cam_id}/calibration` 요청. API명세서 §4.5"""

    points: list[CalibrationPoint]
    reference_person: ReferencePerson | None = None


class CalibrationResponse(SpecModel):
    """`POST /cameras/{cam_id}/calibration` 응답. API명세서 §4.5"""

    homography: Homography
    reprojection_error_m: float
    ref_height_calibrated: bool


class Zone(SpecModel):
    """금지구역. `GET /zones` / `POST /zones`. API명세서 §4.5"""

    zone_id: str
    cam_id: int
    name: str
    polygon_m: list[PointM]
    """**지면 실좌표 기준** 꼭짓점 배열. 화면 픽셀 좌표는 서버가 호모그래피로 변환해 저장."""
    buffer_m: float
    """경계 여유. 호모그래피 오차 흡수 및 사전 경고용."""
    active: bool


class VehicleClass(SpecModel):
    """클래스별 위험 반경. `GET /vehicle-classes`. API명세서 §4.5"""

    class_name: str
    danger_radius_m: float
    active: bool


class VehicleClassPatch(SpecModel):
    """`PATCH /vehicle-classes/{name}` 요청. API명세서 §4.5"""

    danger_radius_m: float | None = None
    active: bool | None = None


class ManualAlertRequest(SpecModel):
    """`POST /alerts/manual` 요청. API명세서 §4.5"""

    cam_id: int
    sound: str
    level: int


class MuteAlertRequest(SpecModel):
    """`POST /alerts/mute` 요청. API명세서 §4.5"""

    cam_id: int
    minutes: int
    reason: str


# --------------------------------------------------------------------------
# §4.6 시스템
# --------------------------------------------------------------------------


class EdgeStatus(SpecModel):
    """엣지 상태. API명세서 §4.6

    fps 는 여기 있지 않다 — 카메라별 값이므로 `SystemStatus.cameras[]` 로 간다
    (§2.4 `heartbeat.cameras[]` 와 같은 형식).
    """

    online: bool
    gpu_util: float
    cls_cache_hit_rate: float
    depth_calls_per_min: int

    msg_rejected_total: int
    """스키마 검증에 실패해 거부된 엣지 메시지 누적 건수. API명세서 §2.2 · FN-SYS-06

    감지된 위반이 검증 단계에서 소리 없이 사라지는 것은 오탐보다 위험하다.
    **0이 아니면 대시보드에 경고를 띄운다.** 엣지 구현이 바뀌어 필드가 누락되기
    시작하면 이 값이 오르는 것으로 즉시 드러나야 한다.
    """


class CameraStatus(SpecModel):
    """카메라 스트림 상태. API명세서 §4.6

    **메인과 서브를 따로 노출한다.** 서로 다른 스트림이고 관측 주체도 다르다 —
    메인이 끊겨도 추론은 계속되고, 서브가 끊겨도 녹화는 계속된다. 하나로 합치면
    어느 쪽이 죽었는지 구분할 수 없다.
    """

    cam_id: int
    main_state: StreamState
    """**서버가 보는 메인 스트림**(1920×1080, 라이브·녹화용) 상태."""
    sub_state: StreamState
    """**엣지가 보는 서브 스트림**(640×360, 추론용) 상태. `heartbeat` 값을 그대로 전달."""
    fps: float
    """엣지의 실제 처리 fps."""


class McuStatus(SpecModel):
    """ESP32 상태. API명세서 §4.6"""

    online: bool
    last_seen: AwareDatetime | None = None


class CloudStatus(SpecModel):
    """클라우드 상태. API명세서 §4.6

    `quota_used` 초과 시 **분석 기능만 중단되고 안전 기능은 무관**하다.
    """

    available: bool
    quota_used: float


class StorageStatus(SpecModel):
    """저장소 상태. API명세서 §4.6"""

    retention_days: int
    free_gb: int


class TimeSyncStatus(SpecModel):
    """엣지–서버 시각 차이. 크면 클립 추출 구간이 어긋난다. API명세서 §4.6"""

    edge_offset_ms: int


class SystemStatus(SpecModel):
    """`GET /system/status`. API명세서 §4.6"""

    edge: EdgeStatus
    cameras: list[CameraStatus]
    mcu: McuStatus
    cloud: CloudStatus
    storage: StorageStatus
    time_sync: TimeSyncStatus
