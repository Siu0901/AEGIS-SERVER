"""레터박스 좌표 변환. 모델이 없어도 검증할 수 있는 순수 계산이다.

여기가 틀리면 **모든 박스가 조용히 어긋난다** — 감지는 정상으로 보이는데 좌표만
세로로 눌리고 위로 밀리므로, 화면을 보기 전까지 드러나지 않는다.
"""

from __future__ import annotations

import pytest

from edge.letterbox import Letterbox

#: 실제 구성 — 서브 스트림 640×360(16:9) → 모델 입력 640×384 rect.
SUB = Letterbox(source_width=640, source_height=360, model_width=640, model_height=384)


def test_sub_stream_needs_only_vertical_padding() -> None:
    """640×360 은 가로가 이미 맞으므로 위아래로만 12px 씩 붙는다."""
    assert SUB.scale == pytest.approx(1.0)
    assert SUB.pad_x == pytest.approx(0.0)
    assert SUB.pad_y == pytest.approx(12.0)


def test_corners_map_to_unit_square() -> None:
    """패딩을 걷어내면 프레임의 네 모서리가 정확히 0과 1이다."""
    assert SUB.to_normalized(0.0, 12.0) == pytest.approx((0.0, 0.0))
    assert SUB.to_normalized(640.0, 372.0) == pytest.approx((1.0, 1.0))


def test_padding_band_is_outside_the_frame() -> None:
    """패딩 영역은 프레임 밖이다.

    **0으로 접지 않는다.** 접으면 프레임 위쪽에 걸친 박스의 접지점이 경계에 눌려
    붙어 거리가 조용히 틀어진다 — 자를지 말지는 쓰는 쪽이 정한다.
    """
    assert SUB.to_normalized(0.0, 0.0)[1] < 0.0
    assert SUB.to_normalized(0.0, 384.0)[1] > 1.0


@pytest.mark.parametrize(
    "point",
    [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.21, 0.83), (0.99, 0.02)],
)
def test_round_trip(point: tuple[float, float]) -> None:
    model = SUB.to_model(*point)
    assert SUB.to_normalized(*model) == pytest.approx(point)


def test_square_letterbox_would_pad_both_axes() -> None:
    """정사각 입력(640×640)을 쓰면 위아래 패딩이 140px 로 늘어난다.

    이 테스트는 **정사각을 쓰지 말라는 근거를 숫자로 고정한다**(기능명세서 §5).
    640×384 rect 대비 연산 픽셀이 약 1.67배다.
    """
    square = Letterbox(source_width=640, source_height=360, model_width=640, model_height=640)
    assert square.pad_y == pytest.approx(140.0)
    pixel_ratio = (640 * 640) / (640 * 384)
    assert pixel_ratio == pytest.approx(1.667, abs=0.01)


def test_downscale_keeps_aspect() -> None:
    """모델 입력이 프레임보다 작으면 화각을 자르지 않고 줄인다."""
    box = Letterbox(source_width=1920, source_height=1080, model_width=640, model_height=384)
    assert box.scale == pytest.approx(640 / 1920)
    assert box.resized_height == 360
    assert box.pad_y == pytest.approx(12.0)
    assert box.to_normalized(*box.to_model(0.5, 0.5)) == pytest.approx((0.5, 0.5))
