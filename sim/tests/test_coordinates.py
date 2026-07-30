"""시나리오의 좌표가 **한 벌**인지 확인한다. FN-DET-06 · FN-DET-07

M6 이전에는 시나리오가 픽셀과 미터를 각각 손으로 적었고, 그 둘이 서로 어긋나 있었다.
어긋난 채로도 아무 테스트가 깨지지 않았다 — 서버는 미터만 보고, 화면은 픽셀만 보기
때문이다. 그래서 여기서 잠근다.

1. 시나리오는 **정규화 픽셀만** 적는다 (미터를 적으면 로더가 거부한다)
2. 나가는 미터는 개발용 캘리브레이션으로 변환한 값과 정확히 같다
3. `in_zone` · `zone_id` 는 그 미터로 판정한 구역과 같다 (`scripts/seed_zones.py` 기준)
4. `within_danger_radius` 는 `dist_m` 과 `danger_radius_m` 이 말하는 것과 같다
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
import yaml

from aegis_contracts import CandidateMsg, DetectedPerson, FrameMsg
from aegis_vision import ZoneShape, within_radius, zone_for_point
from scripts.seed_cameras import homography_for
from scripts.seed_zones import DEV_ZONES
from sim.edge_sim.scripted import CASES_DIR, load_case

START = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)
CASE_NAMES = sorted(path.stem for path in CASES_DIR.glob("*.yaml"))

#: 개발용 구역을 판정용 형태로. **시드와 같은 값**이라야 시나리오가 기대하는 구역과
#: 서버가 보는 구역이 같다.
ZONES: dict[int, list[ZoneShape]] = {}
for zone in DEV_ZONES:
    polygon = cast("list[list[float]]", zone["polygon_m"])
    ZONES.setdefault(cast("int", zone["cam_id"]), []).append(
        ZoneShape(
            zone_id=str(zone["zone_id"]),
            polygon_m=tuple((float(x), float(y)) for x, y in polygon),
            buffer_m=cast("float", zone["buffer_m"]),
        )
    )


@pytest.mark.parametrize("case", CASE_NAMES)
def test_scenarios_carry_pixels_only(case: str) -> None:
    """미터가 적혀 있으면 두 벌의 좌표가 된다 — 로더가 막지만 파일도 깨끗해야 한다."""
    raw = yaml.safe_load((CASES_DIR / f"{case}.yaml").read_text(encoding="utf-8"))
    for entry in raw["timeline"]:
        assert "foot_point_m" not in entry, f"{case}: candidate 에 미터가 적혀 있다"
        for obj in entry.get("objects", []):
            assert "foot_point_m" not in obj, f"{case}: frame 사람에 미터가 적혀 있다"
            assert "anchor_m" not in obj, f"{case}: frame 지게차에 미터가 적혀 있다"


@pytest.mark.parametrize("case", CASE_NAMES)
def test_meters_come_from_the_calibration(case: str) -> None:
    """나가는 미터는 픽셀을 호모그래피에 통과시킨 값 그 자체다(§6.2)."""
    for item in load_case(case, START):
        message = item.message
        if isinstance(message, FrameMsg):
            homography = homography_for(message.cam_id)
            for obj in message.objects:
                if isinstance(obj, DetectedPerson):
                    pixel, ground = obj.foot_point, obj.foot_point_m
                else:
                    pixel, ground = obj.anchor, obj.anchor_m
                expected = homography.to_ground(pixel)
                assert ground == pytest.approx((round(expected[0], 2), round(expected[1], 2)))


@pytest.mark.parametrize("case", CASE_NAMES)
def test_zone_labels_agree_with_the_geometry(case: str) -> None:
    """★ `in_zone` · `zone_id` 가 접지점 위치와 일치한다. FN-DET-07

    M6 이전에는 어긋나 있었다 — 예를 들어 `x_m 12.4`(구역 밖)인 작업자가
    `in_zone: forklift_lane` 을 달고 있었다. 좌표와 라벨이 각각 손으로 쓰였기 때문이다.

    **시나리오가 적은 키프레임만 본다.** 사이를 채운 프레임은 판정 값을 앞 키프레임에서
    그대로 물려받으므로(사이를 지어내지 않는다) 경계를 지나는 순간에는 계산값과 다를 수
    있고, 그건 의도된 동작이다.
    """
    raw = yaml.safe_load((CASES_DIR / f"{case}.yaml").read_text(encoding="utf-8"))
    default_cam = int(raw.get("cam_id", 1))
    for entry in raw["timeline"]:
        cam_id = int(entry.get("cam_id", default_cam))
        zones = ZONES.get(cam_id, [])
        homography = homography_for(cam_id)
        if entry["type"] == "frame":
            for obj in entry["objects"]:
                if obj["class"] != "person":
                    continue
                point = homography.to_ground(tuple(obj["foot_point"]))
                computed = zone_for_point(point, zones, previous_zone_id=obj["in_zone"])
                assert obj["in_zone"] == computed, (
                    f"{case}: {tuple(round(v, 2) for v in point)} 의 in_zone 이 어긋난다"
                )
        elif entry["type"] == "candidate":
            point = homography.to_ground(_bottom_center(entry["bbox"]))
            computed = zone_for_point(point, zones, previous_zone_id=entry["zone_id"])
            assert entry["zone_id"] == computed, (
                f"{case}: 후보 zone_id 가 어긋난다 ({tuple(round(v, 2) for v in point)})"
            )


def _bottom_center(bbox: list[float]) -> tuple[float, float]:
    """후보의 접지점은 bbox 아래변 중앙이다(§6.1 「bbox 기반」)."""
    return ((bbox[0] + bbox[2]) / 2.0, bbox[3])


@pytest.mark.parametrize("case", CASE_NAMES)
def test_danger_radius_flag_agrees_with_the_distance(case: str) -> None:
    """`within_danger_radius` 는 `dist_m` 과 반경이 말하는 것과 같아야 한다(§2.2).

    반경은 프레임의 지게차가 싣고 오므로(`danger_radius_m`) 시나리오 안에서 검산된다.
    """
    radii = _danger_radii(case)
    for item in load_case(case, START):
        message = item.message
        if not isinstance(message, CandidateMsg):
            continue
        for nearby in message.nearby:
            radius = radii.get((message.cam_id, nearby.track_id))
            if radius is None:
                continue
            expected = within_radius(nearby.dist_m, radius)
            assert nearby.within_danger_radius is expected, (
                f"{case}: 지게차 {nearby.track_id} 가 {nearby.dist_m}m 인데 "
                f"within_danger_radius={nearby.within_danger_radius} (반경 {radius}m)"
            )


def _danger_radii(case: str) -> dict[tuple[int, int], float]:
    """(cam_id, track_id) → 그 지게차가 보고한 위험 반경."""
    found: dict[tuple[int, int], float] = {}
    for item in load_case(case, START):
        if isinstance(item.message, FrameMsg):
            for obj in item.message.objects:
                if (radius := getattr(obj, "danger_radius_m", None)) is not None:
                    found[(item.message.cam_id, obj.track_id)] = radius
    return found
