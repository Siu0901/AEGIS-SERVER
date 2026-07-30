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

from collections.abc import Mapping
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
from server.domain.alerts import SoundEntry
from server.domain.metrics import MetricsRow

__all__ = [
    "AnomalyRepository",
    "CameraRepository",
    "EventRepository",
    "PolicyRepository",
    "Repository",
    "SoundRepository",
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

    async def find_open_all(self) -> list[EventSummary]:
        """종결되지 않은 이벤트 전량. 서버 재시작 시 상태머신 복구에 쓴다.

        복구하지 않으면 그 이벤트들은 어떤 전이도 받지 못하고 시정률 분모에
        영원히 미해소로 남는다.
        """
        ...

    async def metrics_rows(
        self,
        from_: datetime | None,
        to: datetime | None,
    ) -> list[MetricsRow]:
        """지표 집계에 필요한 최소 정보. FN-SYS-04 · FN-SYS-05

        무엇이 분자이고 무엇이 분모인지는 저장소가 정하지 않는다 —
        `server/domain/metrics.py` 하나에만 둔다(§6.7).
        """
        ...

    async def find_due_clip_jobs(self, now: datetime, delay_s: float) -> list[str]:
        """실행 시각이 지난 `clip_status = pending` 이벤트 ID들. FN-REC-03

        `delay_s` 는 `clip_post_roll_s + margin` 이다. 확정 시각에 이 시간을 더한 때가
        잡의 실행 시각이며, **그 전에 부르면 사후 구간이 아직 녹화되지 않았다.**

        큐를 따로 두지 않고 이 조회가 큐 역할을 한다. 서버가 죽어도 예약은 DB 에 남아
        있으므로, 재시작 뒤 이 질의 한 번이 곧 복구다(기능명세서 §4.4).
        """
        ...

    async def count_repeat_7d(
        self,
        cam_id: int,
        track_id: int,
        zone_id: str | None,
        at: datetime,
    ) -> int:
        """동일 트랙·구역의 최근 7일 유사 이벤트 수. FN-EVT-06

        기준 시각 `at` 을 받는다. 구현이 시스템 시계를 읽으면 절대규칙 1이 깨지고,
        무엇보다 어제 본 목록과 오늘 본 목록에서 같은 이벤트의 숫자가 달라진다.
        """
        ...

    async def create(self, event: EventDetail) -> None: ...

    async def update(self, event_id: str, changes: Mapping[str, Any]) -> None:
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


class SoundRepository(Protocol):
    """위반 유형·수동 방송 이름 → 음원 파일·등급·표시 이름.

    기능명세서 §6 `alert_sounds` · FN-ALM-01 · FN-ALM-04 · FN-CFG-03

    **코드에 파일명과 등급을 박지 않기 위한 경계다**(절대규칙 6). 음원과 등급 교체가
    배포가 아니라 설정 변경이어야 설치 현장마다 다른 안내 문구와 경보 강도를 쓸 수 있다.
    """

    async def load_sounds(self) -> dict[str, SoundEntry]:
        """`{violation_type: SoundEntry}`. **꺼진(`active = false`) 항목은 빼고** 돌려준다."""
        ...


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
    def sounds(self) -> SoundRepository: ...

    @property
    def vehicle_classes(self) -> VehicleClassRepository: ...

    @property
    def anomalies(self) -> AnomalyRepository: ...
