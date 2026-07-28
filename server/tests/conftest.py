"""서버 테스트 공용 도구.

바깥 프로세스(mediamtx · REC · NTP)에 실제로 붙지 않는다. 붙으면 테스트 결과가
그날 그 기계의 상태에 좌우되고, 그건 검증이 아니라 관측이다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aegis_contracts import (
    EventDetail,
    EventListQuery,
    EventStatus,
    EventSummary,
    Policies,
    RecCameraStatus,
    RecStatusResponse,
    RecStorageStatus,
    ViolationType,
    Zone,
)
from aegis_contracts.enums import StreamState
from server.app.config import ServerSettings
from server.infra.rec_client import RecUnavailableError

__all__ = [
    "REC_STATUS",
    "FakeEventStore",
    "FakePolicyStore",
    "FakeRecClient",
    "FakeWatcher",
    "FakeZoneStore",
    "make_settings",
    "rec_status_with",
]

#: API명세서 §4.7 `GET /status` 예시 그대로.
REC_STATUS = RecStatusResponse(
    cameras=[
        RecCameraStatus(
            cam_id=1,
            recording=True,
            last_segment_at=datetime(2026, 8, 14, 5, 37, 10, tzinfo=UTC),
        ),
        RecCameraStatus(
            cam_id=2,
            recording=True,
            last_segment_at=datetime(2026, 8, 14, 5, 37, 10, tzinfo=UTC),
        ),
    ],
    storage=RecStorageStatus(
        total_gb=500,
        used_gb=378,
        free_gb=122,
        retention_days=7,
        oldest_segment_at=datetime(2026, 8, 7, 5, 37, 0, tzinfo=UTC),
    ),
)


def rec_status_with(*, recording: dict[int, bool]) -> RecStatusResponse:
    """카메라별 녹화 여부만 바꾼 §4.7 응답.

    REC 이 녹화하지 않는 카메라는 **목록에 아예 없다.** 그래서 `cam_id` 를 키로 받는다.
    """
    return RecStatusResponse(
        cameras=[
            RecCameraStatus(
                cam_id=cam_id,
                recording=is_recording,
                last_segment_at=datetime(2026, 8, 14, 5, 37, 10, tzinfo=UTC),
            )
            for cam_id, is_recording in sorted(recording.items())
        ],
        storage=REC_STATUS.storage,
    )


def make_settings(**overrides: object) -> ServerSettings:
    """개발자의 `.env` 를 읽지 않는 설정. NTP 확인도 끈다(네트워크 접근 금지)."""
    fields: dict[str, object] = {
        "cam_ids": [1, 2],
        "mediamtx_api": "http://127.0.0.1:59997",
        "recorder_base": "http://127.0.0.1:59100",
        "ntp_server": "",
        **overrides,
    }
    return ServerSettings(_env_file=None, **fields)  # type: ignore[arg-type]


class FakeWatcher:
    """`StreamObserver` 대역."""

    def __init__(self, states: dict[int, StreamState]) -> None:
        self._states = dict(states)
        self.started = False
        self.stopped = False

    def states(self) -> dict[int, StreamState]:
        return dict(self._states)

    def set(self, cam_id: int, state: StreamState) -> None:
        self._states[cam_id] = state

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class FakeRecClient:
    """`StorageReader` 대역. `available=False` 면 REC 이 죽은 상황을 흉내 낸다.

    `sequence` 를 주면 부를 때마다 **다른 응답**을 돌려준다(마지막 값이 이후 반복).
    한 요청 안에서 REC 을 두 번 부르면 값이 어긋난다는 것을 드러내기 위한 장치다.
    """

    def __init__(
        self,
        *,
        available: bool = True,
        payload: RecStatusResponse | None = None,
        sequence: list[RecStatusResponse] | None = None,
    ) -> None:
        self.available = available
        self.payload = payload or REC_STATUS
        self.sequence = list(sequence or [])
        self.calls = 0

    async def status(self) -> RecStatusResponse:
        self.calls += 1
        if not self.available:
            msg = "REC 에 닿지 못했다 (테스트)"
            raise RecUnavailableError(msg)
        if self.sequence:
            return self.sequence.pop(0) if len(self.sequence) > 1 else self.sequence[0]
        return self.payload

    async def aclose(self) -> None:
        return None


class FakeEventStore:
    """`EventStore` · `EventReader` 대역. 메모리 안의 이벤트 목록 하나다.

    DB 를 띄우지 않는 이유는 속도 때문만이 아니다 — FN-EVT-01 이 검증하는 것은
    "같은 트랙·같은 유형이면 새로 만들지 않는다"는 **판단**이고, 그 판단은 저장
    매체와 무관해야 한다.
    """

    def __init__(self, items: list[EventDetail] | None = None) -> None:
        self.items: list[EventDetail] = list(items or [])
        self.created: list[EventDetail] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.fail_with: Exception | None = None

    async def find_open_events(
        self, cam_id: int, track_id: int
    ) -> dict[ViolationType, EventSummary]:
        open_statuses = {
            EventStatus.CANDIDATE,
            EventStatus.ACTIVE,
            EventStatus.ALERTED,
            EventStatus.RE_ALERTED,
            EventStatus.LOST,
        }
        return {
            item.violation_type: EventSummary.model_validate(
                item.model_dump(include=set(EventSummary.model_fields))
            )
            for item in self.items
            if item.cam_id == cam_id and item.track_id == track_id and item.status in open_statuses
        }

    async def next_event_id(self, at: datetime) -> str:
        from server.domain.event_machine import format_event_id

        return format_event_id(at, len(self.items) + 1)

    async def create(self, event: EventDetail) -> None:
        self.items.append(event)
        self.created.append(event)

    async def update(self, event_id: str, changes: dict[str, Any]) -> None:
        self.updates.append((event_id, changes))
        for index, item in enumerate(self.items):
            if item.event_id == event_id:
                self.items[index] = item.model_copy(update=changes)

    async def list_events(self, query: EventListQuery) -> tuple[list[EventSummary], str | None]:
        if self.fail_with is not None:
            raise self.fail_with
        return [
            EventSummary.model_validate(item.model_dump(include=set(EventSummary.model_fields)))
            for item in self.items
        ], None

    async def get(self, event_id: str) -> EventDetail | None:
        if self.fail_with is not None:
            raise self.fail_with
        return next((item for item in self.items if item.event_id == event_id), None)


class FakeZoneStore:
    """`ZoneReader` 대역."""

    def __init__(self, zones: list[Zone] | None = None) -> None:
        self.zones = list(zones or [])
        self.fail_with: Exception | None = None

    async def list_zones(self, cam_id: int | None = None) -> list[Zone]:
        if self.fail_with is not None:
            raise self.fail_with
        return [zone for zone in self.zones if cam_id is None or zone.cam_id == cam_id]


class FakePolicyStore:
    """`PolicyReader` 대역."""

    def __init__(self, policies: Policies | None = None) -> None:
        self.policies = policies or Policies()
        self.fail_with: Exception | None = None

    async def load(self) -> Policies:
        if self.fail_with is not None:
            raise self.fail_with
        return self.policies
