"""온디맨드 뎁스 검증 — `aegis_vision.DepthProbe` 구현. FN-DET-11

★ **거리 수치를 내지 않는다**(CLAUDE.md 절대규칙 4). 단안 뎁스는 절대거리가 부정확해서
「몇 미터」로 쓸 수 없다. 여기서 답하는 것은 둘뿐이다.

| 답 | 쓰임 |
|---|---|
| `same_plane` | 사람과 지게차가 앞뒤로 분리됐는가 — 원근 착시 기각(§6.6) |
| `depth_variance` | 사람 마스크의 깊이가 퍼져 있는가 — 누운 자세 보강(FN-DET-10) |

**상대 역깊이라 스케일이 없다.** Depth Anything 의 출력은 「가까울수록 큰 값」인 상대
지도이고 프레임마다 스케일이 달라진다. 그래서 두 영역의 차이를 **그 프레임의 깊이
범위로 나눠** 비교한다 — 절대값끼리 비교하면 밝기가 바뀌는 것만으로 판정이 뒤집힌다.

**프레임당 한 번만 돌린다.** 트리거가 여러 쌍에서 걸려도 깊이 지도는 프레임에 하나다.
`bind()` 로 프레임을 걸어 두고 첫 `measure()` 에서 계산해 그 프레임 안에서 재사용한다.
"""

from __future__ import annotations

import logging
import time

import cv2
import numpy as np
import numpy.typing as npt

from aegis_vision import Bbox
from aegis_vision.depth import DepthResult

from .config import DepthConfig, RuntimeConfig
from .session import Session

__all__ = ["DepthEstimator"]

log = logging.getLogger(__name__)

#: ImageNet 정규화. Depth Anything V2 의 전처리와 같아야 한다.
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

#: 모델 입력은 14의 배수여야 한다(ViT 패치 크기). 아니면 출력이 잘린다.
_PATCH = 14

#: 프레임 깊이 범위를 재는 백분위. 최대·최소를 쓰면 한 점의 이상치가 분모를 지배한다.
_LOW_PERCENTILE = 5.0
_HIGH_PERCENTILE = 95.0


class DepthEstimator:
    """단안 뎁스 한 장을 만들고 영역끼리 비교한다.

    `aegis_vision.DepthProbe` 프로토콜을 만족하므로 `verify_depth` 에 그대로 넣는다.
    """

    def __init__(
        self,
        config: DepthConfig,
        runtime: RuntimeConfig,
        *,
        separation_max: float,
        variance_scale: float,
    ) -> None:
        if config.model_path is None:  # pragma: no cover - 부르는 쪽이 먼저 확인한다
            msg = "뎁스 모델 경로가 없다 — DepthEstimator 를 만들면 안 된다"
            raise ValueError(msg)
        self._session = Session(config.model_path, runtime)
        self._size = config.input_size - (config.input_size % _PATCH)
        self._separation_max = separation_max
        self._variance_scale = variance_scale
        self._frame: npt.NDArray[np.uint8] | None = None
        self._depth: npt.NDArray[np.float32] | None = None
        self._span: float = 1.0
        self._calls = 0
        self._elapsed_s = 0.0
        log.info(
            "뎁스 모델 적재 — %s (입력 %d×%d)",
            config.model_path.name,
            self._size,
            self._size,
        )

    @property
    def calls(self) -> int:
        """모델 호출 수. `heartbeat.depth_calls_per_min`(§2.4)이 이것을 센다."""
        return self._calls

    @property
    def mean_latency_ms(self) -> float:
        return (self._elapsed_s / self._calls * 1000.0) if self._calls else 0.0

    def bind(self, frame_bgr: npt.NDArray[np.uint8]) -> None:
        """이 프레임을 대상으로 삼는다. **아직 모델을 부르지 않는다.**

        트리거가 하나도 걸리지 않는 프레임이 대부분이므로(§6.6), 실제 계산은 첫
        `measure()` 까지 미룬다 — 그것이 「온디맨드」의 의미다.
        """
        self._frame = frame_bgr
        self._depth = None

    def measure(self, *, person_bbox: Bbox, vehicle_bbox: Bbox | None) -> DepthResult:
        """`DepthProbe` 프로토콜. 깊이 지도가 없으면 이 호출에서 만든다."""
        depth = self._ensure()
        if depth is None:
            # 프레임이 없다. **`same_plane=True` 로 답하지 않는다** — 참으로 답하면
            # 근접 위반이 「검증됨」으로 통과한다. 모르는 것은 모른다고 한다.
            return DepthResult(same_plane=False)

        person = _region(depth, person_bbox)
        if person.size == 0:
            return DepthResult(same_plane=False)
        variance = float(np.var(person)) / (self._span**2) * self._variance_scale

        if vehicle_bbox is None:
            # 쓰러짐 보강(트리거 D). 비교 대상이 없으므로 분산만 답한다.
            return DepthResult(same_plane=False, depth_variance=round(variance, 4))

        vehicle = _region(depth, vehicle_bbox)
        if vehicle.size == 0:
            return DepthResult(same_plane=False, depth_variance=round(variance, 4))

        separation = abs(float(np.median(person)) - float(np.median(vehicle))) / self._span
        return DepthResult(
            same_plane=separation <= self._separation_max,
            depth_variance=round(variance, 4),
        )

    # -- 내부 --------------------------------------------------------------

    def _ensure(self) -> npt.NDArray[np.float32] | None:
        if self._depth is not None:
            return self._depth
        if self._frame is None:
            return None
        started = time.perf_counter()
        self._depth = self._infer(self._frame)
        self._elapsed_s += time.perf_counter() - started
        self._calls += 1
        low, high = np.percentile(self._depth, [_LOW_PERCENTILE, _HIGH_PERCENTILE])
        # 범위가 0에 가까우면 (평평한 벽 등) 나눗셈이 폭주한다. 그때는 분리를 못 보는
        # 것이므로 분모를 1로 두어 separation 이 0 에 머물게 한다 — 같은 평면으로 본다.
        self._span = max(float(high) - float(low), 1e-6)
        return self._depth

    def _infer(self, frame_bgr: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
        resized = cv2.resize(frame_bgr, (self._size, self._size), interpolation=cv2.INTER_LINEAR)
        rgb = resized[:, :, ::-1].astype(np.float32) / 255.0
        normalized = (rgb - _MEAN) / _STD
        blob = np.ascontiguousarray(normalized.transpose(2, 0, 1)[None])
        raw = self._session.run(blob)[0]
        depth = raw[0] if raw.ndim == 3 else raw
        # 정규화 좌표로 바로 색인할 수 있도록 프레임 크기로 되돌린다.
        height, width = frame_bgr.shape[:2]
        resized = cv2.resize(depth, (width, height), interpolation=cv2.INTER_LINEAR)
        return np.asarray(resized, dtype=np.float32)


def _region(depth: npt.NDArray[np.float32], bbox: Bbox) -> npt.NDArray[np.float32]:
    """정규화 bbox 안의 깊이 값들. 프레임 밖으로 나간 부분은 잘라낸다."""
    height, width = depth.shape[:2]
    x1 = max(round(bbox[0] * width), 0)
    y1 = max(round(bbox[1] * height), 0)
    x2 = min(round(bbox[2] * width), width)
    y2 = min(round(bbox[3] * height), height)
    if x2 <= x1 or y2 <= y1:
        return np.empty(0, dtype=np.float32)
    return depth[y1:y2, x1:x2].reshape(-1)
