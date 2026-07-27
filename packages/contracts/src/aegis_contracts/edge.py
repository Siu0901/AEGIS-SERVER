"""엣지 → 서버 WebSocket `/ws/edge` 메시지.

출처: API명세서 §2

엣지는 **판단하지 않는다.** 규칙에 걸리면 후보(`CandidateMsg`)만 올리고
확정·경고·시정판정은 전부 서버가 한다.
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from ._base import Bbox, PointM, PointPx, SpecModel
from .enums import (
    CameraState,
    DistanceMethod,
    HelmetState,
    ObjectClass,
    Posture,
    TrackLostReason,
    ViolationType,
)

__all__ = [
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


class DetectedVehicle(SpecModel):
    """`frame` 메시지의 vehicle(지게차) 객체. API명세서 §2.1

    지게차는 지면 주행 장비라 접점이 명확하므로 `anchor_m` 이 접지 기준점이 된다.
    """

    class_: Literal["vehicle"] = Field(alias="class")
    track_id: int
    conf: float
    bbox: Bbox

    anchor_m: PointM
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
    """

    type: Literal["candidate"] = "candidate"
    cam_id: int
    ts: AwareDatetime
    track_id: int
    violations: list[ViolationType]
    zone_id: str | None = None
    bbox: Bbox
    conf: float
    foot_point_m: PointM
    foot_conf: float

    helmet: HelmetState | None = None
    helmet_conf: float | None = None
    posture: Posture | None = None

    observed_ms: int
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


class HeartbeatMsg(SpecModel):
    """`heartbeat` — 상태 보고 (5초 주기). API명세서 §2.4"""

    type: Literal["heartbeat"] = "heartbeat"
    ts: AwareDatetime
    fps: dict[str, float]
    gpu_util: float
    mem_used_mb: int
    cls_calls_per_min: int
    cls_cache_hit_rate: float
    depth_calls_per_min: int
    cameras: dict[str, CameraState]


#: `/ws/edge` 로 올라오는 모든 메시지. `type` 값으로 구분되는 판별 유니온.
EdgeMessage = Annotated[
    FrameMsg | CandidateMsg | TrackLostMsg | HeartbeatMsg,
    Field(discriminator="type"),
]
