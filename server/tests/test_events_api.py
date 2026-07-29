"""`GET /events` · `GET /zones` · `GET /policies` (API명세서 §4.1 · §4.5).

세 라우터가 공통으로 지키는 것: **저장소에 닿지 못한 것을 "없다"로 답하지 않는다.**
빈 배열이나 기본값으로 덮으면 화면은 정상으로 보이는데 사실만 틀린다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from aegis_contracts import EventDetail, EventListResponse, Policies, ViolationType, Zone
from aegis_vision.clock import FakeClock
from server.app.main import create_app
from server.domain.event_machine import build_candidate_event

from .conftest import (
    FakeEventStore,
    FakePolicyStore,
    FakeRecClient,
    FakeWatcher,
    FakeZoneStore,
    make_settings,
)
from .test_event_machine import candidate

ZONE = Zone(
    zone_id="forklift_lane",
    cam_id=1,
    name="지게차 통행로",
    polygon_m=[(2.0, 6.0), (7.0, 6.0), (7.0, 11.0), (2.0, 11.0)],
    buffer_m=0.3,
    active=True,
)


def build(
    *,
    events: FakeEventStore | None = None,
    zones: FakeZoneStore | None = None,
    policies: FakePolicyStore | None = None,
) -> TestClient:
    app = create_app(
        make_settings(),
        FakeClock(datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)),
        rec_client=FakeRecClient(),
        stream_watcher=FakeWatcher({1: "ok", 2: "ok"}),
        events=events or FakeEventStore(),
        zones=zones or FakeZoneStore([ZONE]),
        policies=policies or FakePolicyStore(),
    )
    return TestClient(app)


def sample_event(event_id: str = "EV-20260814-0231") -> EventDetail:
    return build_candidate_event(candidate(), ViolationType.NO_HELMET, event_id)


# --------------------------------------------------------------------------
# §4.1 events
# --------------------------------------------------------------------------


def test_empty_list_matches_the_spec_envelope() -> None:
    with build() as client:
        response = client.get("/api/v1/events")
    assert response.status_code == 200
    assert EventListResponse.model_validate(response.json()).items == []


def test_listed_event_matches_the_spec_schema() -> None:
    with build(events=FakeEventStore([sample_event()])) as client:
        payload = client.get("/api/v1/events").json()

    listing = EventListResponse.model_validate(payload)
    assert [item.event_id for item in listing.items] == ["EV-20260814-0231"]
    # M2 의 이벤트는 확정되지 않았다. 그 사실이 응답에 그대로 보여야 한다.
    assert listing.items[0].status == "candidate"
    assert listing.items[0].confirmed_at is None


def test_missing_event_answers_with_the_spec_error_envelope() -> None:
    """§1.4 는 `{"error": {...}}` 다. FastAPI 기본 `{"detail": ...}` 이 아니다."""
    with build() as client:
        response = client.get("/api/v1/events/EV-없는것")

    assert response.status_code == 404
    body: dict[str, Any] = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["detail"] == {"event_id": "EV-없는것"}


def test_broken_cursor_is_an_error_not_a_silent_first_page() -> None:
    """조용히 첫 장으로 되돌리면 클라이언트가 같은 장을 무한히 돈다."""
    store = FakeEventStore()
    store.fail_with = ValueError("커서를 해석할 수 없다: 'zzz'")
    with build(events=store) as client:
        response = client.get("/api/v1/events", params={"cursor": "zzz"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unreachable_store_is_503_not_an_empty_list() -> None:
    store = FakeEventStore()
    store.fail_with = OSError("connection refused")
    with build(events=store) as client:
        response = client.get("/api/v1/events")

    assert response.status_code == 503
    assert "닿지 못했" in response.json()["error"]["message"]


# --------------------------------------------------------------------------
# §4.5 zones · policies
# --------------------------------------------------------------------------


def test_zones_are_returned_in_the_get_zones_shape() -> None:
    """대시보드가 이 응답을 그대로 캐시하고 `zone_updated`(§5.4)로 갱신한다."""
    with build() as client:
        payload = client.get("/api/v1/zones").json()

    assert [Zone.model_validate(item) for item in payload] == [ZONE]


def test_unreachable_zone_store_is_503_not_an_empty_polygon_list() -> None:
    """빈 배열로 답하면 대시보드가 금지구역을 지운 채로 그린다."""
    zones = FakeZoneStore()
    zones.fail_with = OSError("connection refused")
    with build(zones=zones) as client:
        response = client.get("/api/v1/zones")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_policies_carry_the_overlay_buffer_keys() -> None:
    """프론트가 지연 버퍼를 여기서 읽는다 — 값을 코드에 적지 않는다(절대규칙 6)."""
    with build() as client:
        payload = client.get("/api/v1/policies").json()

    policies = Policies.model_validate(payload)
    assert policies.overlay_buffer_webrtc_ms == 300.0
    assert policies.overlay_buffer_hls_ms == 2800.0
    assert policies.overlay_stale_ms == 1000.0


def test_unreachable_policy_store_does_not_fall_back_to_contract_defaults() -> None:
    """계약 기본값은 **시드의 원천**이지 런타임 값이 아니다. 현장에서 조정한 값과 다를 수 있다."""
    policies = FakePolicyStore()
    policies.fail_with = OSError("connection refused")
    with build(policies=policies) as client:
        response = client.get("/api/v1/policies")

    assert response.status_code == 503
