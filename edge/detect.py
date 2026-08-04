"""1단계 감지 — seg 모델 하나로 `person` · `vehicle` 과 마스크를 얻는다. FN-DET-02

★ **마스크는 밖으로 나가지 않는다.** 계약(`aegis_contracts.edge`)에 마스크 필드가
없고, 서버로 가는 것은 마스크에서 **계산한 값**(접지점 · 높이 비율 · 주축 각도 ·
최근접 거리)뿐이다. 대시보드가 그리는 것은 박스와 거리선이다.

★ **제로샷이 아니다.** 이 가중치는 `toy_person` · `toy_truck` 으로 이미 학습된 것이고,
`edge/config.yaml` 의 `classes:` 표가 그것을 계약 클래스 2종으로 접는다. 표에 없는
클래스는 버린다 — 이름이 비슷하다는 이유로 `person` 에 붙이지 않는다(절대규칙 11).

**출력 형식(end2end)**. 학습된 모델이 NMS 를 내장하고 있어 후처리에서 NMS 를 돌리지
않는다. `output0` 은 `[1, 300, 38]` 이며 한 행이 다음과 같다.

```
[0:4]  x1 y1 x2 y2   모델 입력(640×384) 픽셀 좌표 — 레터박스가 포함된 좌표계다
[4]    conf
[5]    class index
[6:38] 마스크 계수 32개  ← output1 의 프로토타입과 곱해 마스크가 된다
```
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from aegis_contracts.enums import ObjectClass
from aegis_vision import Bbox, PointPx

from .config import DetectConfig, RuntimeConfig
from .letterbox import Letterbox
from .session import Session

__all__ = ["Detection", "Detector"]

log = logging.getLogger(__name__)

#: 레터박스 패딩 색. ultralytics 학습 파이프라인과 같은 값이어야 한다.
_PAD_VALUE = 114

#: 마스크 이진화 임계. 프로토타입 조합의 시그모이드 출력에 적용한다.
_MASK_THRESHOLD = 0.5

#: 윤곽 점 수 상한.
#:
#: `nearest_pair_m`(§6.5)이 두 윤곽의 전수 비교라 점 수의 곱만큼 계산이 든다. 48이면
#: 사람↔지게차 한 쌍에 2,304회로, 8fps 예산에서 무시할 수준이다. 줄이는 방식은
#: **균등 솎기**다 — `approxPolyDP` 로 꼭짓점만 남기면 주축(PCA)이 긴 변 쪽으로
#: 쏠려 누운 사람의 각도가 실제와 달라진다.
_MAX_CONTOUR_POINTS = 48

#: 마스크 프로토타입의 축소 배율. `output1` 이 96×160 이고 입력이 384×640 이다.
_PROTO_STRIDE = 4


@dataclass(frozen=True, slots=True)
class Detection:
    """감지 하나. 좌표는 전부 **정규화 프레임 좌표**다(API명세서 §1.2)."""

    object_class: ObjectClass
    conf: float
    bbox: Bbox
    contour: tuple[PointPx, ...]
    """마스크 윤곽. **서버로 보내지 않는다** — 게이지·거리 계산에만 쓴다."""
    box_height_px: float
    """원본 프레임 기준 박스 높이(픽셀). 분류 크기 게이트(`cls_min_crop_px`)가 본다."""


class Detector:
    """ONNX seg 추론. 카메라 한 대에 하나씩 만든다(세션은 스레드마다 분리한다)."""

    def __init__(
        self,
        config: DetectConfig,
        runtime: RuntimeConfig,
        letterbox: Letterbox,
    ) -> None:
        self._config = config
        self._letterbox = letterbox
        self._session = Session(config.model_path, runtime)
        self._names = self._session.class_names()
        self._unmapped: set[str] = set()
        log.info(
            "감지 모델 적재 — %s (클래스 %s → %s)",
            config.model_path.name,
            list(self._names.values()),
            dict(config.class_map),
        )

    def __call__(self, frame_bgr: npt.NDArray[np.uint8]) -> list[Detection]:
        """프레임 한 장 → 감지 목록. 입력은 서브 스트림 해상도의 BGR 프레임이다."""
        output0, output1 = self._session.run(self._preprocess(frame_bgr))
        rows = output0[0]
        protos = output1[0]

        kept = rows[rows[:, 4] >= self._config.conf]
        detections: list[Detection] = []
        for row in kept:
            mapped = self._map_class(int(row[5]))
            if mapped is None:
                continue
            detection = self._build(row, protos, mapped)
            if detection is not None:
                detections.append(detection)
        return detections

    # -- 전처리 ------------------------------------------------------------

    def _preprocess(self, frame_bgr: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
        """rect letterbox. **정사각으로 만들지 않는다**(기능명세서 §5)."""
        box = self._letterbox
        resized = cv2.resize(
            frame_bgr,
            (box.resized_width, box.resized_height),
            interpolation=cv2.INTER_LINEAR,
        )
        canvas = np.full((box.model_height, box.model_width, 3), _PAD_VALUE, dtype=np.uint8)
        top, left = int(box.pad_y), int(box.pad_x)
        canvas[top : top + box.resized_height, left : left + box.resized_width] = resized
        rgb = canvas[:, :, ::-1].astype(np.float32) / 255.0
        return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])

    # -- 후처리 ------------------------------------------------------------

    def _map_class(self, index: int) -> ObjectClass | None:
        """모델 클래스 인덱스 → 계약 클래스. 표에 없으면 `None`(버린다).

        **버린 사실을 한 번은 남긴다.** 학습 라벨을 바꿨는데 `classes:` 표를 안 고치면
        감지가 통째로 사라지는데, 로그가 없으면 "모델이 못 찾는다"로 오해한다.
        """
        name = self._names.get(index)
        if name is None:
            return None
        mapped = self._config.class_map.get(name)
        if mapped is None and name not in self._unmapped:
            self._unmapped.add(name)
            log.warning(
                "모델 클래스 %r 이 config 의 detect.classes 에 없다 — 이 클래스는 버린다",
                name,
            )
        return mapped

    def _build(
        self,
        row: npt.NDArray[np.float32],
        protos: npt.NDArray[np.float32],
        object_class: ObjectClass,
    ) -> Detection | None:
        box = self._letterbox
        x1, y1, x2, y2 = (float(value) for value in row[:4])
        contour = _contour(row[6:], protos, (x1, y1, x2, y2), box)
        if contour is None:
            # 마스크가 비었다. 게이지도 거리도 낼 수 없으므로 **박스만 올리지 않는다** —
            # 마스크 없는 사람을 섞어 보내면 서버가 후보의 근거를 확인할 수 없다.
            return None
        top_left = box.to_normalized(x1, y1)
        bottom_right = box.to_normalized(x2, y2)
        return Detection(
            object_class=object_class,
            conf=float(row[4]),
            bbox=(top_left[0], top_left[1], bottom_right[0], bottom_right[1]),
            contour=contour,
            box_height_px=(y2 - y1) / box.scale,
        )


# --------------------------------------------------------------------------
# 내부
# --------------------------------------------------------------------------


def _contour(
    coefficients: npt.NDArray[np.float32],
    protos: npt.NDArray[np.float32],
    bbox_model: tuple[float, float, float, float],
    box: Letterbox,
) -> tuple[PointPx, ...] | None:
    """마스크 계수 → 정규화 좌표의 윤곽.

    프로토타입 해상도(96×160)에서 조합한 뒤 **박스 영역만** 원래 크기로 늘린다.
    전체를 늘리면 프레임당 384×640 보간이 감지 수만큼 생기는데, 레고 미니피겨처럼
    작은 대상은 박스가 프레임의 몇 %라 그 비용의 대부분이 버려진다.
    """
    channels = protos.shape[0]
    combined = coefficients[:channels] @ protos.reshape(channels, -1)
    mask = 1.0 / (1.0 + np.exp(-combined.reshape(protos.shape[1], protos.shape[2])))

    # 프로토타입 격자에 맞춰 자른다. 잘라낸 조각이 덮는 **모델 좌표 영역**이 그대로
    # 원점이 되므로, 박스 크기로 늘이지 않고 격자 배수 크기로 늘인다 — 박스 크기에
    # 맞추면 floor/ceil 로 생긴 반 칸이 스케일 오차로 남는다.
    x1, y1, x2, y2 = bbox_model
    px1 = max(int(x1 // _PROTO_STRIDE), 0)
    py1 = max(int(y1 // _PROTO_STRIDE), 0)
    px2 = min(int(np.ceil(x2 / _PROTO_STRIDE)), mask.shape[1])
    py2 = min(int(np.ceil(y2 / _PROTO_STRIDE)), mask.shape[0])
    if px2 <= px1 or py2 <= py1:
        return None

    origin_x = px1 * _PROTO_STRIDE
    origin_y = py1 * _PROTO_STRIDE
    width = (px2 - px1) * _PROTO_STRIDE
    height = (py2 - py1) * _PROTO_STRIDE
    crop = cv2.resize(mask[py1:py2, px1:px2], (width, height), interpolation=cv2.INTER_LINEAR)
    binary = (crop >= _MASK_THRESHOLD).astype(np.uint8)

    # **박스 밖을 지운다.** 조각이 박스보다 최대 한 칸 크므로 옆에 붙어 선 다른 사람의
    # 마스크가 함께 들어올 수 있고, 그러면 아래에서 고르는 「가장 큰 윤곽」이 남의 것이
    # 될 수 있다. 실제로 사람이 겹쳐 서 있을 때 나는 오류다(ultralytics `crop_mask` 와
    # 같은 처리).
    inner = np.zeros_like(binary)
    ix1 = max(round(x1 - origin_x), 0)
    iy1 = max(round(y1 - origin_y), 0)
    ix2 = min(round(x2 - origin_x), width)
    iy2 = min(round(y2 - origin_y), height)
    if ix2 <= ix1 or iy2 <= iy1:
        return None
    inner[iy1:iy2, ix1:ix2] = binary[iy1:iy2, ix1:ix2]

    contours, _ = cv2.findContours(inner, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(np.float32)
    if len(largest) < 3:
        return None
    if len(largest) > _MAX_CONTOUR_POINTS:
        step = len(largest) / _MAX_CONTOUR_POINTS
        indices = (np.arange(_MAX_CONTOUR_POINTS) * step).astype(np.int32)
        largest = largest[indices]

    return tuple(
        box.to_normalized(origin_x + float(px), origin_y + float(py)) for px, py in largest
    )
