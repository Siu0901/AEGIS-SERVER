"""marker 궤적 — **영상과 좌표가 정말로 같은 수식을 쓰는가.**

이 검사가 없으면 `deploy/marker_path.py` 의 파이썬 함수와 ffmpeg 표현식이 조용히
갈라질 수 있다. 그 순간 marker 도구는 정합을 재는 대신 자기 오차를 보여주게 되고,
화면에서 두 박스가 어긋나도 원인을 영상·좌표·도구 중 어디로도 못 좁힌다.

ffmpeg 표현식을 파이썬에서 평가하기 위해 `mod(a,b)` 만 바꿔 끼운다. 나머지 함수와
연산자(`abs` · `*` · `-` · 괄호)는 두 언어에서 표기가 같다 — 궤적을 삼각파로 고른
이유가 이것이다.
"""

from __future__ import annotations

import re

import pytest

from deploy.marker_path import (
    BOX_H,
    BOX_W,
    box_size_px,
    escape,
    expr_x,
    expr_y,
    overlay_filter,
    position,
    source_input,
)
from sim.edge_sim import marker

#: 한 주기를 촘촘히 훑는 표본. 삼각파의 꺾이는 지점(4초·6.5초)이 포함되도록 잡았다.
SAMPLES = [0.0, 0.5, 2.0, 3.999, 4.0, 4.001, 6.5, 7.999, 8.0, 12.5, 13.0, 20.75, 1785250970.123]


def evaluate(expression: str, t: float) -> float:
    """ffmpeg 표현식을 파이썬으로 평가한다. `mod(a,b)` 만 `((a)%(b))` 로 바꾼다."""
    converted = re.sub(r"mod\(([^,]+),([^)]+)\)", r"((\1)%(\2))", expression)
    return float(eval(converted, {"abs": abs, "t": t}))


@pytest.mark.parametrize("t", SAMPLES)
def test_ffmpeg_expression_matches_python(t: float) -> None:
    """두 표현이 같은 값을 낸다. 상수 하나만 어긋나도 여기서 걸린다."""
    x, y = position(t)
    assert evaluate(expr_x(), t) == pytest.approx(x, abs=1e-9)
    assert evaluate(expr_y(), t) == pytest.approx(y, abs=1e-9)


def test_marker_stays_inside_the_frame() -> None:
    """박스가 화면 밖으로 나가면 겹침을 눈으로 볼 수 없다."""
    for t in [index * 0.05 for index in range(int(13.0 / 0.05) + 1)]:
        cx, cy = position(t)
        assert cx - BOX_W / 2 >= 0.0 and cx + BOX_W / 2 <= 1.0
        assert cy - BOX_H / 2 >= 0.0 and cy + BOX_H / 2 <= 1.0


def test_commas_are_escaped_for_the_filter_graph() -> None:
    """ffmpeg 필터 그래프에서 `,` 는 **필터 구분자**다.

    `mod(t,8.0)` 을 그대로 넣으면 그 쉼표에서 필터가 잘려
    `No option name near '((0.58+...'` 로 죽는다(ffmpeg 8.1 확인).
    """
    assert escape("mod(t,8.0)") == r"mod(t\,8.0)"
    filter_string = overlay_filter()
    # 옵션 구분자로 남아야 할 `,` 는 없다 — 표현식 안의 쉼표는 전부 이스케이프된다.
    assert "," not in filter_string.replace(r"\,", "")


def test_overlay_is_evaluated_per_frame() -> None:
    """**`drawbox` 를 쓰지 않는 이유가 여기 있다.**

    ffmpeg 8.1.2 의 `drawbox` 는 `x`·`y` 표현식을 초기화 때 한 번만 계산하고(그 빌드에는
    `eval` 옵션조차 없다) 그 값을 계속 쓴다. 사각형이 시각과 무관한 자리에 붙박여
    있는데 화면에는 멀쩡히 보이므로, 정합을 재려던 도구가 가짜 측정값을 내놓는다.
    `overlay` 는 `eval` 기본값이 `frame` 이지만 명시해 의도를 남긴다.
    """
    assert "eval=frame" in overlay_filter()


def test_overlay_uses_background_size_not_box_size() -> None:
    """`overlay` 에서 `W`·`H` 는 배경, `w`·`h` 는 얹을 사각형이다.

    둘을 바꾸면 사각형 크기에 비례한 엉뚱한 자리에 붙는다.
    """
    filter_string = overlay_filter()
    assert "*W-w/2" in filter_string
    assert "*H-h/2" in filter_string


def test_marker_source_is_a_single_finite_frame() -> None:
    """무한 소스를 주면 필터 그래프가 막혀 송출이 시작되지 않는다.

    ffmpeg 프로세스는 살아 있는데 mediamtx 경로가 계속 `ready=false` 로 남는다 —
    실측으로 밟은 함정이다. `overlay` 의 `repeatlast`(기본 1)가 한 장을 재사용한다.
    """
    argv = source_input(640, 360)
    assert argv[-1].endswith(":d=1:r=1")
    assert "shortest" not in overlay_filter()


def test_box_size_matches_the_normalised_size() -> None:
    assert box_size_px(1920, 1080) == (round(BOX_W * 1920), round(BOX_H * 1080))
    assert box_size_px(640, 360) == (round(BOX_W * 640), round(BOX_H * 360))


def test_trajectory_is_deterministic() -> None:
    """같은 시각이면 언제 계산해도 같은 위치다. 두 프로세스가 위상을 맞추는 근거다."""
    assert position(1785250970.5) == position(1785250970.5)


def test_horizontal_motion_is_fast_enough_to_read_100ms() -> None:
    """정합 목표가 ±100ms 이므로 그 오차가 눈에 보일 만큼은 움직여야 한다.

    100ms 에 1920px 기준 20px 이상 움직이지 않으면 겹침 여부로 판단할 수 없다.
    """
    moved = abs(position(2.0)[0] - position(2.1)[0])
    assert moved * 1920 > 20


def test_sim_frames_sit_exactly_on_the_trajectory() -> None:
    """시뮬레이터가 보내는 bbox 가 궤적에서 나온 그 사각형이어야 한다."""
    from datetime import UTC, datetime

    start = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)
    timeline = marker.build(start, duration_s=2.0, fps=8.0)
    assert timeline

    for item in timeline:
        cx, cy = position(item.message.ts.timestamp())
        person = item.message.objects[0]
        assert person.bbox == pytest.approx(
            (cx - BOX_W / 2, cy - BOX_H / 2, cx + BOX_W / 2, cy + BOX_H / 2)
        )
        # 접지점은 박스 아래변 중앙 — 오버레이가 찍는 점과 겹치는지 함께 본다.
        assert person.foot_point == pytest.approx((cx, cy + BOX_H / 2))


def test_reproject_follows_the_new_timestamps() -> None:
    """`retime` 이 `ts` 를 옮기면 좌표도 따라와야 한다.

    따라오지 않으면 도구 자신이 만든 오차가 측정값에 섞인다.
    """
    from datetime import UTC, datetime, timedelta

    from sim.edge_sim.scripted import retime

    start = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)
    timeline = marker.build(start, duration_s=1.0, fps=8.0)
    moved = marker.reproject(retime(timeline, start + timedelta(seconds=3.3)))

    for item in moved:
        cx, _ = position(item.message.ts.timestamp())
        assert item.message.objects[0].foot_point[0] == pytest.approx(cx)
