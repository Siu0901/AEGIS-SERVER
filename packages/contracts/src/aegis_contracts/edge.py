"""엣지 → 서버 WebSocket `/ws/edge` 메시지.

출처: API명세서 §2

엣지는 **판단하지 않는다.** 규칙에 걸리면 후보(`CandidateMsg`)만 올리고
확정·경고·시정판정은 전부 서버가 한다.

**필수 · 선택 규약** (API명세서 §2.1 말미, §2.1~§2.4 전체 적용)

| 명세서 표기 | 코드 표현 |
|---|---|
| `·생략` | `X \\| None = None` — 필드가 아예 안 실릴 수 있다 |
| `·null` | `X \\| None` (기본값 없음) — **필드는 항상 실리고 값만 null** |
| 표기 없음 | 기본값 없는 필수 필드 |

`·null` 에 기본값을 주면 안 된다. 값이 null인 것과 필드가 없는 것은 다른 사실이고,
엣지 구현이 필드를 빠뜨리기 시작해도 드러나지 않게 된다.
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from ._base import Bbox, Contour, PointM, PointPx, SpecModel
from .enums import (
    DistanceMethod,
    HelmetState,
    NearbyBasis,
    ObjectClass,
    Posture,
    StreamState,
    TrackLostReason,
    ViolationType,
)

__all__ = [
    "CameraHealth",
    "CandidateMsg",
    "DetectedObject",
    "DetectedPerson",
    "DetectedVehicle",
    "EdgeClock",
    "EdgeMessage",
    "FrameMsg",
    "FrameNearby",
    "HeartbeatMsg",
    "NearbyVehicle",
    "TrackLostMsg",
]


class FrameNearby(SpecModel):
    """`frame.objects[].nearby[]` — 이 사람과 차량 사이의 거리. API명세서 §2.1

    **확정과 해소는 반드시 같은 양을 본다.** 엣지는 마스크 최근접 거리(§6.5)로
    `proximity` 후보를 만드는데, 서버가 그 값을 받지 못하면 접지점↔`anchor_m` 거리로
    대체 계산하게 된다. 두 값은 **FN-DET-09 가 존재하는 바로 그 상황**(포크가 뻗은
    지게차)에서 크게 갈린다(실측 1.55m 대 3.50m) — 엣지가 근접이라고 올린 순간 서버는
    이미 해소로 판정해 이벤트가 확정에 도달하지 못한다.

    엣지는 후보 생성을 위해 이 값을 이미 계산하고 있으므로 추가 연산 비용은 없다.
    **판정의 원천은 하나여야 한다.**

    `candidate.nearby[]`(`NearbyVehicle` · §2.2)와 다른 모델이다. 저쪽은 후보의 근거를
    담아 `method` · `depth_verified` · `moving` 을 싣고, 이쪽은 매 프레임 흐르는 관측값이라
    해소 판정과 거리선에 필요한 것만 싣는다.
    """

    track_id: int
    class_: Literal["vehicle"] = Field(alias="class")
    dist_m: float
    """지면 거리(m). **해소 판정(FN-EVT-03)과 오버레이 거리선이 같이 보는 값이다.**"""
    basis: NearbyBasis
    """`mask_nearest`(P1 · 기본) / `anchor`(마스크가 없을 때의 대체)."""
    in_danger_zone: bool
    """`danger_radius_m` 이내 여부."""


class DetectedPerson(SpecModel):
    """`frame` 메시지의 person 객체. API명세서 §2.1

    `helmet` 은 2단계 분류 결과이며 `on` / `off` 두 값만 존재한다(§6.3).
    크기·신뢰도 게이트를 통과하지 못하고 직전 캐시도 없으면 **필드 자체가 생략**된다.
    """

    class_: Literal["person"] = Field(alias="class")
    track_id: int
    conf: float
    bbox: Bbox

    # `helmet` 이 실린 경우에만 함께 실린다 — 셋은 한 묶음이다.
    helmet: HelmetState | None = None
    helmet_conf: float | None = None
    helmet_checked_at: AwareDatetime | None = None

    foot_point: PointPx
    foot_point_m: PointM
    foot_conf: float
    posture: Posture
    height_ratio: float
    axis_angle_deg: float
    stillness_s: float

    in_zone: str | None
    """구역 밖이면 `null`. **필드 자체는 항상 실린다**(기본값 없음)."""

    nearby: list[FrameNearby]
    """이 사람과 차량 사이의 거리. 주변에 없으면 **빈 배열**이며 필드는 항상 실린다.

    기본값을 두지 않는 이유: 엣지가 이 필드를 빠뜨리기 시작하면 서버는 "주변에 지게차가
    없다"로 읽고 진행 중인 `proximity` 이벤트를 해소로 판정한다. 빠진 것과 없는 것이
    같아 보이면 안 되는 자리다.
    """

    riding_track_id: int | None = None
    """탑승 중인 차량의 `track_id`. 탑승 중이 아니면 `null` (FN-DET-13 · §2.1).

    ★ **탑승자는 일부 판정에서 제외된다** — 자신이 탄 차량과의 `proximity`,
      `zone_intrusion`, `fall`. `no_helmet` 은 **제외하지 않는다**(운전자도 착용 대상).
    """

    contour: Contour | None = None
    """진단용 마스크 윤곽 (API명세서 §2.1). 정책 `overlay_mask` 가 켜졌을 때만 채운다.

    ★ **판정에 쓰지 않는다.** 없으면 필드를 생략한다 — `null` 을 싣지 않는다.
    """


class DetectedVehicle(SpecModel):
    """`frame` 메시지의 vehicle(지게차) 객체. API명세서 §2.1

    지게차는 지면 주행 장비라 접점이 명확하므로 `anchor` 가 접지 기준점이 된다.
    """

    class_: Literal["vehicle"] = Field(alias="class")
    track_id: int
    conf: float
    bbox: Bbox

    anchor: PointPx
    """지면 기준점의 **정규화 좌표**. 오버레이 거리선의 끝점이다(§5.1).

    **`bbox` 아래변 중앙이 아니다.** 마스크 하단에서 산출한 값이라 포크가 뻗었거나
    적재물이 있으면 박스 중앙과 어긋난다. 클라이언트가 `bbox` 로 추정하지 않도록
    엣지가 반드시 함께 싣는다(§2.1).
    """

    anchor_m: PointM
    """위 좌표를 호모그래피로 변환한 지면 실좌표(m). 거리·구역 판정 기준."""

    moving: bool
    danger_radius_m: float

    contour: Contour | None = None
    """진단용 마스크 윤곽 (API명세서 §2.1). 정책 `overlay_mask` 가 켜졌을 때만 채운다.

    ★ **판정에 쓰지 않는다.** 없으면 필드를 생략한다 — `null` 을 싣지 않는다.
    """


#: `frame.objects[]` 원소. `class` 값으로 구분되는 판별 유니온.
DetectedObject = Annotated[
    DetectedPerson | DetectedVehicle,
    Field(discriminator="class_"),
]


class FrameMsg(SpecModel):
    """`frame` — 프레임 메타데이터 (매 프레임). API명세서 §2.1

    대시보드 오버레이용 좌표 스트림이다. **영상과 마스크는 포함하지 않는다.**
    """

    type: Literal["frame"] = "frame"
    cam_id: int
    ts: AwareDatetime
    objects: list[DetectedObject]


class NearbyVehicle(SpecModel):
    """`candidate.nearby[]` 원소 — 주변 위험 지게차. API명세서 §2.2

    스크리닝 반경(`screening_radius_m`, 기본 5m) 안에 든 지게차만 담긴다.
    """

    class_: Literal["vehicle"] = Field(alias="class")
    track_id: int
    dist_m: float
    method: DistanceMethod
    depth_verified: bool
    moving: bool
    within_danger_radius: bool


class CandidateMsg(SpecModel):
    """`candidate` — 이벤트 후보. API명세서 §2.2

    규칙에 걸렸을 때만 전송한다. **확정·경고 판단은 서버가 한다.**

    **메시지 하나에 위반 유형 하나다.** 한 트랙에 두 유형이 동시에 걸리면 후보
    메시지를 유형 수만큼 각각 보낸다 — 유형마다 조건 충족 시작 시각이 달라
    `observed_ms` 가 각각의 값을 가져야 하기 때문이다. 하나로 묶으면 어느 유형의
    관측 시간인지 알 수 없어 확정 판정(FN-EVT-02)의 참고값이 무의미해진다.
    """

    type: Literal["candidate"] = "candidate"
    cam_id: int
    ts: AwareDatetime
    track_id: int

    violation_type: ViolationType
    """이 메시지가 나르는 위반 유형 **하나**. 배열이 아니다(§2.2).

    이벤트 병합 키가 `cam_id + track_id + violation_type`(FN-EVT-01)이고 유형마다
    확정 타이머와 해소 조건이 독립적으로 돈다. REST(§4.1) · 대시보드(§5.2)의
    `violation_type` 과 이름이 일치한다.

    **`overlay.objects[].violations`(§5.1)와 혼동하지 않는다.** 저쪽은 배열이다 —
    한 트랙에 이벤트가 여럿 걸릴 수 있고 화면은 그것을 합쳐 보여준다.
    """

    bbox: Bbox
    conf: float
    foot_point_m: PointM

    observed_ms: int
    """**이 메시지의 `violation_type`** 을 연속 관측한 시간(ms). 서버 확정 판정의 참고값."""

    zone_id: str | None
    """침입한 구역이 없으면 `null`. **필드 자체는 항상 실린다**(§2.1 `in_zone` 과 동일 규약)."""

    foot_conf: float | None = None
    """`fall` 처럼 접지점이 무의미한 경우 생략된다."""

    helmet: HelmetState | None = None
    helmet_conf: float | None = None
    posture: Posture | None = None

    nearby: list[NearbyVehicle] = Field(default_factory=list)


class TrackLostMsg(SpecModel):
    """`track_lost` — 트랙 소실 통지. API명세서 §2.3

    ByteTrack 자체 트랙 버퍼로 복구되는 짧은 단절은 이 메시지를 발생시키지 않는다.
    엣지가 최종적으로 트랙을 포기한 시점에만 전송한다.
    """

    type: Literal["track_lost"] = "track_lost"
    cam_id: int
    track_id: int
    class_: ObjectClass = Field(alias="class")
    last_ts: AwareDatetime
    last_foot_point_m: PointM
    last_helmet: HelmetState | None = None
    reason: TrackLostReason


class CameraHealth(SpecModel):
    """`heartbeat.cameras[]` 원소 — 카메라별 상태. API명세서 §2.4"""

    cam_id: int
    sub_state: StreamState
    """엣지가 보는 **서브 스트림**(640×360, 추론용) 상태.

    메인 스트림은 서버가 따로 보므로 여기 없다. `GET /system/status` 가 둘을 합쳐
    `main_state` · `sub_state` 로 노출한다(§4.6).
    """
    fps: float
    """실제 처리 프레임 수. **8 미만 지속 시 대시보드 경고**."""


class EdgeClock(SpecModel):
    """`heartbeat.clock` — 엣지가 **자체 NTP 로 잰** 자기 시계 오차. API명세서 §2.4

    ★ **서버가 도착 시각으로 추정하지 않는다.** 이 값의 용도는 「클립 추출 구간을
    믿어도 되는가」 하나뿐인데, `ts` 와 도착 시각의 차이로 재면 네트워크 지연이 섞여
    시계 오차와 전송 지연을 구분할 수 없다. 클립이 밀리는 원인은 시계 오차뿐이다.

    자기 신고의 약점 — 엣지 NTP 자체가 실패하면 틀린 값을 자신 있게 보고한다 — 은
    `synced` 로 막는다. `false` 면 서버는 `edge_offset_ms` 를 `null` 로 전달한다.
    """

    offset_ms: float
    """엣지 시계가 기준시보다 얼마나 앞서 있는가(ms). `synced == false` 면 무의미하다."""
    synced: bool
    """엣지 NTP 동기화 성공 여부. **`false` 면 `offset_ms` 를 신뢰하지 않는다.**"""
    source: str | None = None
    """동기 서버. 진단용이며 판정에 쓰지 않는다."""
    last_sync_at: AwareDatetime | None = None
    """마지막 동기 시각. 오래되면 `synced` 가 참이어도 값이 낡았다."""


class HeartbeatMsg(SpecModel):
    """`heartbeat` — 상태 보고 (5초 주기). API명세서 §2.4"""

    type: Literal["heartbeat"] = "heartbeat"
    ts: AwareDatetime
    cameras: list[CameraHealth]
    gpu_util: float
    mem_used_mb: int
    cls_calls_per_min: int
    cls_cache_hit_rate: float
    depth_calls_per_min: int
    clock: EdgeClock | None = None
    """FN-SYS-02 — 엣지 시계 상태(§2.4).

    ★ **없으면 `null` 이지 0이 아니다.** 옛 엣지 빌드가 이 절을 안 보낼 수 있는데,
    그때 서버가 「오차 0」으로 읽으면 동기화된 적 없는 엣지가 완벽한 것으로 보인다.
    보고하지 않는 엣지는 `time_sync.edge_offset_ms` 가 `null` 로 남는다.
    """


#: `/ws/edge` 로 올라오는 모든 메시지. `type` 값으로 구분되는 판별 유니온.
EdgeMessage = Annotated[
    FrameMsg | CandidateMsg | TrackLostMsg | HeartbeatMsg,
    Field(discriminator="type"),
]
