"""marker 궤적 — **영상과 좌표가 공유하는 유일한 정의.**

오버레이 정합(±100ms · FN-UI-02)을 눈이 아니라 화면으로 확인하기 위한 장치다.
`deploy/fake_cams.py --marker` 가 영상에 사각형을 얹고, `sim/edge_sim/marker.py`
가 **같은 수식으로** person 좌표를 만들어 `/ws/edge` 로 보낸다. 화면에서 오버레이
박스가 영상 속 사각형과 겹치면 정합이 맞는 것이고, 어긋난 거리가 곧 오차다.

**두 궤적을 각자 정의하지 않는다.** 중복 정의하면 어긋났을 때 영상이 틀렸는지
좌표가 틀렸는지 알 수 없어, 정합을 재려던 도구가 오히려 원인을 감춘다.
그래서 파라미터도 수식도 이 파일에만 있다.

**시각 기준은 에포크 초다.** `fake_cams` 의 필터 체인이
`setpts=RTCTIME/(TB*1000000)` 로 pts 를 에포크로 덮어쓰므로, ffmpeg 표현식 안의
`t` 는 벽시계 에포크 초다. 시뮬레이터도 프레임 `ts` 의 에포크 초를 그대로 넣는다.
두 프로세스의 기동 시각이 달라도 궤적의 위상이 같아지는 이유가 이것이다.

**같은 함수만 쓴다.** 파이썬과 ffmpeg 표현식이 둘 다 가진 `abs` · `mod` 로만 쓴
삼각파라, 두 표현이 글자 단위로 대응한다(`tests/test_marker_path.py` 가 대조한다).
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "BOX_H",
    "BOX_W",
    "PERIOD_X_S",
    "PERIOD_Y_S",
    "X_CENTER",
    "X_SWING",
    "Y_CENTER",
    "Y_SWING",
    "box_size_px",
    "escape",
    "expr_x",
    "expr_y",
    "overlay_filter",
    "position",
    "source_input",
]

#: 가로 왕복 주기(초). 짧을수록 시간 오차가 위치 오차로 크게 드러난다.
#: 8초면 정규화 속도 0.19/s → 1920px 기준 초당 366px 이라 100ms 오차가 37px 이다.
PERIOD_X_S: Final = 8.0

#: 세로 왕복 주기(초). 가로와 **서로소가 아닌 값**을 피해 궤적이 한 선에 겹치지 않게 한다.
PERIOD_Y_S: Final = 13.0

#: 중심 좌표의 진동 범위(정규화). 박스가 화면 밖으로 나가지 않도록 여유를 둔다.
X_CENTER: Final = 0.50
X_SWING: Final = 0.36
Y_CENTER: Final = 0.58
Y_SWING: Final = 0.13

#: 사각형 크기(정규화). 사람 한 명 정도로 잡아 오버레이 박스와 비교하기 쉽게 한다.
BOX_W: Final = 0.06
BOX_H: Final = 0.22


def _triangle(elapsed: float, period: float) -> float:
    """-1 ~ +1 삼각파. `abs` 와 나머지 연산만 쓴다 — ffmpeg 표현식과 같은 형태여야 한다."""
    return 1.0 - abs(2.0 * (elapsed % period) / period - 1.0) * 2.0


def position(epoch_s: float) -> tuple[float, float]:
    """에포크 초 → 사각형 **중심**의 정규화 좌표.

    `deploy/fake_cams.py` 가 태우는 사각형과 `sim/edge_sim/marker.py` 가 보내는
    좌표가 이 함수 하나에서 나온다.
    """
    return (
        X_CENTER + X_SWING * _triangle(epoch_s, PERIOD_X_S),
        Y_CENTER + Y_SWING * _triangle(epoch_s, PERIOD_Y_S),
    )


def _expr_triangle(period: float) -> str:
    """`_triangle` 과 같은 수식의 ffmpeg 표현식. 함수·상수·괄호가 1:1 대응한다."""
    return f"(1-abs(2*mod(t,{period})/{period}-1)*2)"


def expr_x() -> str:
    """중심 x 의 ffmpeg 표현식(정규화)."""
    return f"({X_CENTER}+{X_SWING}*{_expr_triangle(PERIOD_X_S)})"


def expr_y() -> str:
    """중심 y 의 ffmpeg 표현식(정규화)."""
    return f"({Y_CENTER}+{Y_SWING}*{_expr_triangle(PERIOD_Y_S)})"


def escape(expression: str) -> str:
    """필터 문자열에 넣기 위해 `,` 를 이스케이프한다.

    ffmpeg 필터 그래프에서 `,` 는 **필터 사이의 구분자**다. `mod(t,8.0)` 을 그대로
    넣으면 그 쉼표에서 필터가 잘려 `No option name near '((0.58+...'` 로 죽는다
    (ffmpeg 8.1 확인). 폰트 경로의 `:` 와 같은 이유이며, 같은 파일 안에서 두 번째로
    밟는 함정이라 함수로 떼어 두고 테스트로 못박는다.
    """
    return expression.replace(",", r"\,")


def box_size_px(width: int, height: int) -> tuple[int, int]:
    """이 해상도에서 사각형의 픽셀 크기. overlay 입력 소스를 만들 때 쓴다."""
    return max(2, round(BOX_W * width)), max(2, round(BOX_H * height))


def overlay_filter() -> str:
    """사각형을 궤적 위치에 얹는 `overlay` 필터 한 조각.

    **`drawbox` 를 쓰지 않는다.** ffmpeg 8.1.2 의 `drawbox` 는 `x`·`y` 표현식을 필터
    초기화 때 한 번만 계산하고(그 빌드에는 `eval` 옵션조차 없다) 그 값을 계속 쓴다.
    화면에는 사각형이 멀쩡히 보이는데 **시각과 무관한 자리에 붙박여 있어서**, 정합을
    재려던 도구가 오히려 "0.26 만큼 어긋났다"는 가짜 측정값을 내놓는다.
    6초에 걸친 6프레임이 픽셀까지 동일한 것으로 확인했다.

    `overlay` 는 `eval` 기본값이 `frame` 이라 매 프레임 다시 계산한다.

    `W`·`H` 는 배경 크기, `w`·`h` 는 얹을 사각형 크기다. 중심 좌표에서 절반을 빼
    좌상단을 구한다.

    **`setpts=RTCTIME/...` 뒤, `setpts=PTS-STARTPTS` 앞에 놓아야 한다.** 그 밖에 두면
    `t` 가 스트림 시작 기준이라 시뮬레이터의 에포크 기준과 위상이 어긋난다.
    """
    x = escape(f"{expr_x()}*W-w/2")
    y = escape(f"{expr_y()}*H-h/2")
    # `repeatlast`(기본 1)로 사각형 입력의 마지막 프레임을 계속 재사용한다.
    # `shortest` 를 켜면 1프레임짜리 입력이 끝나는 순간 송출이 멈춘다.
    return f"overlay=eval=frame:x={x}:y={y}"


def source_input(width: int, height: int) -> list[str]:
    """overlay 로 얹을 자홍색 사각형 입력. `ffmpeg` 인자 조각이다.

    **프레임 하나짜리 유한 입력**이다. 무한 소스를 주면 그쪽이 실시간 제약 없이
    최대 속도로 프레임을 뽑아 필터 그래프가 막히고, ffmpeg 프로세스는 살아 있는데
    송출이 시작되지 않는다(실측: 경로가 계속 `ready=false`).
    `overlay` 의 `repeatlast` 기본값이 1이라 이 한 장을 계속 재사용한다.
    """
    box_w, box_h = box_size_px(width, height)
    return ["-f", "lavfi", "-i", f"color=magenta:size={box_w}x{box_h}:d=1:r=1"]
