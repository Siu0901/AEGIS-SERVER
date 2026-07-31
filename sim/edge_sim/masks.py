"""합성 마스크 — 시나리오가 「어떤 자세인가」만 적으면 윤곽을 그려 준다.

실물 엣지는 세그멘테이션 모델에서 마스크를 받는다(FN-DET-02 세그 헤드). 시뮬레이터에는
모델이 없으므로 **자세와 움직임을 좌표로 합성**하고, 그 뒤의 계산(높이 비율 · 주축 각도 ·
정지 지속 · 최근접 거리)은 `packages/vision` 의 실제 로직이 그대로 한다.

★ **여기서 판정하지 않는다.** 이 모듈이 만드는 것은 관측(윤곽)이고, `fallen` 인지
아닌지는 `aegis_vision.posture.posture_of` 가 정한다. 「쭈그림이면 standing 을 싣는다」
같은 코드가 들어오는 순간 오탐 억제를 검증한 것이 아니라 정답을 적어 넣은 것이 된다
(`.claude/rules/sim.md` — 엣지는 판단하지 않는다).

---

**자세 넷** — bbox 는 시나리오가 적고, 이 모듈은 그 안을 어떤 모양으로 채울지 정한다.

| `posture` | 모양 | 세 게이지에 미치는 영향 |
|---|---|---|
| `standing` | 세로로 긴 캡슐 | 높이 비율 ≈ 1 · 주축 ≈ 0° |
| `crouch` | 낮고 둥근 덩어리 | 높이 비율 낮음 · 주축이 수평에 가까울 수 있다 |
| `bend` | ㄱ 자 (수평 상체 + 수직 다리) | 높이 비율 중간 · 주축이 상체를 따라 눕는다 |
| `lying` | 가로로 긴 캡슐 | 높이 비율 매우 낮음 · 주축 ≈ 90° |

★ **`crouch` 와 `bend` 는 ①②를 통과하도록 일부러 그린다.** 그것이 FN-DET-10 의
어려운 부분이고, 둘을 갈라내는 것은 ③(정지 지속)뿐이다. 모양만으로 걸러지게 그리면
③이 실제로 일하는지 확인할 수 없다.

**움직임 둘**

| `motion` | 뜻 |
|---|---|
| `working` | 상체·팔이 계속 움직인다. 프레임마다 형태가 바뀌어 정지 시간이 쌓이지 않는다 |
| `still` | 움직이지 않는다. 정지 시간이 쌓인다 |

움직임은 **결정적**이다 — 시각으로만 정해지는 삼각함수 한 개이며 난수가 없다.
시나리오를 두 번 돌리면 같은 값이 나와야 기대값을 적을 수 있다.
"""

from __future__ import annotations

import math
from typing import Final

from aegis_vision import Bbox, PointPx

__all__ = [
    "MOTIONS",
    "POSTURES",
    "person_mask",
    "vehicle_mask",
]

#: 시나리오가 쓸 수 있는 자세 이름.
POSTURES: Final = ("standing", "crouch", "bend", "lying")

#: 시나리오가 쓸 수 있는 움직임 이름.
MOTIONS: Final = ("working", "still")

#: 윤곽을 몇 점으로 그릴지. 최근접 거리는 전수 비교라 점 수가 곧 비용이고,
#: 40점이면 정규화 좌표에서 2.5% 간격이라 판정에 영향을 주지 않는다.
_STEPS = 40

#: `working` 이 만드는 형태 변화의 주기(초)와 크기.
#:
#: 주기가 프레임 간격(8fps = 0.125초)보다 충분히 길어야 프레임마다 다른 값이 나온다.
#: 크기는 `edge/config.yaml` 의 `posture.shape_change_max` 를 넘도록 잡는다 — 넘지
#: 않으면 「일하는 사람」이 정지로 잡히고, 그건 시뮬레이터가 시나리오를 배신하는 것이다.
_SWING_PERIOD_S = 1.6
_SWING_AMPLITUDE = 0.55


