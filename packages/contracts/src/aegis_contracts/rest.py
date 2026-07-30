"""REST API 요청·응답 모델.

출처: API명세서 §1.4 (오류) · §4 (전 절)

Base URL: `http://<server-host>:8000/api/v1`
"""

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field

from ._base import Homography, PointM, PointPx, SpecModel
from .enums import (
    AlertLevel,
    ChatRoute,
    ClipExtractStatus,
    ClipStatus,
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
    "ClipRequest",
    "ClipResponse",
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
    "ManualAlertResponse",
    "McuStatus",
    "MetricsDistributionQuery",
    "MetricsDistributionResponse",
    "MetricsRepeatQuery",
    "MetricsRepeatResponse",
    "MetricsSummary",
    "MetricsTimeseriesQuery",
    "MetricsTimeseriesResponse",
    "MuteAlertRequest",
    "MuteAlertResponse",
    "NearbySnapshot",
    "RecCameraStatus",
    "RecStatusResponse",
    "RecStorageStatus",
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
    "TableCell",
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
    """**최초** 경고 발동 시각. 재경고로 갱신하지 않는다."""
    last_alerted_at: AwareDatetime | None
    """**최근** 경고 시각. 재경고 시 갱신된다(§4.1 · §6).

    `alerted_at` 과 분리한 이유: `resolution_sec` 이 `alerted_at → resolved_at` 으로
    정의되어 있어, 재경고마다 `alerted_at` 을 덮으면 재경고가 많을수록 시정 소요
    시간이 짧아져 **시정률이 부풀려진다**.
    """
    note: str | None
    """관리자 메모. 수동 정정 사유 등. 이벤트 상세 화면(FN-UI-03)에서 표시한다(§4.1).

    **저장만 되고 다시 읽을 수 없던 필드다.** 명세서가 §4.1 응답에 추가하면서
    오탐 사유가 화면까지 도달하게 됐다.
    """
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

    # ⚠ 아래 셋은 §6 `events` 컬럼이지만 §4.1 응답 예시에는 아직 칸이 없다.
    # 세 값 모두 **다시 읽을 수 없으면 화면이 그릴 수 없는** 것들이라 상세 응답에 둔다.
    # `docs/INDEX.md` 「명세서 확인 필요」에 올려 두었다(CLAUDE.md 절대규칙 8).
    clip_status: ClipStatus | None
    """`pending` / `ready` / `failed`. 확정 전이면 `null`.

    이벤트 상세 화면(FN-UI-03)은 `pending` 동안 클립 대신 키프레임을 보여준다.
    §5.2 `event_updated` 로는 그 순간 화면을 보고 있던 사람만 알 수 있으므로,
    나중에 열어본 사람도 알 수 있도록 상세 응답이 같은 값을 준다.
    """

    clip_error: str | None
    """클립 추출 실패 사유. REC 의 `reason`(§4.7)을 그대로 담는다(§6).

    **`note` 와 섞지 않는다.** 관리자 메모와 기계가 남긴 실패 사유가 한 칸을 쓰면
    사람이 쓴 문장을 지우거나 사유가 덮이는 일이 생긴다.
    """

    alert_suppressed: bool
    """경고 일시중지 중에 확정되어 **방송이 나가지 않은** 이벤트인가(§6 · §4.8).

    시정률 집계에서 전량 제외된다 — 작업자에게 알린 적이 없으니 시정할 기회도 없었다.
    화면은 이 값이 참인 이벤트에 그 사실을 표시한다(미시정으로 보이면 안 된다).
    """


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

    ```
    correction_rate   = resolved / (resolved + resolved_late + unresolved)
    undetermined_rate = expired  / (resolved + resolved_late + unresolved + expired)
    ```
    """

    period: str
    correction_rate: float | None
    """**분모가 0이면 `null`**(§6.7). `0.0` 은 "시정률이 0%"라는 주장이지만 실제로는
    "판정 가능한 이벤트가 없다"는 뜻이라 둘을 같은 값으로 내보낼 수 없다.
    판정 불가 이벤트만 있는 구간에서 0% 가 표시되면 시스템이 전혀 작동하지 않은
    것처럼 보인다. 화면은 `null` 을 `–` 로 그린다."""
    undetermined_rate: float | None
    """모집단이 비면 `null`. `correction_rate` 와 같은 이유다."""
    total_violations: int
    resolved: int
    """`resolve_window_s` **이내**에 해소된 건수. 분자에 들어가는 유일한 버킷이다."""
    resolved_late: int
    """해소됐으나 창을 넘긴 건수. **분모에만** 들어간다.

    `unresolved` 와 섞지 않는다 — "시정은 했으나 늦었다"와 "아직 안 했다"는 현장에서
    의미가 다르고, 합쳐두면 응답만 보고 원인을 구분할 수 없다(§6.7)."""
    unresolved: int
    """아직 해소되지 않은 건수(`alerted` · `re_alerted`)."""
    undetermined: int
    suppressed: int
    """경고 일시중지 중에 확정되어 **방송이 나가지 않은** 건수(기능명세서 §4.8).

    시정률 분모·분자 모두에서 제외된다. 지표 이름이 「**방송 후** 시정률」이므로
    방송이 없었던 이벤트는 모집단이 아니다 — 알린 적이 없으니 시정할 기회도 없었고,
    미시정으로 세면 시스템 성능을 부당하게 깎는다. `expired` 와 같은 원칙으로
    **제외하고 건수를 공개**한다.

    ⚠ §4.2 응답 예시에는 아직 이 칸이 없다. §4.8 이 「`suppressed` 로 별도 집계」를
    요구하므로 여기 둔다 — `docs/INDEX.md` 「명세서 확인 필요」 참조.
    """
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
    """버킷 시작 시각. **표기는 `bucket` 에 따라 다르다**(§4.2).

    | `bucket` | 형식 | 예 |
    |---|---|---|
    | `day` | `YYYY-MM-DD` | `2026-08-12` |
    | `week` | `YYYY-MM-DD` (그 주 **월요일**) | `2026-08-10` |
    | `hour` | `YYYY-MM-DDTHH:00:00Z` | `2026-08-12T09:00:00Z` |

    세 형식이 한 필드에 오므로 `AwareDatetime` 이 아니라 `str` 이다. 날짜 버킷을
    자정 시각으로 바꿔 실으면 "그 날"과 "그 날 0시"가 구분되지 않는다.
    """
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
    """집계 키. **모든 축에서 문자열이다**(§4.2).

    `by=hour_of_day` 는 `"00"`~`"23"` 으로 **0을 채운다** — 사전순 정렬이 시각순과
    일치해야 히트맵(FN-UI-05)의 칸 순서가 뒤집히지 않기 때문이다(`"10" < "9"`).
    """
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


#: `TableAttachment.rows[][]` 의 셀. API명세서 §4.4 — **string / number / null 만.**
#:
#: `Any` 로 열어두지 않는다. 표는 SQL 집계 결과를 그대로 옮기는 자리라 중첩 객체나
#: 배열이 들어오면 화면이 렌더링할 수 없고, 그 사실이 런타임까지 숨는다.
#: `bool` 은 파이썬에서 `int` 의 하위형이라 여기에 이미 포함된다.
TableCell = str | int | float | None


class TableAttachment(SpecModel):
    """`attachments[]` 의 표 첨부 — SQL 집계 결과 표시용. API명세서 §4.4"""

    kind: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[TableCell]]
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
    sound: str | None = None
    """`alert_sounds` 의 키. **미지정 시 기본 안내 음원**을 쓴다(§4.5)."""
    level: AlertLevel
    """`1` | `2` | `3`. `notify_device` 가 참이면 이 값으로 MQTT 도 발행한다."""
    notify_device: bool = True
    """기본 `true`. 스피커만 울리고 경광등은 끄고 싶으면 `false`(§4.5)."""


class ManualAlertResponse(SpecModel):
    """`POST /alerts/manual` 응답(`202`). API명세서 §4.5"""

    dispatched_at: AwareDatetime


class MuteAlertRequest(SpecModel):
    """`POST /alerts/mute` 요청. API명세서 §4.5"""

    cam_id: int | None = None
    """**생략하면 전체 카메라**에 적용된다(§4.5)."""
    minutes: int | None = None
    """`0` 은 즉시 해제다. 생략하면 `mute_default_duration_s`(기본 900초)를 쓴다.

    **기한 없는 일시중지가 되지 않도록** 서버가 정책 기본값을 붙인다 —
    꺼둔 것을 잊는 순간 감시가 조용히 멎는 상태가 오탐보다 위험하다.
    """
    reason: str


class MuteAlertResponse(SpecModel):
    """`POST /alerts/mute` · `GET /alerts/mute` 응답. API명세서 §4.5

    두 엔드포인트가 **같은 형태**를 돌려준다(§4.5). 조회 경로가 있어야 화면이
    "언제 풀리는지"를 새로고침 뒤에도 알 수 있다.
    """

    cam_id: int | None
    """`null` 이면 전체 카메라 대상이다."""
    muted: bool
    muted_until: AwareDatetime | None
    """해제 시각. `muted` 가 거짓이면 `null`."""
    reason: str | None
    """일시중지 사유. `muted` 가 거짓이면 `null`."""


# --------------------------------------------------------------------------
# §4.6 시스템
# --------------------------------------------------------------------------
# **관측 주체가 없을 때는 `null` 을 쓴다** (§4.6 「관측 주체가 없을 때는 null 을 쓴다」).
#
# `0` 이나 `false` 는 "관측했더니 0이었다"는 **주장**이라 실제 장애와 구분되지 않는다.
# 예외는 두 가지다.
#
# * `edge.msg_rejected_total` — 서버가 직접 세므로 관측 주체가 항상 존재한다(`0` 시작)
# * `sub_state` — `StreamState` 에 "모름"이 없고, 연결되지 않은 것은 사실이므로 `"down"`
#
# 대시보드는 `null` 을 "측정 불가"로 표시하고 `0` 과 다르게 그린다.


class EdgeStatus(SpecModel):
    """엣지 상태. API명세서 §4.6

    fps 는 여기 있지 않다 — 카메라별 값이므로 `SystemStatus.cameras[]` 로 간다
    (§2.4 `heartbeat.cameras[]` 와 같은 형식).
    """

    online: bool
    """연결 여부는 서버가 직접 안다. 관측 주체가 있으므로 `false` 가 사실이다."""

    gpu_util: float | None
    """엣지 미연결 시 `null`. 게이지 값은 관측 없이 0으로 채우지 않는다(§4.6)."""

    cls_cache_hit_rate: float | None
    """엣지 미연결 시 `null`."""

    depth_calls_per_min: int | None
    """엣지 미연결 시 `null`."""

    msg_rejected_total: int
    """스키마 검증에 실패해 거부된 엣지 메시지 누적 건수. API명세서 §2.2 · FN-SYS-06

    감지된 위반이 검증 단계에서 소리 없이 사라지는 것은 오탐보다 위험하다.
    **0이 아니면 대시보드에 경고를 띄운다.** 엣지 구현이 바뀌어 필드가 누락되기
    시작하면 이 값이 오르는 것으로 즉시 드러나야 한다.

    **여기만 `null` 이 아니다** — 서버가 직접 세는 값이라 관측 주체가 항상 있다(§4.6).
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
    fps: float | None
    """엣지의 실제 처리 fps.

    **엣지가 붙기 전에는 `null` 이다**(§4.6 null 규약). `0.0` 은 "엣지가 돌고 있는데
    처리량이 0"이라는 다른 의미이므로 실제 장애와 구분되지 않는다.
    """

    recording: bool | None
    """REC 이 이 카메라를 녹화 중인지. API명세서 §4.6

    **REC 의 `GET /status`(§4.7) 값을 그대로 전달한다.** 서버가 메인 스트림 상태로
    추론하지 않는다 — 라이브가 보이는 것과 녹화되는 것은 다른 프로세스의 일이라,
    추론으로 그리면 녹화가 죽은 채 REC 표시만 켜져 있는 화면이 만들어진다.
    화면의 REC 표시는 이 값으로 그린다.

    **REC 에 닿지 못하면 `null`**(관측 주체 없음). `false` 는 "REC 이 살아 있는데
    이 카메라만 녹화하지 않는다"는 다른 뜻이다.
    """


class McuStatus(SpecModel):
    """ESP32 상태. API명세서 §4.6"""

    online: bool
    last_seen: AwareDatetime | None = None


class CloudStatus(SpecModel):
    """클라우드 상태. API명세서 §4.6

    `quota_used` 초과 시 **분석 기능만 중단되고 안전 기능은 무관**하다.
    """

    available: bool
    quota_used: float | None
    """무료 한도 사용률. **클라우드가 붙기 전에는 `null`.**

    `0.0` 은 "한도를 하나도 쓰지 않았다"는 관측 결과이므로, 아직 아무도 재지 않은
    상태와 구분되어야 한다(§4.6 null 규약).
    """


class StorageStatus(SpecModel):
    """저장소 상태. API명세서 §4.6

    **REC(§4.7)의 `GET /status` 응답 `storage` 절을 5필드 그대로 전달한다.** 서버가
    자체 디스크를 조회해 채우지 않는다 — 운용 시 녹화 디스크는 서버 노트북이 아니라
    엣지 NVMe SSD 이고, 서버 디스크의 여유 공간은 녹화와 아무 상관이 없다.

    **REC 에 닿지 못하면 다섯 필드가 전부 `null` 이다.** 서버의 로컬 디스크 값으로
    대신 채우지 않는다 — "녹화 공간이 남아 있다"는 잘못된 확신을 주기 때문이다.
    이때 `/ws/dashboard` 로 `system` `component="storage"` `state="down"` 이
    함께 나간다(§5.3).
    """

    total_gb: int | None
    used_gb: int | None
    free_gb: int | None
    retention_days: int | None
    oldest_segment_at: AwareDatetime | None
    """보존된 가장 오래된 세그먼트 시각. **영상 검색 가능 범위의 하한이다.**

    세그먼트가 한 개도 없으면(기동 직후) `null` 이고, REC 미도달 때도 `null` 이다.
    """


class TimeSyncStatus(SpecModel):
    """엣지–서버 시각 차이. 크면 클립 추출 구간이 어긋난다. API명세서 §4.6"""

    edge_offset_ms: int | None
    """`heartbeat` 로 관측한다. **엣지가 붙기 전에는 `null`**(§4.6 null 규약).

    `0` 은 "완벽히 동기화됨"이라는 강한 주장이고, 측정한 적이 없다는 사실과 정반대다.
    클립 구간 정합이 이 값에 걸려 있으므로 측정 없음을 동기화됨으로 보이게 하면 안 된다.
    """


class SystemStatus(SpecModel):
    """`GET /system/status`. API명세서 §4.6"""

    edge: EdgeStatus
    cameras: list[CameraStatus]
    mcu: McuStatus
    cloud: CloudStatus
    storage: StorageStatus
    """**REC(§4.7)의 `GET /status` 값을 5필드 그대로 전달한다.** 서버가 자체 디스크를
    조회해 채우지 않는다 — 운용 시 녹화 디스크는 서버가 아니라 엣지 SSD 에 있다."""
    time_sync: TimeSyncStatus


# --------------------------------------------------------------------------
# §4.7 서버 → REC (녹화 컴포넌트 내부 API)
# --------------------------------------------------------------------------
# REC 은 메인 스트림 녹화와 구간 추출만 하는 독립 컴포넌트다. 개발 중에는 서버와 같은
# 기계에서 돌지만 운용 시에는 엣지 NVMe SSD 위에서 돈다. **서버는 녹화 파일에 직접
# 접근하지 않고 항상 이 API 를 쓴다** — 옮길 때 `RECORDER_BASE` 하나만 바꾸면 되도록.


class ClipRequest(SpecModel):
    """`POST /clips` 요청. API명세서 §4.7"""

    cam_id: int
    from_: AwareDatetime = Field(alias="from")
    to: AwareDatetime
    event_id: str
    """추출 결과 파일명이자 서버가 자기 저장소에 옮길 때 쓰는 키."""


class ClipResponse(SpecModel):
    """`POST /clips` 응답. API명세서 §4.7"""

    status: ClipExtractStatus

    size_bytes: int | None = None
    download_url: str | None = None
    """`RECORDER_BASE` 기준 상대 경로."""

    actual_from: AwareDatetime | None = None
    actual_to: AwareDatetime | None = None
    """세그먼트 경계 때문에 요청 구간과 다를 수 있다. **실제로 잘라낸 구간을 정확히 반환한다.**

    요청 시각이 세그먼트 중간에 걸치면 그 세그먼트의 시작부터 포함되므로 **클립이
    요청보다 최대 세그먼트 길이(10초)만큼 길어질 수 있다. 이는 정상 동작이다**(§4.7).
    이벤트 클립에서는 앞뒤 맥락이 늘어나는 것이므로 문제가 되지 않는다.

    파일이 만들어지지 않은 `not_found` 에서는 네 필드가 모두 `null` 이다.
    """

    reason: str | None = None
    """비-`ready` 사유. `partial` · `not_found` 에서 채운다. API명세서 §4.7

    `status` 만으로는 "보존 기간이 지났다"와 "그 시각에 녹화가 없었다"가 구분되지
    않는다. 서버는 이 값을 보고 `clip_status = failed` 의 원인을 기록한다.
    `ready` 에서는 `null`.
    """


class RecCameraStatus(SpecModel):
    """`GET /status` 의 카메라 항목. API명세서 §4.7"""

    cam_id: int
    recording: bool
    last_segment_at: AwareDatetime | None = None
    """마지막으로 닫힌 세그먼트의 시작 시각. 한 개도 없으면 `null`."""


class RecStorageStatus(SpecModel):
    """`GET /status` 의 저장소 절. API명세서 §4.7

    §4.6 `storage` 와 **같은 5필드**다. 서버는 고르거나 가공하지 않고 그대로 옮긴다.
    다른 점은 nullable 여부뿐이다 — REC 은 자기 디스크를 직접 재므로 값이 항상 있고,
    서버 쪽은 REC 에 닿지 못하면 `null` 이 된다.
    """

    total_gb: int
    used_gb: int
    free_gb: int
    retention_days: int
    oldest_segment_at: AwareDatetime | None = None


class RecStatusResponse(SpecModel):
    """`GET /status`. API명세서 §4.7"""

    cameras: list[RecCameraStatus]
    storage: RecStorageStatus
