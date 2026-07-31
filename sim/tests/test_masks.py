"""합성 마스크에서 나온 게이지가 실제로 자세를 갈라놓는가. FN-DET-08 ~ 11

★ **이 파일이 「오탐 억제」의 증거다.**

`sim/tests/test_cases.py` 는 서버 상태머신이 기대대로 판정하는지를 본다. 그런데
쭈그림·허리 굽힘 시나리오에는 후보가 아예 없으므로, 그쪽 검사만으로는 "후보를 안
적었으니 이벤트가 없다"는 **동어반복**이 된다. 여기서는 그 앞 단계 — 시나리오가 적은
자세와 움직임에서 `packages/vision` 이 계산해 낸 `posture` 와 세 게이지 — 를 직접 본다.

시나리오의 `expect.postures` · `expect.distances` 가 정답이고, 대조는 이 파일이 한다.

    expect:
      postures:
        - at_s: 8.0
          track_id: 3
          posture: standing
          meets: [height_ratio, axis_angle]   # 충족한 조건
          fails: [stillness]                  # 미충족 조건
      distances:
        - at_s: 2.0
          track_id: 3
          vehicle_track_id: 11
          mask_nearest_below_m: 2.0
          bbox_center_above_m: 3.0

`meets` / `fails` 를 함께 적는 이유: `posture == standing` 만 확인하면 **모양 때문에
①②에서 걸러진 것**과 **③이 일한 것**을 구분할 수 없다. 전자라면 ③이 죽어 있어도
테스트가 통과한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from aegis_contracts import Policies
from aegis_vision import (
    FallThresholds,
    Homography,
    ReferenceHeight,
    StillnessTracker,
    distance_bbox_center_m,
    ground_distance_m,
    height_ratio,
    mask_shape,
    posture_of,
)
from scripts.seed_cameras import homography_for
from sim.edge_sim.masks import person_mask
from sim.edge_sim.scripted import CASES_DIR, load_case

#: 시나리오 시작 시각. 결정적이어야 기대값을 적을 수 있다.
START = datetime(2026, 8, 14, 5, 0, 0, tzinfo=UTC)

#: 조건 이름 → 그 조건이 충족됐는지 보는 함수. `policies` 기본값과 같은 임계값이다.
_POLICIES = Policies()
_CONDITIONS = {
    "height_ratio": lambda o: o.height_ratio <= _POLICIES.fall_height_ratio_max,
    "axis_angle": lambda o: o.axis_angle_deg >= _POLICIES.fall_axis_angle_min_deg,
    "stillness": lambda o: o.stillness_s >= _POLICIES.fall_stillness_s,
}


def _spec(case: str) -> dict[str, Any]:
    raw: Any = yaml.safe_load(Path(CASES_DIR / f"{case}.yaml").read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _cases_with(key: str) -> list[str]:
    found = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        expect = _spec(path.stem).get("expect") or {}
        if expect.get(key):
            found.append(path.stem)
    return found


POSTURE_CASES = _cases_with("postures")
DISTANCE_CASES = _cases_with("distances")

#: 이 이름들이 사라지면 대조가 조용히 0건이 된다. 그것을 통과로 보지 않는다.
REQUIRED_POSTURE = {"fall_detected", "crouch_not_fall", "bend_not_fall"}
REQUIRED_DISTANCE = {"proximity_forklift", "mask_vs_center"}


def _frame_at(messages: list[Any], at_s: float, cam_id: int) -> Any:
    """`at_s` 직전(또는 그 시각)의 `frame`. 보간으로 8fps 가 채워져 있다."""
    frames = [
        item
        for item in messages
        if item.message.type == "frame"
        and item.message.cam_id == cam_id
        and item.at_s <= at_s + 1e-6
    ]
    assert frames, f"{at_s}초 이전에 cam{cam_id} 프레임이 없다"
    return frames[-1].message


def _bbox(value: Any) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = (float(item) for item in value)
    return (x1, y1, x2, y2)


def _person(frame: Any, track_id: int) -> Any:
    for obj in frame.objects:
        if getattr(obj, "track_id", None) == track_id and obj.class_ == "person":
            return obj
    msg = f"트랙 {track_id} 이 프레임에 없다"
    raise AssertionError(msg)


def _vehicle(frame: Any, track_id: int) -> Any:
    for obj in frame.objects:
        if getattr(obj, "track_id", None) == track_id and obj.class_ == "vehicle":
            return obj
    msg = f"지게차 {track_id} 이 프레임에 없다"
    raise AssertionError(msg)


def test_required_posture_cases_exist() -> None:
    assert set(POSTURE_CASES) >= REQUIRED_POSTURE, (
        f"빠진 자세 시나리오: {sorted(REQUIRED_POSTURE - set(POSTURE_CASES))}"
    )


def test_required_distance_cases_exist() -> None:
    assert set(DISTANCE_CASES) >= REQUIRED_DISTANCE, (
        f"빠진 거리 시나리오: {sorted(REQUIRED_DISTANCE - set(DISTANCE_CASES))}"
    )


@pytest.mark.parametrize("case", POSTURE_CASES)
def test_posture_matches_its_expectations(case: str) -> None:
    """★ 자세별 판정표. 세 조건 중 무엇이 충족되고 무엇이 걸렀는지까지 대조한다."""
    spec = _spec(case)
    messages = load_case(case, START)
    cam_id = int(spec.get("cam_id", 1))
    problems: list[str] = []

    for want in spec["expect"]["postures"]:
        at_s = float(want["at_s"])
        person = _person(_frame_at(messages, at_s, cam_id), int(want["track_id"]))
        label = f"{case} t={at_s}s track={want['track_id']}"

        if person.posture != want["posture"]:
            problems.append(
                f"{label} posture: 기대 {want['posture']} · 실제 {person.posture} "
                f"(height_ratio={person.height_ratio} axis={person.axis_angle_deg} "
                f"stillness={person.stillness_s})"
            )
        for name in want.get("meets", []):
            if not _CONDITIONS[name](person):
                problems.append(f"{label} 조건 {name} 이 충족되지 않았다 — 모양을 다시 봐라")
        for name in want.get("fails", []):
            if _CONDITIONS[name](person):
                problems.append(f"{label} 조건 {name} 이 충족됐다 — 미충족을 기대했다")

    assert not problems, "\n".join(problems)


def test_getting_up_returns_to_standing() -> None:
    """★ 쓰러졌다가 일어난다 — `fallen` 이 한 번 붙으면 굳어버리면 안 된다.

    §4.2 는 `fall` 의 해소 조건을 「자세가 `standing` 으로 복귀」로 정한다. 판정이
    되돌아오지 않으면 일어선 사람이 영원히 쓰러진 채로 남고, 관리자 확인 없이는
    이벤트가 닫히지 않는다.

    시나리오가 아니라 여기서 잠그는 이유: 이 검사의 대상은 서버 전이가 아니라
    **자세 판정이 양방향인가**이고, 그건 마스크와 게이지만으로 확인된다.
    """
    thresholds = FallThresholds(
        height_ratio_max=_POLICIES.fall_height_ratio_max,
        axis_angle_min_deg=_POLICIES.fall_axis_angle_min_deg,
        stillness_s=_POLICIES.fall_stillness_s,
    )
    homography = homography_for(1)
    reference = ReferenceHeight(px_height=0.42, at_m=(6.0, 9.0))
    tracker = StillnessTracker(
        move_px=_POLICIES.stillness_move_px,
        window_s=_POLICIES.stillness_window_s,
        shape_change_max=0.15,
    )
    lying = (0.4130, 0.7200, 0.5972, 0.7576)
    standing = (0.4597, 0.2600, 0.5397, 0.7576)

    def read(
        bbox: tuple[float, float, float, float],
        posture: str,
        motion: str,
        at_s: float,
    ) -> Any:
        shape = mask_shape(person_mask(bbox, posture=posture, motion=motion, at_s=at_s))
        return posture_of(
            height_ratio=height_ratio(
                shape,
                foot_point=((bbox[0] + bbox[2]) / 2, bbox[3]),
                homography=homography,
                reference=reference,
            ),
            axis_angle_deg=shape.angle_deg,
            stillness_s=tracker.observe(at_s, shape),
            thresholds=thresholds,
        )

    # 8초 동안 누워 움직이지 않는다 → `fallen`.
    down = [read(lying, "lying", "still", index / 8) for index in range(64)]
    assert down[-1].posture == "fallen"

    # 일어선다. 형태가 크게 바뀌므로 정지 시간이 0으로 돌아가고 높이 비율도 회복된다.
    up = [read(standing, "standing", "working", 8.0 + index / 8) for index in range(24)]
    assert up[0].stillness_s == 0.0
    assert up[-1].posture == "standing"
    assert up[-1].height_ratio > _POLICIES.fall_height_ratio_max


@pytest.mark.parametrize("case", DISTANCE_CASES)
def test_distances_match_their_expectations(case: str) -> None:
    """★ FN-DET-09 — 마스크 최근접과 bbox 중심이 갈리는 지점을 숫자로 잠근다."""
    spec = _spec(case)
    messages = load_case(case, START)
    cam_id = int(spec.get("cam_id", 1))
    homography: Homography = homography_for(cam_id)
    problems: list[str] = []

    for want in spec["expect"]["distances"]:
        at_s = float(want["at_s"])
        candidates = [
            item.message
            for item in messages
            if item.message.type == "candidate"
            and abs(item.at_s - at_s) < 1e-6
            and item.message.track_id == int(want["track_id"])
        ]
        if not candidates:
            problems.append(f"{case} t={at_s}s 에 트랙 {want['track_id']} 후보가 없다")
            continue

        vehicle_id = int(want["vehicle_track_id"])
        nearby = [item for item in candidates[0].nearby if item.track_id == vehicle_id]
        if not nearby:
            problems.append(f"{case} t={at_s}s nearby 에 지게차 {vehicle_id} 이 없다")
            continue
        reading = nearby[0]
        label = f"{case} t={at_s}s"

        if reading.method != "mask_nearest":
            problems.append(f"{label} method: 기대 mask_nearest · 실제 {reading.method}")
        if "mask_nearest_below_m" in want and reading.dist_m >= want["mask_nearest_below_m"]:
            problems.append(
                f"{label} 최근접 {reading.dist_m}m — {want['mask_nearest_below_m']}m 미만이 아니다"
            )
        if "within_danger_radius" in want and (
            reading.within_danger_radius is not want["within_danger_radius"]
        ):
            problems.append(
                f"{label} within_danger_radius: 기대 {want['within_danger_radius']} "
                f"· 실제 {reading.within_danger_radius}"
            )
        if "depth_verified" in want and reading.depth_verified is not want["depth_verified"]:
            problems.append(
                f"{label} depth_verified: 기대 {want['depth_verified']} "
                f"· 실제 {reading.depth_verified}"
            )
        if "bbox_center_above_m" in want:
            frame = _frame_at(messages, at_s, cam_id)
            center = distance_bbox_center_m(
                _bbox(candidates[0].bbox),
                _bbox(_vehicle(frame, vehicle_id).bbox),
                homography,
            )
            if center <= want["bbox_center_above_m"]:
                problems.append(
                    f"{label} 중심 거리 {center:.2f}m 가 {want['bbox_center_above_m']}m 를 "
                    "넘지 않는다 — 두 방식이 갈리지 않으면 FN-DET-09 가 필요 없다"
                )

        if "anchor_above_m" in want:
            # ★ 서버가 §2.1 `frame.nearby[].dist_m` 대신 접지점↔앵커로 해소를 판정하면
            #   어떻게 되는지를 숫자로 남긴다. 이 값이 경고 임계 위인 동안에도 최근접은
            #   임계 아래라, 옛 경로에서는 후보가 올라오는 내내 서버가 「이미 해소」로
            #   보아 이벤트가 확정에 도달하지 못했다.
            frame = _frame_at(messages, at_s, cam_id)
            anchor_m = ground_distance_m(
                candidates[0].foot_point_m,
                _vehicle(frame, vehicle_id).anchor_m,
            )
            if anchor_m <= want["anchor_above_m"]:
                problems.append(
                    f"{label} 접지점↔앵커 거리 {anchor_m:.2f}m 가 "
                    f"{want['anchor_above_m']}m 를 넘지 않는다 — 두 값이 갈리지 않으면 "
                    "「확정과 해소가 같은 양을 보는가」를 확인할 수 없다"
                )

    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("case", DISTANCE_CASES)
def test_frame_carries_the_same_distance_as_the_candidate(case: str) -> None:
    """★ §2.1 — `frame` 의 `nearby[].dist_m` 이 후보의 근거와 같은 값인가.

    **확정과 해소는 반드시 같은 양을 본다.** 후보(§2.2)는 마스크 최근접으로 올라오고
    해소 판정(FN-EVT-03)은 `frame` 의 이 값을 보므로, 둘이 어긋나면 엣지가 근접이라고
    올린 순간에 서버가 해소로 판정한다. 여기서 두 경로가 같은 숫자를 내는지 잠근다.
    """
    spec = _spec(case)
    messages = load_case(case, START)
    cam_id = int(spec.get("cam_id", 1))
    problems: list[str] = []

    for want in spec["expect"]["distances"]:
        at_s = float(want["at_s"])
        track_id = int(want["track_id"])
        vehicle_id = int(want["vehicle_track_id"])
        candidate = next(
            (
                item.message
                for item in messages
                if item.message.type == "candidate"
                and abs(item.at_s - at_s) < 1e-6
                and item.message.track_id == track_id
            ),
            None,
        )
        if candidate is None:
            continue
        expected = next(
            (item.dist_m for item in candidate.nearby if item.track_id == vehicle_id), None
        )
        person = _person(_frame_at(messages, at_s, cam_id), track_id)
        actual = next((item.dist_m for item in person.nearby if item.track_id == vehicle_id), None)
        label = f"{case} t={at_s}s"
        if actual is None:
            problems.append(f"{label} frame.nearby 에 지게차 {vehicle_id} 이 없다")
        elif expected is not None and abs(actual - expected) > 0.02:
            problems.append(
                f"{label} frame {actual}m · candidate {expected}m — 두 경로가 다른 값을 잰다"
            )
        if actual is not None:
            basis = next(item.basis for item in person.nearby if item.track_id == vehicle_id)
            if basis != "mask_nearest":
                problems.append(f"{label} basis: 기대 mask_nearest · 실제 {basis}")

    assert not problems, "\n".join(problems)
