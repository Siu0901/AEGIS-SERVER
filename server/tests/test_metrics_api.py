"""`GET /metrics/summary` 와 `PATCH /events/{id}` (API명세서 §4.2 · §4.1).

시정률과 판정 불가율은 **항상 함께** 나가야 한다(FN-SYS-04/05). 시정률만 떼어
보여주면 추적이 끊긴 이벤트가 몇 건인지 알 수 없어 그 숫자를 검증할 수 없다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from aegis_contracts import EventDetail, EventStatus, MetricsSummary, ViolationType
from aegis_vision.clock import FakeClock
from server.app.main import create_app

from .conftest import (
    FakeEventStore,
    FakePolicyStore,
    FakeRecClient,
    FakeWatcher,
    FakeZoneStore,
    make_alerts,
    make_settings,
)

NOW = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)
EARLIER = datetime(2026, 8, 14, 3, 0, 0, tzinfo=UTC)


def event(
    event_id: str,
    status: EventStatus,
    *,
    violation: ViolationType = ViolationType.NO_HELMET,
    resolution_sec: int | None = None,
    alert_suppressed: bool = False,
) -> EventDetail:
    body: dict[str, Any] = {
        "event_id": event_id,
        "cam_id": 1,
        "track_id": 3,
        "violation_type": violation,
        "zone_id": "forklift_lane",
        "status": status,
        "detected_at": EARLIER,
        "confirmed_at": EARLIER,
        "alerted_at": EARLIER,
        "last_alerted_at": EARLIER,
        "note": None,
        "resolved_at": None,
        "resolution_sec": resolution_sec,
        "alert_count": 1,
        "min_distance_m": None,
        "posture": "standing",
        "repeat_count_7d": 0,
        "thumbnail_url": None,
        "clip_url": None,
        "keyframe_urls": [],
        "helmet_conf": 0.88,
        "stillness_s": None,
        "height_ratio": None,
        "depth_verified": None,
        "nearby_snapshot": [],
        "llm_analysis": None,
        "regulation_refs": [],
        "similar_incidents": [],
        "timeline": [],
        "clip_status": None,
        "clip_error": None,
        "alert_suppressed": alert_suppressed,
    }
    return EventDetail.model_validate(body)


def build(store: FakeEventStore) -> TestClient:
    app = create_app(
        make_settings(),
        FakeClock(NOW),
        rec_client=FakeRecClient(),
        stream_watcher=FakeWatcher({1: "ok", 2: "ok"}),
        events=store,
        zones=FakeZoneStore(),
        policies=FakePolicyStore(),
        alerts=make_alerts(FakeClock(NOW)),
    )
    return TestClient(app)


def test_summary_reports_both_numbers_together() -> None:
    """`방송 후 시정률 87% (판정 불가 5%)` — 둘을 갈라 놓지 않는다(§6.7 표기 규칙)."""
    store = FakeEventStore(
        [
            event("EV-1", EventStatus.RESOLVED, resolution_sec=12),
            event("EV-2", EventStatus.ALERTED),
            event("EV-3", EventStatus.EXPIRED),
        ]
    )
    with build(store) as client:
        response = client.get("/api/v1/metrics/summary")

    assert response.status_code == 200
    # 계약으로 되읽어 §4.2 와 어긋난 필드가 없는지 본다(`extra="forbid"`).
    summary = MetricsSummary.model_validate(response.json())
    assert summary.period == "today"
    assert summary.resolved == 1
    assert summary.unresolved == 1
    assert summary.correction_rate == 0.5
    # `expired` 는 시정률 분모에서 빠지고 판정 불가로 따로 센다.
    assert summary.undetermined == 1
    assert summary.undetermined_rate == 1 / 3
    assert summary.total_violations == 3


def test_summary_without_a_store_is_503_not_zeroes() -> None:
    """ "이벤트가 없다"와 "저장소에 닿지 못했다"는 화면에서 구분되어야 한다."""
    app = create_app(
        make_settings(),
        FakeClock(NOW),
        rec_client=FakeRecClient(),
        stream_watcher=FakeWatcher({1: "ok"}),
        events=FakeEventStore(),
        zones=FakeZoneStore(),
        policies=FakePolicyStore(),
        alerts=make_alerts(FakeClock(NOW)),
    )
    # 조립이 잘못된 상황을 만든다. 저장소를 아예 주지 않으면 실제 DB 엔진이 만들어져
    # 테스트가 바깥 프로세스에 붙는다(conftest 서두의 원칙).
    app.state.event_service = None
    with TestClient(app) as client:
        response = client.get("/api/v1/metrics/summary")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_force_resolve_closes_the_event() -> None:
    """FN-EVT-05 — 시스템이 놓친 시정을 관리자가 종결한다."""
    store = FakeEventStore([event("EV-1", EventStatus.ALERTED)])
    with build(store) as client:
        response = client.patch("/api/v1/events/EV-1", json={"force_resolve": True})

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert response.json()["resolution_sec"] is not None


def test_false_positive_is_recorded_without_changing_the_status() -> None:
    """오탐 표시는 상태를 바꾸지 않는다. 지표에서 빠지는 것으로 충분하다(§6.7)."""
    store = FakeEventStore([event("EV-1", EventStatus.ALERTED)])
    with build(store) as client:
        response = client.patch(
            "/api/v1/events/EV-1",
            json={"is_false_positive": True, "note": "안전모를 든 채 이동 중이었음"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "alerted"
    assert store.updates[0][1]["is_false_positive"] is True


def test_patching_a_missing_event_is_404() -> None:
    with build(FakeEventStore()) as client:
        response = client.patch("/api/v1/events/EV-없음", json={"force_resolve": True})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
