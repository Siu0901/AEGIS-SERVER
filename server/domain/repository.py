"""영속화 경계 — 프로토콜만 정의한다.

`server/domain` 에는 I/O가 없다(CLAUDE.md 절대규칙 2). 여기 있는 것은 **도메인이
필요로 하는 저장소의 모양**일 뿐이고, 실제 구현은 `server/infra/db` 가 담당한다.
그래서 이 모듈은 `sqlmodel` · `sqlalchemy` 를 import 하지 않는다.

메서드를 `async` 로 둔 이유: 서버 런타임(FastAPI · `/ws/edge` · `/ws/dashboard`)이
전부 비동기이고, 나중에 동기→비동기로 바꾸는 비용이 반대 방향보다 크기 때문이다.

M0 에서는 타입이 계약 모델(`aegis_contracts`)로 표현되어 있다. 상태머신 전용
도메인 엔티티는 M2 에서 상태머신과 함께 도입한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from aegis_contracts import (
    EventDetail,
    EventListQuery,
    EventStatus,
    EventSummary,
    Policies,
    VehicleClass,
    ViolationType,
    Zone,
)

__all__ = [
    "AnomalyRepository",
    "CameraRepository",
    "EventRepository",
    "PolicyRepository",
    "Repository",
    "VehicleClassRepository",
    "ZoneRepository",
]


class EventRepository(Protocol):
    """이벤트 영속화. 기능명세서 §4.2 · §6 `events`"""

    async def get(self, event_id: str) -> EventDetail | None: ...

    async def list_events(self, query: EventListQuery) -> tuple[list[EventSummary], str | None]:
        """목록과 `next_cursor` 를 돌려준다. API명세서 §4.1"""
        ...

    async def find_open_by_track(
        self,
        cam_id: int,
        track_id: int,
        violation_type: ViolationType,
    ) -> EventSummary | None:
        """진행 중 이벤트를 찾는다. 중복 병합(FN-EVT-01)의 1차 조회."""
        ...

    async def find_lost_by_camera(self, cam_id: int) -> list[EventSummary]:
        """재결합 후보가 되는 `lost` 이벤트들. FN-EVT-07 ②

        `track_id` 는 카메라 내에서만 유효하므로 조회도 카메라 단위다.
        """
        ...

    async def find_due_clip_jobs(self, now: datetime) -> list[str]:
        """실행 시각이 지난 `clip_status = pending` 이벤트 ID들. FN-REC-03

        서버 재시작 시 예약 잡을 DB에서 복구해 재실행하기 위한 조회다.
        """
        ...

    async def count_repeat_7d(
        self,
        cam_id: int,
        track_id: int,
        zone_id: str | None,
    ) -> int:
        """동일 트랙·구역의 최근 7일 유사 이벤트 수. FN-EVT-06"""
        ...

    async def create(self, event: EventDetail) -> None: ...

    async def update(self, event_id: str, changes: dict[str, Any]) -> None:
        """부분 갱신. 상태 전이·타임스탬프·재결합 이력 반영에 쓴다."""
        ...

    async def set_status(
        self,
        event_id: str,
        status: EventStatus,
        at: datetime,
    ) -> None:
        """상태 전이 1건을 기록한다. 전이 판단 자체는 도메인 상태머신이 한다."""
        ...


class ZoneRepository(Protocol):
    """금지구역. 기능명세서 §6 `zones` · API명세서 §4.5"""

    async def list_zones(self, cam_id: int | None = None) -> list[Zone]: ...

    async def get(self, zone_id: str) -> Zone | None: ...

    async def upsert(self, zone: Zone) -> None: ...


class CameraRepository(Protocol):
    """카메라와 캘리브레이션. 기능명세서 §6 `cameras` · API명세서 §4.5"""

    async def list_cameras(self) -> list[dict[str, Any]]: ...

    async def get_homography(self, cam_id: int) -> list[list[float]] | None:
        """3×3 픽셀→지면 변환 행렬. 미캘리브레이션이면 `None`."""
        ...

    async def save_calibration(
        self,
        cam_id: int,
        homography: list[list[float]],
        ref_height_px_at_m: dict[str, Any] | None,
        calibrated_at: datetime,
    ) -> None: ...


class PolicyRepository(Protocol):
    """정책값. 기능명세서 §6 `policies` · API명세서 §4.5

    임계값·타이머는 코드가 아니라 여기서만 읽는다(CLAUDE.md 절대규칙 6).
    """

    async def load(self) -> Policies: ...

    async def patch(self, changes: dict[str, Any]) -> Policies: ...


class VehicleClassRepository(Protocol):
    """클래스별 위험 반경. 기능명세서 §6 `vehicle_classes` · API명세서 §4.5"""

    async def list_vehicle_classes(self) -> list[VehicleClass]: ...

    async def patch(self, class_name: str, changes: dict[str, Any]) -> VehicleClass: ...


class AnomalyRepository(Protocol):
    """이상 탐지 결과와 정상 풀. 기능명세서 §6 `anomalies` · `normal_pool` · FN-AI-04"""

    async def record_anomaly(
        self,
        cam_id: int,
        score: float,
        keyframe_path: str | None,
        detected_at: datetime,
    ) -> int:
        """이상 플래그를 저장하고 id 를 돌려준다. **경고 방송은 발동하지 않는다.**"""
        ...

    async def add_normal_sample(
        self,
        cam_id: int,
        time_bucket: str,
        embedding: list[float],
        sampled_at: datetime,
    ) -> None: ...

    async def nearest_normal_distance(
        self,
        cam_id: int,
        time_bucket: str,
        embedding: list[float],
        k: int,
    ) -> float | None:
        """k-최근접 평균 코사인 거리. `anomaly_score` 의 원천. API명세서 §6.8"""
        ...


class Repository(Protocol):
    """저장소 묶음. 조립 지점이 구현체 하나를 주입한다."""

    @property
    def events(self) -> EventRepository: ...

    @property
    def zones(self) -> ZoneRepository: ...

    @property
    def cameras(self) -> CameraRepository: ...

    @property
    def policies(self) -> PolicyRepository: ...

    @property
    def vehicle_classes(self) -> VehicleClassRepository: ...

    @property
    def anomalies(self) -> AnomalyRepository: ...
