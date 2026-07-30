"""경고 음원 매핑 API — `GET /alert-sounds` · `PUT /alert-sounds/{violation_type}`.

API명세서 §4.5 · FN-CFG-03

이 API 가 존재하는 이유는 파일명과 등급이 **코드에 없기** 때문이다(절대규칙 6).
그래서 여기서 막아야 하는 것 둘:

1. **`fall` 의 등급을 3 미만으로 내릴 수 없다**(§3). 안전 하한은 설정 대상이 아니다.
2. 등록되지 않은 키를 새로 만들 수 없다. 오타가 새 음원 키가 되면 아무도 재생하지 않는다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from aegis_contracts import ViolationType
from aegis_vision.clock import FakeClock
from server.app.main import create_app

from .conftest import (
    FakeEventStore,
    FakePolicyStore,
    FakeRecClient,
    FakeSoundStore,
    FakeWatcher,
    FakeZoneStore,
    make_alerts,
    make_settings,
)

NOW = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)


def build(sounds: FakeSoundStore | None = None) -> tuple[TestClient, FakeSoundStore]:
    store = sounds or FakeSoundStore()
    clock = FakeClock(NOW)
    app = create_app(
        make_settings(),
        clock,
        rec_client=FakeRecClient(),
        stream_watcher=FakeWatcher({1: "ok", 2: "ok"}),
        events=FakeEventStore(),
        zones=FakeZoneStore([]),
        policies=FakePolicyStore(),
        sounds=store,
        alerts=make_alerts(clock, sounds=store),
    )
    return TestClient(app), store


def test_list_returns_every_mapping_with_level_and_label() -> None:
    client, _ = build()
    with client:
        body = client.get("/api/v1/alert-sounds").json()
    by_type = {item["violation_type"]: item for item in body}
    assert by_type["no_helmet"]["level"] == 2
    assert by_type["fall"]["level"] == 3
    assert by_type["no_helmet"]["label"] == "안전모 미착용 안내"
    # 수동 방송용 키도 같은 테이블에 있다(§4.5 `sound`).
    assert "custom_notice" in by_type


def test_list_includes_disabled_entries() -> None:
    """꺼진 항목을 감추면 설정 화면에서 다시 켤 방법이 없다."""
    client, store = build()
    with client:
        client.put("/api/v1/alert-sounds/proximity", json={"active": False})
        body = client.get("/api/v1/alert-sounds").json()
    entry = next(item for item in body if item["violation_type"] == "proximity")
    assert entry["active"] is False
    # 경고 경로는 여전히 꺼진 것을 보지 않는다.
    assert "proximity" in store.inactive


def test_update_changes_file_level_and_label() -> None:
    client, store = build()
    with client:
        response = client.put(
            "/api/v1/alert-sounds/no_helmet",
            json={"file_path": "custom/no_helmet_ko.wav", "level": 3, "label": "안전모"},
        )
    assert response.status_code == 200
    assert response.json()["level"] == 3
    assert store.mapping["no_helmet"].file_path == "custom/no_helmet_ko.wav"
    assert store.mapping["no_helmet"].label == "안전모"


def test_fall_cannot_be_lowered_below_three() -> None:
    """★ §3 — 쓰러짐은 대상자가 스스로 시정할 수 없어 등급을 낮출 수 없다.

    낮추면 긴급 상황에서 부저가 울리지 않는다. **안전 하한은 설정 대상이 아니다.**
    """
    client, store = build()
    with client:
        response = client.put("/api/v1/alert-sounds/fall", json={"level": 2})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert store.mapping["fall"].level == 3


def test_fall_can_still_be_raised_and_otherwise_edited() -> None:
    """하한이지 고정값이 아니다 — 3 은 유지되고 파일명은 바뀐다."""
    client, store = build()
    with client:
        assert client.put("/api/v1/alert-sounds/fall", json={"level": 3}).status_code == 200
        assert (
            client.put("/api/v1/alert-sounds/fall", json={"file_path": "fall_ko.wav"}).status_code
            == 200
        )
    assert store.mapping["fall"].level == 3
    assert store.mapping["fall"].file_path == "fall_ko.wav"


def test_other_types_can_be_lowered() -> None:
    """하한이 있는 유형은 `fall` 뿐이다. 나머지는 현장 판단으로 조정한다(§3)."""
    client, store = build()
    with client:
        assert client.put("/api/v1/alert-sounds/no_helmet", json={"level": 1}).status_code == 200
    assert store.mapping["no_helmet"].level == 1


def test_unknown_key_is_not_created() -> None:
    """오타가 새 음원 키가 되면 그 키는 아무도 재생하지 않는다."""
    client, store = build()
    with client:
        response = client.put("/api/v1/alert-sounds/no_helmets", json={"level": 2})
    assert response.status_code == 404
    assert "no_helmets" not in store.mapping


def test_empty_patch_is_rejected() -> None:
    client, _ = build()
    with client:
        response = client.put("/api/v1/alert-sounds/no_helmet", json={})
    assert response.status_code == 422


def test_change_reaches_the_alert_path_without_a_restart() -> None:
    """★ FN-CFG-04 — 설정 변경이 재시작 없이 반영된다.

    주기 갱신(60초)만 믿으면 화면에서 등급을 바꾼 뒤 그동안 옛 등급으로 경고가 나간다.
    라우터가 저장 직후 캐시와 상태머신 등급표를 함께 갱신한다.
    """
    client, _ = build()
    with client:
        alerts = client.app.state.alerts  # type: ignore[attr-defined]
        assert alerts.severity_map()[ViolationType.NO_HELMET] == 2
        client.put("/api/v1/alert-sounds/no_helmet", json={"level": 3})
        # 라우터가 캐시를 갱신했으므로 다음 경고는 3 으로 나간다.
        assert alerts.severity_map()[ViolationType.NO_HELMET] == 3
