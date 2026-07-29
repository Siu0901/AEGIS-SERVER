"""FN-SYS-03 — 클라우드 장애 격리 (기능명세서 §4.8 · API명세서 §4.6).

요구는 "API 실패 시 실시간 안전 루프에 영향 없이 **분석 기능만 중단 표시**"다.
격리를 말로만 두지 않으려면 두 가지를 잠가야 한다.

1. 클라우드가 죽은 상태에서 **감지 → 확정 → 경고 → 시정**이 끝까지 돈다.
2. 그 실패가 `GET /system/status` 의 `cloud` 절과 §5.3 `system` 에만 나타난다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from aegis_contracts import ComponentSystemMsg, SystemStatus
from aegis_vision.clock import FakeClock
from server.app.main import create_app
from server.domain.cloud_state import CloudRuntime

from .conftest import (
    FakeEventStore,
    FakeMqtt,
    FakePlayer,
    FakePolicyStore,
    FakeRecClient,
    FakeWatcher,
    FakeZoneStore,
    make_alerts,
    make_settings,
)

NOW = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)


def test_cloud_starts_unavailable_rather_than_optimistic() -> None:
    """불러본 적이 없으면 `available: false` · `quota_used: null` 이다.

    "아직 모른다"를 "쓸 수 있다"로 낙관하면, 분석 결과가 비어 있는 이유가 화면에서
    사라진다. `quota_used: 0.0` 은 "한도를 안 썼다"는 **다른 주장**이다(§4.6).
    """
    cloud = CloudRuntime()
    assert cloud.status().available is False
    assert cloud.status().quota_used is None
    assert cloud.state() == "down"


def test_a_failure_is_reported_as_analysis_only() -> None:
    """§5.3 `system` 은 **분석 기능만** 멈췄다고 말한다."""
    cloud = CloudRuntime()
    cloud.mark_ok(NOW, quota_used=0.62)

    message = cloud.mark_failed(NOW, "429 Too Many Requests")

    assert isinstance(message, ComponentSystemMsg)
    assert message.component == "cloud_api"
    assert message.state == "down"
    assert "안전 기능은 계속 동작한다" in message.detail
    # 도달하지 못했으면 사용률을 알 수 없다. 마지막 값을 남기면 화면이 현재로 읽는다.
    assert cloud.status().quota_used is None


def test_only_changes_are_published() -> None:
    """같은 상태를 반복 보고하지 않는다 — 실제 변화가 소음에 묻힌다."""
    cloud = CloudRuntime()
    assert cloud.mark_failed(NOW, "타임아웃") is None  # 이미 down 이다
    assert cloud.mark_ok(NOW) is not None
    assert cloud.mark_ok(NOW) is None


def test_a_high_quota_is_degraded_not_down() -> None:
    """한도가 차오르는 중은 "아직 쓸 수 있으나 곧 끊긴다"이다(§5.3 `ComponentState`)."""
    cloud = CloudRuntime()
    cloud.mark_ok(NOW, quota_used=0.2)
    assert cloud.state() == "ok"
    cloud.mark_ok(NOW, quota_used=0.9)
    assert cloud.state() == "degraded"


def test_the_safety_loop_runs_end_to_end_while_the_cloud_is_down() -> None:
    """★ 클라우드가 죽어 있는 동안 확정 → 경고 → 시정이 끝까지 돈다.

    시나리오 검사(`sim/case_check.py`)와 같은 경로를 쓰되, 여기서는 **클라우드를 죽여
    놓고** 돌린다. 안전 루프가 클라우드를 부르는 곳이 하나라도 있으면 여기서 드러난다.
    """
    from sim.case_check import check_case, run_case

    result = asyncio.run(run_case("normal_resolve"))

    assert check_case("normal_resolve", result) == []
    assert result.metrics.correction_rate == 1.0
    # 방송과 경광등이 실제로 나갔다 — 클라우드와 무관한 경로다.
    assert [sound.filename for sound in result.played] == ["no_helmet.wav"]
    assert len(result.alerts) == 1


def test_system_status_reports_the_cloud_without_touching_the_safety_path() -> None:
    """`GET /system/status` 의 `cloud` 절이 런타임 상태를 그대로 싣는다."""
    clock = FakeClock(NOW)
    app = create_app(
        make_settings(),
        clock,
        rec_client=FakeRecClient(),
        stream_watcher=FakeWatcher({1: "ok", 2: "ok"}),
        events=FakeEventStore(),
        zones=FakeZoneStore(),
        policies=FakePolicyStore(),
        alerts=make_alerts(clock, player=FakePlayer(), mqtt=FakeMqtt()),
    )
    cloud: CloudRuntime = app.state.cloud

    with TestClient(app) as client:
        before = SystemStatus.model_validate(client.get("/api/v1/system/status").json())
        cloud.mark_ok(NOW, quota_used=0.62)
        after = SystemStatus.model_validate(client.get("/api/v1/system/status").json())

    assert before.cloud.available is False
    assert before.cloud.quota_used is None
    assert after.cloud.available is True
    assert after.cloud.quota_used == 0.62
    # 클라우드 상태가 바뀌어도 카메라·엣지·저장소 절은 흔들리지 않는다.
    assert [camera.model_dump() for camera in before.cameras] == [
        camera.model_dump() for camera in after.cameras
    ]


def test_mcu_status_expires_on_its_own() -> None:
    """FN-SYS-01 — 장치 보고가 끊기면 `online: false` 다. 마지막 값을 붙들지 않는다."""
    from aegis_contracts import DeviceStatus
    from server.domain.mcu_state import McuRuntime

    mcu = McuRuntime(stale_after_s=30.0)
    status: Any = DeviceStatus(device="esp32-01", online=True, uptime_s=84210, last_alert=None)

    mcu.apply_status(status, NOW)
    assert mcu.status(NOW).online is True
    assert mcu.status(NOW + timedelta(seconds=31)).online is False
    # 오래된 값을 남기면 화면이 "한참 전에 살아 있었다"를 "지금 살아 있다"로 읽는다.
    assert mcu.status(NOW + timedelta(seconds=31)).last_seen is None
