"""안전모 분류 전처리 — **학습·검증 경로와 같아야 한다** (FN-DET-04).

ultralytics `classify_transforms()` (v8.4.126 실측)

    T.Resize(224)      # 정수 하나면 **짧은 변** 기준, 비율 유지
    T.CenterCrop(224)
    T.ToTensor()
    T.Normalize(mean=(0,0,0), std=(1,1,1))   # 무연산

한동안 이 자리에 `ClassifyLetterBox` 라고 적어 두고 **긴 변** 기준으로 줄인 뒤 회색
패딩을 채웠다. 같은 크롭이 학습 때와 전혀 다른 형태로 들어간다 — 사람 박스는 대체로
세로로 길어서 **매번** 어긋난다(확률적 실패가 아니라 구조적 실패다).

눈으로는 못 잡는 종류의 결함이다. 두 방식 다 224×224 를 내놓고 사람 크롭처럼
보이므로, 화면을 봐서는 어느 쪽이 학습과 맞는지 알 수 없다. 그래서 기하로 잠근다.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from edge.classify import HelmetClassifier
from edge.config import ClassifyConfig
from edge.detect import Detection

SIZE = 224


def crop_of(
    width: int,
    height: int,
    *,
    margin: float = 0.0,
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
) -> npt.NDArray[np.float32]:
    """`width`x`height` 크롭 하나를 실제 `_crop()` 에 태워 모델 입력을 얻는다.

    세션을 만들지 않는다 — 여기서 보는 것은 전처리 기하뿐이고, 모델을 올리면
    테스트가 가중치 파일에 묶여 CI 에서 돌지 않게 된다.
    """
    classifier = HelmetClassifier.__new__(HelmetClassifier)
    config = ClassifyConfig.__new__(ClassifyConfig)
    object.__setattr__(config, "input_size", SIZE)
    object.__setattr__(config, "crop_margin", margin)
    classifier._config = config
    # 가로 위치를 알아볼 수 있게 좌→우 밝기 경사를 넣는다.
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :, 1] = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    detection = Detection(
        object_class="person",
        conf=1.0,
        bbox=bbox,
        contour=(),
        box_height_px=float(height),
    )
    tensor = classifier._crop(frame, detection)
    assert tensor is not None
    return tensor


def test_output_is_always_the_model_input_shape() -> None:
    for width, height in [(100, 300), (300, 100), (224, 224), (7, 9), (640, 360)]:
        assert crop_of(width, height).shape == (3, SIZE, SIZE)


def test_no_padding_is_added() -> None:
    """★ **패딩이 없어야 한다.** 옛 구현은 세로로 긴 크롭에 좌우를 회색(114)으로
    채웠고, 100×300 기준으로 화면의 **66%가 배경**이었다. 학습 입력에는 그런 띠가
    없으므로 모델은 처음 보는 그림을 받게 된다.
    """
    tensor = crop_of(100, 300)
    grey = 114 / 255.0
    # 옛 구현이라면 좌우 끝 열이 통째로 패딩값이었다.
    left_edge = tensor[:, :, 0]
    right_edge = tensor[:, :, -1]
    assert not np.allclose(left_edge, grey, atol=1e-3)
    assert not np.allclose(right_edge, grey, atol=1e-3)


def test_short_side_decides_the_scale_not_the_long_side() -> None:
    """세로로 긴 크롭에서 **가로가 꽉 차야 한다**.

    짧은 변(가로)이 224 로 늘어나므로 가로 방향 경사가 0~255 전 구간을 담는다.
    긴 변 기준으로 줄이던 옛 구현에서는 가로가 75px 로 줄고 나머지가 패딩이었다.
    """
    tensor = crop_of(100, 300)
    green = tensor[1]
    row = green[SIZE // 2]
    assert row[0] == pytest.approx(0.0, abs=0.02)
    assert row[-1] == pytest.approx(1.0, abs=0.02)


def test_center_is_kept_when_the_long_side_overflows() -> None:
    """가로로 긴 크롭은 **가운데만** 남는다 — 양끝이 잘려 나간다.

    이것이 CenterCrop 의 정의이고 학습이 본 형태다. 잘리는 것이 아까워 보이더라도
    추론에서만 살려두면 학습과 어긋난다.
    """
    tensor = crop_of(600, 200)
    row = tensor[1][SIZE // 2]
    # 좌우 끝이 잘렸으므로 경사의 양 극단(0.0 · 1.0)이 남아 있지 않다.
    assert row[0] > 0.15
    assert row[-1] < 0.85


def test_square_crop_passes_through_unchanged() -> None:
    """정사각 크롭은 리사이즈만 되고 잘리지 않는다 — 두 방식이 같아지는 유일한 경우다."""
    row = crop_of(300, 300)[1][SIZE // 2]
    assert row[0] == pytest.approx(0.0, abs=0.02)
    assert row[-1] == pytest.approx(1.0, abs=0.02)


def test_margin_widens_the_crop_beyond_the_box() -> None:
    """★ **박스 바깥으로 넓혀 잘라야 한다** — 안전모가 위 경계에 걸리기 때문이다.

    감지 박스는 사람에 딱 맞게 나온다. 그대로 자르면 판정의 근거인 머리 윤곽이 잘려
    나가고, 모델은 학습 때 본 적 없는 형태를 받는다.

    프레임 가운데의 작은 박스를 두 번 자른다. 여유를 준 쪽이 **더 넓은 범위**를
    담으므로, 가로 경사에서 더 넓은 밝기 구간이 나온다.
    """
    box = (0.4, 0.4, 0.6, 0.6)
    tight = crop_of(400, 400, margin=0.0, bbox=box)[1][SIZE // 2]
    padded = crop_of(400, 400, margin=0.25, bbox=box)[1][SIZE // 2]
    assert padded[0] < tight[0]
    assert padded[-1] > tight[-1]


def test_margin_is_clipped_at_the_frame_edge() -> None:
    """가장자리에 선 사람은 여유가 한쪽만 붙는다 — 프레임 밖을 지어내지 않는다."""
    assert crop_of(400, 400, margin=0.25, bbox=(0.0, 0.0, 0.3, 0.3)).shape == (3, SIZE, SIZE)
