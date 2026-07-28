"""`GET /api/v1/system/status` (API명세서 §4.6 · FN-SYS-01).

핵심은 두 가지다.

* `storage` 가 **REC 값**인가 — 서버 로컬 디스크를 조회해 채우면 안 된다
* 관측한 적 없는 값이 `null` 인가 — 0 으로 채우면 장애와 구분되지 않는다
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from aegis_contracts import SystemStatus
from server.app.main import create_app

from .conftest import REC_STATUS, FakeRecClient, FakeWatcher, make_settings


def _client(watcher: FakeWatcher, rec: FakeRecClient) -> TestClient:
    app = create_app(make_settings(), rec_client=rec, stream_watcher=watcher)
    return TestClient(app)


def test_response_matches_spec_schema() -> None:
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, FakeRecClient()) as client:
        response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    # 계약으로 되읽어 §4.6 과 어긋난 필드가 없는지 본다(`extra="forbid"`).
    status = SystemStatus.model_validate(response.json())
    assert [camera.cam_id for camera in status.cameras] == [1, 2]


def test_main_state_comes_from_the_stream_watcher() -> None:
    watcher = FakeWatcher({1: "ok", 2: "reconnecting"})
    with _client(watcher, FakeRecClient()) as client:
        payload = client.get("/api/v1/system/status").json()

    states = {camera["cam_id"]: camera["main_state"] for camera in payload["cameras"]}
    assert states == {1: "ok", 2: "reconnecting"}


def test_sub_state_is_down_and_fps_is_null_without_an_edge() -> None:
    """엣지가 없으면 서브 스트림을 관측하는 주체가 없다(§4.6).

    `fps: 0.0` 으로 채우면 "엣지가 도는데 처리량이 0" 과 구분되지 않는다.
    """
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, FakeRecClient()) as client:
        payload = client.get("/api/v1/system/status").json()

    for camera in payload["cameras"]:
        assert camera["sub_state"] == "down"
        assert camera["fps"] is None
    assert payload["edge"]["online"] is False
    assert payload["edge"]["msg_rejected_total"] == 0
    assert payload["time_sync"]["edge_offset_ms"] is None


def test_storage_is_passed_through_from_rec() -> None:
    """서버가 자기 디스크를 조회하지 않는다(§4.7).

    운용 시 녹화 디스크는 엣지 SSD 다. 서버 노트북의 여유 공간을 실으면 엣지가
    가득 차도 대시보드는 여유롭다고 표시한다.
    """
    rec = FakeRecClient()
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, rec) as client:
        payload = client.get("/api/v1/system/status").json()

    assert payload["storage"]["free_gb"] == REC_STATUS.storage.free_gb
    assert payload["storage"]["retention_days"] == REC_STATUS.storage.retention_days
    assert rec.calls >= 1


def test_storage_is_null_when_rec_is_unreachable() -> None:
    """REC 이 죽었을 때 서버 디스크 값으로 대신 채우지 않는다."""
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, FakeRecClient(available=False)) as client:
        response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["storage"] == {"retention_days": None, "free_gb": None}


def test_watcher_lifecycle_is_tied_to_the_app() -> None:
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, FakeRecClient()) as client:
        client.get("/health")
        assert watcher.started
    assert watcher.stopped