def person_mask(bbox: Bbox, *, posture: str, motion: str, at_s: float) -> list[PointPx]:
    """사람 마스크 윤곽. `bbox` 안을 자세에 맞는 모양으로 채운다.

    `at_s` 는 시나리오 시작 기준 경과 초다. `motion="working"` 일 때만 쓰이며,
    이 값 하나로 형태가 정해지므로 재생이 결정적이다.
    """
    if posture not in POSTURES:
        msg = f"모르는 자세다: {posture!r} — {POSTURES} 중 하나여야 한다"
        raise ValueError(msg)
    if motion not in MOTIONS:
        msg = f"모르는 움직임이다: {motion!r} — {MOTIONS} 중 하나여야 한다"
        raise ValueError(msg)

    x1, y1, x2, y2 = (float(value) for value in bbox)
    if x2 <= x1 or y2 <= y1:
        msg = f"bbox 가 뒤집혔거나 넓이가 0이다: {bbox!r}"
        raise ValueError(msg)

    swing = _swing(at_s) if motion == "working" else 0.0
    if posture == "bend":
        points = _bend(x1, y1, x2, y2, swing)
    elif posture == "crouch":
        points = _crouch(x1, y1, x2, y2, swing)
    elif posture == "lying":
        points = _lying(x1, y1, x2, y2, swing)
    else:
        points = _standing(x1, y1, x2, y2, swing)
    return points


def vehicle_mask(bbox: Bbox, *, fork_ratio: float = 0.0) -> list[PointPx]:
    """지게차 마스크 윤곽. `fork_ratio` 만큼 **왼쪽으로 포크가 뻗는다.**

    ★ 이 형상이 FN-DET-09 의 존재 이유다 — 질량은 차체에 있는데 부딪히는 부분은
    포크 끝이라, bbox 중심 거리와 마스크 최근접 거리가 갈린다.

    `fork_ratio` 는 bbox 폭 대비 포크 길이다. `0.0` 이면 포크가 없는 직사각 차체이며,
    그때는 두 방식이 반폭만큼만 차이 난다.
    """
    x1, y1, x2, y2 = (float(value) for value in bbox)
    if not 0.0 <= fork_ratio < 1.0:
        msg = f"fork_ratio 는 0 이상 1 미만이어야 한다: {fork_ratio!r}"
        raise ValueError(msg)

    width = x2 - x1
    body_x1 = x1 + width * fork_ratio
    points = _rect_outline(body_x1, y1, x2, y2)
    if fork_ratio > 0.0:
        # 포크는 지면 가까이(bbox 아래쪽 20% 띠)에 붙어 앞으로 나온다.
        fork_top = y2 - (y2 - y1) * 0.25
        fork_bottom = y2 - (y2 - y1) * 0.08
        points += _rect_outline(x1, fork_top, body_x1, fork_bottom)
    return points


# --- 자세별 모양 ------------------------------------------------------------


def _standing(x1: float, y1: float, x2: float, y2: float, swing: float) -> list[PointPx]:
    """세로로 긴 캡슐 + 한쪽으로 뻗는 팔.

    팔이 나오고 들어가면 폭과 면적이 바뀌어 형태 변화량이 생긴다 — 서 있는 사람은
    어차피 ①②에서 걸러지지만, 「서서 일하다 쓰러졌다」 같은 전이를 그리려면
    같은 규칙이 서 있는 구간에도 적용되어야 한다.
    """
    points = _capsule(x1 + (x2 - x1) * 0.22, y1, x2 - (x2 - x1) * 0.22, y2, horizontal=False)
    return points + _arm(x1, x2, y1 + (y2 - y1) * 0.30, swing)


