"""시나리오 파일이 계약 스키마로 검증되는지 확인한다.

시뮬레이터가 실물과 구분되지 않으려면 케이스 파일이 `aegis_contracts` 를 통과해야 한다.
서버도 브로커도 필요 없는 검사다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sim.edge_sim.scripted import CASES_DIR, load_case

START = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)

CASE_NAMES = sorted(path.stem for path in CASES_DIR.glob("*.yaml"))


def test_at_least_one_case_exists() -> None:
    assert CASE_NAMES


@pytest.mark.parametrize("case", CASE_NAMES)
def test_case_loads_and_validates(case: str) -> None:
    timeline = load_case(case, START)
    assert timeline
    # 시각 순 정렬은 재생기가 의존하는 불변식이다.
    assert [item.at_s for item in timeline] == sorted(item.at_s for item in timeline)


@pytest.mark.parametrize("case", CASE_NAMES)
def test_timestamps_are_derived_from_start(case: str) -> None:
    """`ts` 는 시나리오가 적지 않고 시작 시각 + 경과로 주입된다."""
    for item in load_case(case, START):
        stamp = getattr(item.message, "ts", None) or item.message.last_ts
        assert (stamp - START).total_seconds() == pytest.approx(item.at_s)


def test_unknown_case_names_available_options() -> None:
    with pytest.raises(FileNotFoundError, match="사용 가능"):
        load_case("존재하지_않는_케이스", START)


# --------------------------------------------------------------------------
# frame_fps — 키프레임 사이 채우기
# --------------------------------------------------------------------------


def _write(tmp_path: Path, body: str) -> str:
    path = tmp_path / "tween.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


_TWO_KEYFRAMES = """
name: tween
cam_id: 1
frame_fps: 4
timeline:
  - at: 0.0
    type: frame
    cam_id: 1
    objects:
      - class: person
        track_id: 1
        conf: 0.90
        bbox: [0.100, 0.300, 0.200, 0.700]
        helmet: "off"
        helmet_conf: 0.80
        foot_point: [0.150, 0.700]
        foot_point_m: [2.00, 8.00]
        foot_conf: 0.90
        posture: standing
        height_ratio: 0.90
        axis_angle_deg: 0.0
        stillness_s: 0.0
        in_zone: null
  - at: 1.0
    type: frame
    cam_id: 1
    objects:
      - class: person
        track_id: 1
        conf: 0.90
        bbox: [0.300, 0.300, 0.400, 0.700]
        helmet: "on"
        helmet_conf: 0.80
        foot_point: [0.350, 0.700]
        foot_point_m: [4.00, 8.00]
        foot_conf: 0.90
        posture: standing
        height_ratio: 0.90
        axis_angle_deg: 0.0
        stillness_s: 0.0
        in_zone: forklift_lane
"""


def test_frame_fps_fills_between_keyframes(tmp_path: Path) -> None:
    """실물 엣지는 카메라당 8fps 이상을 올린다(FN-DET-01). 손으로 적지 않고 채운다."""
    timeline = load_case(_write(tmp_path, _TWO_KEYFRAMES), START)
    # 0.0 · 0.25 · 0.5 · 0.75 · 1.0
    assert [item.at_s for item in timeline] == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_tweened_coordinates_are_linear(tmp_path: Path) -> None:
    timeline = load_case(_write(tmp_path, _TWO_KEYFRAMES), START)
    middle = timeline[2].message.objects[0]
    assert middle.bbox == pytest.approx([0.2, 0.3, 0.3, 0.7])
    assert middle.foot_point == pytest.approx([0.25, 0.7])
    assert middle.foot_point_m == pytest.approx([3.0, 8.0])


def test_tweening_does_not_invent_judgements(tmp_path: Path) -> None:
    """`helmet` · `in_zone` 은 **앞 키프레임 값을 유지**한다.

    좌표는 물리적으로 이어지지만 판정은 그렇지 않다. 사이를 지어내면 시뮬레이터가
    판정을 만들어내는 셈이고, 그 순간 서버 상태머신 검증이 무의미해진다.
    """
    timeline = load_case(_write(tmp_path, _TWO_KEYFRAMES), START)
    for item in timeline[:-1]:
        person = item.message.objects[0]
        assert person.helmet == "off"
        assert person.in_zone is None
    last = timeline[-1].message.objects[0]
    assert last.helmet == "on"
    assert last.in_zone == "forklift_lane"


def test_tweening_only_covers_tracks_present_in_both_keyframes(tmp_path: Path) -> None:
    """한쪽에만 있는 트랙은 등장·퇴장이다. 없는 위치를 지어내지 않는다."""
    body = _TWO_KEYFRAMES.replace(
        "  - at: 1.0\n    type: frame\n    cam_id: 1\n    objects:\n",
        "  - at: 1.0\n    type: frame\n    cam_id: 1\n    objects:\n"
        "      - class: vehicle\n"
        "        track_id: 9\n"
        "        conf: 0.80\n"
        "        bbox: [0.600, 0.400, 0.800, 0.700]\n"
        "        anchor_m: [9.00, 9.00]\n"
        "        moving: false\n"
        "        danger_radius_m: 3.0\n",
    )
    timeline = load_case(_write(tmp_path, body), START)
    assert [len(item.message.objects) for item in timeline] == [1, 1, 1, 1, 2]


def test_without_frame_fps_nothing_is_added(tmp_path: Path) -> None:
    body = _TWO_KEYFRAMES.replace("frame_fps: 4\n", "")
    timeline = load_case(_write(tmp_path, body), START)
    assert [item.at_s for item in timeline] == [0.0, 1.0]


def test_speed_compresses_at_s_and_ts_together(tmp_path: Path) -> None:
    """배속을 걸어도 `ts` 는 실제 송신 시각과 같은 축에 있어야 한다.

    `ts` 만 원속으로 두면 좌표가 벽시계보다 앞선 시각을 달고 나가 오버레이 정합이
    배속만큼 어긋나고, 서버는 미래에서 온 프레임을 받는다.
    """
    timeline = load_case(_write(tmp_path, _TWO_KEYFRAMES), START, speed=4.0)
    assert [item.at_s for item in timeline] == pytest.approx([0.0, 0.0625, 0.125, 0.1875, 0.25])
    for item in timeline:
        assert (item.message.ts - START).total_seconds() == pytest.approx(item.at_s)


def test_speed_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="speed"):
        load_case(_write(tmp_path, _TWO_KEYFRAMES), START, speed=0.0)


def test_frame_fps_must_be_positive(tmp_path: Path) -> None:
    body = _TWO_KEYFRAMES.replace("frame_fps: 4", "frame_fps: 0")
    with pytest.raises(ValueError, match="frame_fps"):
        load_case(_write(tmp_path, body), START)
