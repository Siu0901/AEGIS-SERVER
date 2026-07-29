"""`GET /api/v1/system/status` (API명세서 §4.6 · FN-SYS-01).

핵심은 두 가지다.

* `storage` 가 **REC 값**인가 — 서버 로컬 디스크를 조회해 채우면 안 된다
* 관측한 적 없는 값이 `null` 인가 — 0 으로 채우면 장애와 구분되지 않는다
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from aegis_contracts import SystemStatus
from server.app.main import create_app

from .conftest import (
    REC_STATUS,
    FakeEventStore,
    FakePolicyStore,
    FakeRecClient,
    FakeWatcher,
    make_settings,
    rec_status_with,
)


def _client(watcher: FakeWatcher, rec: FakeRecClient) -> TestClient:
    # 저장소도 가짜를 넣는다 — 기동 시 상태머신이 진행 중 이벤트와 정책값을 읽으므로
    # 주입하지 않으면 테스트가 실제 DB 에 붙는다(conftest 서두의 원칙).
    app = create_app(
        make_settings(),
        rec_client=rec,
        stream_watcher=watcher,
        events=FakeEventStore(),
        policies=FakePolicyStore(),
    )
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


def test_sub_state_is_down_and_gauges_are_null_without_an_edge() -> None:
    """엣지가 없으면 서브 스트림과 게이지를 관측하는 주체가 없다(§4.6 null 규약).

    `fps: 0.0` 으로 채우면 "엣지가 도는데 처리량이 0" 과 구분되지 않는다.
    `sub_state` 만 예외로 `"down"` 이다 — `StreamState` 에 "모름"이 없고 연결되지
    않은 것은 사실이기 때문이다.
    """
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, FakeRecClient()) as client:
        payload = client.get("/api/v1/system/status").json()

    for camera in payload["cameras"]:
        assert camera["sub_state"] == "down"
        assert camera["fps"] is None
    assert payload["edge"]["online"] is False
    assert payload["edge"]["gpu_util"] is None
    assert payload["edge"]["cls_cache_hit_rate"] is None
    assert payload["edge"]["depth_calls_per_min"] is None
    assert payload["cloud"]["quota_used"] is None
    assert payload["time_sync"]["edge_offset_ms"] is None


def test_msg_rejected_total_starts_at_zero_not_null() -> None:
    """서버가 직접 세는 값이라 관측 주체가 항상 있다(§4.6 · FN-SYS-06).

    여기까지 `null` 로 두면 "거부된 메시지가 없다"를 화면이 표시할 수 없게 된다.
    """
    watcher = FakeWatcher({1: "ok"})
    with _client(watcher, FakeRecClient()) as client:
        payload = client.get("/api/v1/system/status").json()

    assert payload["edge"]["msg_rejected_total"] == 0


def test_storage_is_passed_through_from_rec_with_all_five_fields() -> None:
    """서버가 자기 디스크를 조회하지 않는다(§4.7).

    운용 시 녹화 디스크는 엣지 SSD 다. 서버 노트북의 여유 공간을 실으면 엣지가
    가득 차도 대시보드는 여유롭다고 표시한다. §4.6 과 §4.7 의 `storage` 는 같은
    5필드이므로 골라 담지 않고 그대로 옮긴다.
    """
    rec = FakeRecClient()
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, rec) as client:
        payload = client.get("/api/v1/system/status").json()

    assert payload["storage"] == REC_STATUS.storage.model_dump(mode="json")
    assert rec.calls >= 1


def test_storage_is_null_when_rec_is_unreachable() -> None:
    """REC 이 죽었을 때 서버 디스크 값으로 대신 채우지 않는다."""
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, FakeRecClient(available=False)) as client:
        response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["storage"] == {
        "total_gb": None,
        "used_gb": None,
        "free_gb": None,
        "retention_days": None,
        "oldest_segment_at": None,
    }


def test_recording_comes_from_rec_not_from_the_stream_state() -> None:
    """§4.6 `cameras[].recording` 은 REC 의 §4.7 값을 그대로 전달한다.

    메인 스트림이 살아 있다고 녹화 중인 것이 아니다 — 라이브 재스트리밍과 녹화는
    다른 프로세스다. 추론으로 그리면 REC 이 그 카메라만 놓쳤을 때 화면은 계속
    녹화 중이라고 말한다.
    """
    rec = FakeRecClient(payload=rec_status_with(recording={1: True, 2: False}))
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, rec) as client:
        payload = client.get("/api/v1/system/status").json()

    states = {camera["cam_id"]: camera["recording"] for camera in payload["cameras"]}
    assert states == {1: True, 2: False}


def test_recording_is_null_when_rec_is_unreachable() -> None:
    """REC 미도달은 "녹화하지 않는다"가 아니라 "알 수 없다"다(§4.6 null 규약).

    `false` 로 채우면 REC 이 살아 있는데 그 카메라만 녹화가 멈춘 상황과 구분되지 않는다.
    """
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, FakeRecClient(available=False)) as client:
        payload = client.get("/api/v1/system/status").json()

    assert [camera["recording"] for camera in payload["cameras"]] == [None, None]


def test_recording_is_null_for_a_camera_rec_does_not_report() -> None:
    """REC 이 녹화하지 않는 카메라는 목록에 없다. 없는 것을 `false` 로 단정하지 않는다."""
    rec = FakeRecClient(payload=rec_status_with(recording={1: True}))
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, rec) as client:
        payload = client.get("/api/v1/system/status").json()

    states = {camera["cam_id"]: camera["recording"] for camera in payload["cameras"]}
    assert states == {1: True, 2: None}


def test_storage_and_recording_come_from_one_snapshot() -> None:
    """`storage` 와 `recording` 을 **한 응답에서 함께** 꺼낸다.

    REC 을 두 번 부르면 그 사이에 REC 이 죽었을 때 "녹화 중인데 저장소는 응답 없음"
    같은 어긋난 조합이 한 화면에 나온다. 호출을 셀 수는 없다 — `_watch_storage`
    (생존 감시)가 배경에서 같은 API 를 부르기 때문이다. 그래서 부른 횟수가 아니라
    **두 값의 짝이 맞는지**를 본다.
    """
    first = rec_status_with(recording={1: True})
    second = rec_status_with(recording={1: False})
    second = second.model_copy(update={"storage": second.storage.model_copy(update={"free_gb": 7})})

    rec = FakeRecClient(sequence=[first, second])
    watcher = FakeWatcher({1: "ok"})
    with _client(watcher, rec) as client:
        payload = client.get("/api/v1/system/status").json()

    recording = payload["cameras"][0]["recording"]
    free_gb = payload["storage"]["free_gb"]
    assert (recording, free_gb) in {(True, first.storage.free_gb), (False, 7)}


def test_watcher_lifecycle_is_tied_to_the_app() -> None:
    watcher = FakeWatcher({1: "ok", 2: "ok"})
    with _client(watcher, FakeRecClient()) as client:
        client.get("/health")
        assert watcher.started
    assert watcher.stopped