def _crouch(x1: float, y1: float, x2: float, y2: float, swing: float) -> list[PointPx]:
    """낮고 둥근 덩어리 + 팔.

    쭈그린 사람의 bbox 는 짧고 넓다. 그래서 ①(높이 비율)을 통과하고, 폭이 높이보다
    크면 ②(주축 각도)도 통과한다 — **의도한 것이다.** 남는 것은 ③뿐이다.
    """
    points = _capsule(x1, y1 + (y2 - y1) * 0.15, x2, y2, horizontal=True)
    return points + _arm(x1, x2, y1 + (y2 - y1) * 0.35, swing)


def _bend(x1: float, y1: float, x2: float, y2: float, swing: float) -> list[PointPx]:
    """ㄱ 자 — 수평으로 굽힌 상체와 수직으로 선 다리."""
    width = x2 - x1
    height = y2 - y1
    torso = _rect_outline(x1, y1, x2, y1 + height * 0.32)
    legs = _rect_outline(
        x2 - width * 0.38,
        y1 + height * 0.32,
        x2 - width * 0.05,
        y2,
    )
    return torso + legs + _arm(x1, x2, y1 + height * 0.20, swing)


def _lying(x1: float, y1: float, x2: float, y2: float, swing: float) -> list[PointPx]:
    """가로로 긴 캡슐 + 팔.

    **`motion` 은 누운 자세에서도 살아 있어야 한다.** 쓰러진 사람과 바닥에 누워 작업하는
    사람(또는 몸을 뒤척이는 사람)은 모양이 같고 움직임만 다르다. 여기서 팔을 빼면
    `lying` 이 곧 `fallen` 이 되어 ③이 무력해진다 — 그건 시뮬레이터가 정답을 적어 넣는 것이다.
    """
    points = _capsule(x1, y1, x2, y2, horizontal=True)
    return points + _arm(x1, x2, y1 + (y2 - y1) * 0.4, swing)


def _arm(x1: float, x2: float, y: float, swing: float) -> list[PointPx]:
    """`swing` 만큼 옆으로 뻗는 팔. `swing = 0` 이면 팔이 없다(정지).

    면적과 종횡비를 함께 흔들어야 `StillnessTracker` 의 두 지표가 모두 반응한다.
    """
    if swing <= 0.0:
        return []
    reach = (x2 - x1) * swing
    count = max(int(_STEPS * swing), 2)
    return [(x1 - reach * i / count, y) for i in range(count + 1)]


def _swing(at_s: float) -> float:
    """일하는 사람의 팔 뻗음 정도 0~`_SWING_AMPLITUDE`. **결정적**이다."""
    phase = (at_s % _SWING_PERIOD_S) / _SWING_PERIOD_S
    return _SWING_AMPLITUDE * (0.5 - 0.5 * math.cos(2.0 * math.pi * phase))


# --- 도형 부품 --------------------------------------------------------------


def _capsule(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    horizontal: bool,
) -> list[PointPx]:
    """타원 윤곽. `horizontal` 이면 가로로 긴 것으로 그린다(모양은 bbox 가 정한다)."""
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    rx, ry = (x2 - x1) / 2.0, (y2 - y1) / 2.0
    # `horizontal` 은 bbox 가 이미 가로로 길 때 모서리를 덜 깎아 실루엣을 도톰하게
    # 만든다 — 누운 사람의 주축이 흐려지지 않게 하기 위해서다.
    fatten = 1.0 if horizontal else 0.92
    return [
        (
            cx + rx * math.cos(2.0 * math.pi * i / _STEPS),
            cy + ry * fatten * math.sin(2.0 * math.pi * i / _STEPS),
        )
        for i in range(_STEPS)
    ]


def _rect_outline(x1: float, y1: float, x2: float, y2: float) -> list[PointPx]:
    """직사각형 윤곽점."""
    points: list[PointPx] = []
    for i in range(_STEPS // 4 + 1):
        t = i / (_STEPS // 4)
        points.append((x1 + (x2 - x1) * t, y1))
        points.append((x1 + (x2 - x1) * t, y2))
        points.append((x1, y1 + (y2 - y1) * t))
        points.append((x2, y1 + (y2 - y1) * t))
    return points
