"""설정 API — 캘리브레이션 · 구역 편집 · 임계값 · 위험 반경.

API명세서 §4.5 · FN-CFG-01 · 02 · 04 · 05

이 화면이 만드는 것은 **좌표계 그 자체**다. 그래서 여기서 지켜야 하는 것:

1. 잘못 찍은 4점을 저장하지 않는다 — 조용히 통과하면 모든 거리·구역 판정이 틀어진다
2. 재투영 오차를 돌려준다 — 잘못 찍었는지 알 수 있는 유일한 수단이다
3. 캘리브레이션이 바뀌면 그 카메라의 모든 구역에 `zone_updated` 를 발행한다(§5.4)
4. 캘리브레이션 없이 그린 폴리곤은 저장하지 않는다 — 픽셀을 미터인 척 저장할 수 없다
5. 정책 변경이 **재시작 없이** 상태머신에 반영된다(FN-CFG-04)
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aegis_contracts import Zone, ZoneUpdatedMsg
from aegis_vision.clock import FakeClock
from server.app.main import create_app
from server.infra.clip import ClipService

from .conftest import (
    FakeCameraStore,
    FakeEventStore,
    FakePolicyStore,
    FakeRecClient,
    FakeSoundStore,
    FakeVehicleClassStore,
    FakeWatcher,
    FakeZoneStore,
    make_alerts,
    make_settings,
)
from .test_clip_service import StubRec

NOW = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)

#: API명세서 §4.5 예시의 4점 그대로.
SPEC_POINTS: list[dict[str, Any]] = [
    {"px": [0.21, 0.83], "m": [0.0, 0.0]},
    {"px": [0.68, 0.80], "m": [5.0, 0.0]},
    {"px": [0.75, 0.55], "m": [5.0, 5.0]},
    {"px": [0.28, 0.57], "m": [0.0, 5.0]},
]

LANE = Zone(
    zone_id="forklift_lane",
    cam_id=1,
    name="지게차 통행로",
    polygon_m=[(2.0, 6.0), (7.0, 6.0), (7.0, 11.0), (2.0, 11.0)],
    buffer_m=0.3,
    active=True,
)


class Hub:
    """`DashboardHub` 대역 — 발행된 §5 메시지를 모은다."""

    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def broadcast(self, message: Any) -> None:
        self.messages.append(message)


def build(
    *,
    zones: FakeZoneStore | None = None,
    cameras: FakeCameraStore | None = None,
    policies: FakePolicyStore | None = None,
    vehicles: FakeVehicleClassStore | None = None,
    tmp_path: Path | None = None,
) -> tuple[TestClient, dict[str, Any]]:
    clock = FakeClock(NOW)
    events = FakeEventStore()
    clips = ClipService(
        rec=StubRec(),
        store=events,
        clock=clock,
        media_root=tmp_path or Path(tempfile.mkdtemp(prefix="aegis-settings-")),
    )
    parts: dict[str, Any] = {
        "zones": zones or FakeZoneStore([LANE]),
        "cameras": cameras or FakeCameraStore(),
        "policies": policies or FakePolicyStore(),
        "vehicles": vehicles or FakeVehicleClassStore(),
        "hub": Hub(),
        "clips": clips,
    }
    app = create_app(
        make_settings(),
        clock,
        rec_client=FakeRecClient(),
        stream_watcher=FakeWatcher({1: "ok", 2: "ok"}),
        events=events,
        clips=clips,
        zones=parts["zones"],
        policies=parts["policies"],
        sounds=FakeSoundStore(),
        cameras=parts["cameras"],
        vehicle_classes=parts["vehicles"],
        alerts=make_alerts(clock),
    )
    client = TestClient(app)
    # 발행 통로를 가짜로 바꿔 `zone_updated` 를 눈으로 본다. 조립 뒤에 바꾸는 이유는
    # 라우터가 `app.state.hub` 를 통해서만 발행하기 때문이다.
    app.state.hub = parts["hub"]
    return client, parts


# --------------------------------------------------------------------------
# FN-CFG-01 캘리브레이션
# --------------------------------------------------------------------------


def test_calibration_returns_matrix_and_reprojection_error() -> None:
    """§4.5 — 응답 세 필드. **재투영 오차가 없으면 잘못 찍었는지 알 수 없다.**"""
    client, parts = build()
    with client:
        response = client.post("/api/v1/cameras/1/calibration", json={"points": SPEC_POINTS})
    assert response.status_code == 200
    body = response.json()
    assert len(body["homography"]) == 3
    # 4점이면 자유도가 정확히 맞으므로 재현 오차가 0이다.
    assert body["reprojection_error_m"] < 1e-6
    assert body["ref_height_calibrated"] is False
    assert parts["cameras"].homography[1] == body["homography"]
    assert parts["cameras"].calibrated_at[1] == NOW


def test_reference_person_is_recorded() -> None:
    client, parts = build()
    with client:
        response = client.post(
            "/api/v1/cameras/1/calibration",
            json={
                "points": SPEC_POINTS,
                "reference_person": {"px_height": 0.42, "at_m": [2.5, 3.0]},
            },
        )
    assert response.json()["ref_height_calibrated"] is True
    assert parts["cameras"].reference[1] == {"px_height": 0.42, "at_m": [2.5, 3.0]}


def test_three_points_are_rejected() -> None:
    """자유도가 8이라 4점이 필요하다. 부족한 채 저장하면 좌표계가 성립하지 않는다."""
    client, parts = build()
    with client:
        response = client.post("/api/v1/cameras/1/calibration", json={"points": SPEC_POINTS[:3]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert 1 not in parts["cameras"].homography


def test_collinear_points_are_rejected() -> None:
    """통로 한쪽 선을 따라 네 점을 찍는 실수. 행렬은 풀리지만 아무 의미가 없다."""
    collinear = [
        {"px": [0.10, 0.80], "m": [0.0, 0.0]},
        {"px": [0.30, 0.80], "m": [2.0, 0.0]},
        {"px": [0.50, 0.80], "m": [4.0, 0.0]},
        {"px": [0.70, 0.80], "m": [6.0, 0.0]},
    ]
    client, parts = build()
    with client:
        response = client.post("/api/v1/cameras/1/calibration", json={"points": collinear})
    assert response.status_code == 422
    assert "직선" in response.json()["error"]["message"]
    assert 1 not in parts["cameras"].homography


def test_unknown_camera_is_404() -> None:
    client, _ = build()
    with client:
        response = client.post("/api/v1/cameras/9/calibration", json={"points": SPEC_POINTS})
    assert response.status_code == 404


def test_calibration_republishes_every_zone_of_that_camera() -> None:
    """★ §5.4 — 지면 좌표계가 바뀌었으므로 대시보드 캐시를 갱신해야 한다.

    폴리곤 값은 그대로여도 **화면에 그리는 위치가 달라진다.**
    """
    other = LANE.model_copy(update={"zone_id": "cam2_zone", "cam_id": 2})
    client, parts = build(zones=FakeZoneStore([LANE, other]))
    with client:
        client.post("/api/v1/cameras/1/calibration", json={"points": SPEC_POINTS})
    published = [m for m in parts["hub"].messages if isinstance(m, ZoneUpdatedMsg)]
    assert [m.zone.zone_id for m in published] == ["forklift_lane"]
    assert published[0].action == "upsert"
    assert published[0].cam_id == 1
    # `upsert` 는 폴리곤 전량이 필수다(§5.4) — 없으면 수신 측이 캐시를 손상시킨다.
    assert published[0].zone.polygon_m == LANE.polygon_m


def test_camera_list_exposes_the_matrix_for_drawing() -> None:
    """설정 화면이 저장된 구역을 영상 위에 다시 그리려면 행렬이 필요하다."""
    client, _ = build()
    with client:
        before = client.get("/api/v1/cameras").json()
        assert before[0]["homography"] is None
        assert before[0]["calibrated_at"] is None
        client.post("/api/v1/cameras/1/calibration", json={"points": SPEC_POINTS})
        after = client.get("/api/v1/cameras").json()
    assert after[0]["homography"] is not None
    assert after[0]["calibrated_at"] is not None


# --------------------------------------------------------------------------
# FN-CFG-02 구역 편집
# --------------------------------------------------------------------------


def test_drawn_polygon_is_converted_to_meters_by_the_server() -> None:
    """★ §4.5 — 화면에서 그린 픽셀 폴리곤을 **서버가** 지면 좌표로 바꿔 저장한다."""
    client, parts = build(zones=FakeZoneStore([]))
    with client:
        client.post("/api/v1/cameras/1/calibration", json={"points": SPEC_POINTS})
        response = client.post(
            "/api/v1/zones",
            json={
                "zone_id": "drawn",
                "cam_id": 1,
                "name": "적치 금지",
                # 캘리브레이션 사각형 그대로 그렸다 → (0,0)-(5,0)-(5,5)-(0,5) 이어야 한다.
                "polygon": [[0.21, 0.83], [0.68, 0.80], [0.75, 0.55], [0.28, 0.57]],
                "buffer_m": 0.3,
            },
        )
    assert response.status_code == 200
    polygon = response.json()["polygon_m"]
    assert polygon[0] == [0.0, 0.0]
    assert polygon[2] == [5.0, 5.0]
    assert parts["zones"].zones[0].zone_id == "drawn"
    published = [m for m in parts["hub"].messages if isinstance(m, ZoneUpdatedMsg)]
    assert published[-1].zone.zone_id == "drawn"


def test_drawing_without_calibration_is_refused() -> None:
    """★ 픽셀 값을 미터인 척 저장하면 구역 판정이 통째로 틀리면서 아무도 모른다."""
    client, parts = build(zones=FakeZoneStore([]))
    with client:
        response = client.post(
            "/api/v1/zones",
            json={
                "zone_id": "drawn",
                "cam_id": 1,
                "name": "적치 금지",
                "polygon": [[0.2, 0.8], [0.6, 0.8], [0.6, 0.6], [0.2, 0.6]],
            },
        )
    assert response.status_code == 422
    assert "캘리브레이션" in response.json()["error"]["message"]
    assert parts["zones"].zones == []


def test_meter_polygon_is_stored_as_is() -> None:
    """실측값을 직접 넣는 경로. 변환하지 않는다."""
    client, parts = build(zones=FakeZoneStore([]))
    with client:
        response = client.post(
            "/api/v1/zones",
            json={
                "zone_id": "measured",
                "cam_id": 1,
                "name": "실측 구역",
                "polygon_m": [[1.0, 1.0], [4.0, 1.0], [4.0, 4.0]],
            },
        )
    assert response.status_code == 200
    assert parts["zones"].zones[0].polygon_m == [(1.0, 1.0), (4.0, 1.0), (4.0, 4.0)]


def test_both_or_neither_polygon_is_refused() -> None:
    client, _ = build(zones=FakeZoneStore([]))
    payload = {"zone_id": "z", "cam_id": 1, "name": "n"}
    with client:
        assert client.post("/api/v1/zones", json=payload).status_code == 422
        both = payload | {"polygon": [[0.1, 0.1]], "polygon_m": [[1.0, 1.0]]}
        assert client.post("/api/v1/zones", json=both).status_code == 422


def test_two_vertices_are_refused() -> None:
    """두 점은 선분이지 구역이 아니다."""
    client, _ = build(zones=FakeZoneStore([]))
    with client:
        response = client.post(
            "/api/v1/zones",
            json={"zone_id": "z", "cam_id": 1, "name": "n", "polygon_m": [[0.0, 0.0], [1.0, 1.0]]},
        )
    assert response.status_code == 422


def test_delete_publishes_the_removal() -> None:
    """삭제를 알리지 않으면 대시보드가 없는 구역을 계속 그린다."""
    client, parts = build()
    with client:
        response = client.delete("/api/v1/zones/forklift_lane?cam_id=1")
    assert response.status_code == 204
    assert parts["zones"].zones == []
    published = [m for m in parts["hub"].messages if isinstance(m, ZoneUpdatedMsg)]
    assert published[-1].action == "delete"
    assert published[-1].zone.zone_id == "forklift_lane"


def test_deleting_an_unknown_zone_is_404() -> None:
    client, _ = build()
    with client:
        assert client.delete("/api/v1/zones/nope?cam_id=1").status_code == 404


# --------------------------------------------------------------------------
# FN-CFG-04 임계값 · FN-CFG-05 위험 반경
# --------------------------------------------------------------------------


def test_policy_patch_reaches_the_state_machine_without_a_restart() -> None:
    """★ FN-CFG-04 — 재시작해야 먹으면 M7 튜닝이 불가능하다."""
    client, parts = build()
    with client:
        machine = client.app.state.event_service.machine  # type: ignore[attr-defined]
        assert machine.policies.confirm_duration_s == 3.0
        response = client.patch(
            "/api/v1/policies", json={"confirm_duration_s": 5.0, "cooldown_s": 45.0}
        )
        assert response.status_code == 200
        assert machine.policies.confirm_duration_s == 5.0
        assert machine.policies.cooldown_s == 45.0
    # 응답은 갱신 후 **전량**이다. 부분 응답이면 화면이 나머지를 옛 값으로 들고 있게 된다.
    assert response.json()["resolve_duration_s"] == 10.0
    assert parts["policies"].policies.confirm_duration_s == 5.0


def test_policy_patch_also_reaches_the_clip_scheduler() -> None:
    """`clip_post_roll_s` 를 바꾸면 예약 실행 시각이 따라 움직여야 한다."""
    client, _ = build()
    with client:
        clips = client.app.state.clips  # type: ignore[attr-defined]
        clips.set_segment_seconds(10.0)
        assert clips.delay_s == 22.0
        client.patch("/api/v1/policies", json={"clip_post_roll_s": 4.0})
        assert clips.delay_s == 16.0


def test_empty_policy_patch_is_refused() -> None:
    client, _ = build()
    with client:
        assert client.patch("/api/v1/policies", json={}).status_code == 422


def test_vehicle_class_radius_can_be_tuned() -> None:
    """FN-CFG-05 — 지게차 기본 3.0m. 통로 폭에 따라 조정한다."""
    client, parts = build()
    with client:
        assert client.get("/api/v1/vehicle-classes").json()[0]["danger_radius_m"] == 3.0
        response = client.patch("/api/v1/vehicle-classes/vehicle", json={"danger_radius_m": 2.5})
    assert response.status_code == 200
    assert parts["vehicles"].classes[0].danger_radius_m == 2.5


def test_non_positive_radius_is_refused() -> None:
    """0 이하를 허용하면 위험 영역이 조용히 사라진다."""
    client, _ = build()
    with client:
        assert (
            client.patch("/api/v1/vehicle-classes/vehicle", json={"danger_radius_m": 0}).status_code
            == 422
        )


def test_unknown_vehicle_class_is_not_created() -> None:
    """감지 클래스는 2종 고정이다(절대규칙 11). 런타임에 추가하는 경로를 두지 않는다."""
    client, parts = build()
    with client:
        assert (
            client.patch("/api/v1/vehicle-classes/excavator", json={"active": True}).status_code
            == 404
        )
    assert [item.class_name for item in parts["vehicles"].classes] == ["vehicle"]
