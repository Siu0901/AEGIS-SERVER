"""서버 테스트 공용 도구.

바깥 프로세스(mediamtx · REC · NTP)에 실제로 붙지 않는다. 붙으면 테스트 결과가
그날 그 기계의 상태에 좌우되고, 그건 검증이 아니라 관측이다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aegis_contracts import RecCameraStatus, RecStatusResponse, RecStorageStatus
from aegis_contracts.enums import StreamState
from server.app.config import ServerSettings
from server.infra.rec_client import RecUnavailableError

__all__ = ["REC_STATUS", "FakeRecClient", "FakeWatcher", "make_settings"]

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
    """`StorageReader` 대역. `available=False` 면 REC 이 죽은 상황을 흉내 낸다."""

    def __init__(self, *, available: bool = True, payload: RecStatusResponse | None = None) -> None:
        self.available = available
        self.payload = payload or REC_STATUS
        self.calls = 0

    async def status(self) -> RecStatusResponse:
        self.calls += 1
        if not self.available:
            msg = "REC 에 닿지 못했다 (테스트)"
            raise RecUnavailableError(msg)
        return self.payload

    async def aclose(self) -> None:
        return None
