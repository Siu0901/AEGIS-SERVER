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

from ._base import Bbox, PointM, PointPx, SpecModel
from .enums import (
    DistanceMethod,
    HelmetState,
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
    "EdgeMessage",
    "FrameMsg",
    "HeartbeatMsg",
    "NearbyVehicle",
    "TrackLostMsg",
]


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

    violations: list[ViolationType] = Field(min_length=1, max_length=1)
    """이 메시지가 나르는 위반 유형 **하나**. §2.2 의 배열 형태는 유지한다."""

    bbox: Bbox
    conf: float
    foot_point_m: PointM

    observed_ms: int
    """**이 메시지의 위반 유형**을 연속 관측한 시간(ms). 서버 확정 판정의 참고값."""

    @property
    def violation(self) -> ViolationType:
        """이 후보의 위반 유형. 배열이지만 원소는 항상 하나다."""
        return self.violations[0]

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


#: `/ws/edge` 로 올라오는 모든 메시지. `type` 값으로 구분되는 판별 유니온.
EdgeMessage = Annotated[
    FrameMsg | CandidateMsg | TrackLostMsg | HeartbeatMsg,
    Field(discriminator="type"),
]
