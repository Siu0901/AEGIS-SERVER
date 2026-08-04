"""2단계 안전모 분류 — 사람 크롭 → `on` / `off`. FN-DET-04 · FN-DET-05

**안전모에는 별도 bbox 가 없다.** 1단계는 `person` · `vehicle` 2클래스뿐이고, 안전모는
사람 크롭을 이 모델이 판정한다. 화면에는 사람 박스의 색으로 표현된다.

**`unknown` 이라는 값은 없다.** 크기·신뢰도 게이트를 통과하지 못하면 `None` 을 돌려주고,
부르는 쪽이 **직전 값을 유지하거나 필드를 생략**한다(§6.3). 게이트 미통과를 세 번째
클래스로 만들면 서버가 그것을 「판정 결과」로 받아 타이머를 리셋한다 — 명세는 그때
타이머를 **동결**하라고 정한다.

게이트 값(`cls_min_crop_px` · `cls_min_conf` · `cls_cache_ms`)은 **여기 없다.**
현장에서 화면으로 조정하는 값이라 서버 `policies` 소관이고, 매 호출에 주입받는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from aegis_contracts.enums import HelmetState

from .config import ClassifyConfig, RuntimeConfig
from .detect import Detection
from .session import Session

__all__ = ["HelmetClassifier", "HelmetReading"]

log = logging.getLogger(__name__)

#: ultralytics 분류 전처리의 패딩 색. 학습 파이프라인과 같아야 한다.
_PAD_VALUE = 114


@dataclass(frozen=True, slots=True)
class HelmetReading:
    """분류 결과 하나. 게이트를 통과한 것만 만들어진다."""

    helmet: HelmetState
    conf: float
    cached: bool
    """캐시에서 나왔는가. `heartbeat.cls_cache_hit_rate`(§2.4)가 이것을 센다."""


@dataclass(slots=True)
class _CacheEntry:
    reading: HelmetReading
    at_s: float


class HelmetClassifier:
    """사람 크롭을 배치로 분류한다. 트랙별 캐시로 호출 수를 줄인다(FN-DET-05)."""

    def __init__(self, config: ClassifyConfig, runtime: RuntimeConfig) -> None:
        self._config = config
        self._session = Session(config.model_path, runtime)
        self._names = self._session.class_names()
        # 설정이 배치를 켰는데 모델의 배치 축이 1로 고정돼 있으면, 사람이 두 명 이상
        # 잡히는 첫 프레임에서 죽는다. **조용히 넘어가지 않고** 한 장씩으로 내리되
        # 원인과 고치는 법을 남긴다(절대규칙 9).
        self._batch = config.batch and self._session.accepts_batch()
        if config.batch and not self._batch:
            log.error(
                "%s 는 배치 축이 1로 고정돼 있다 — 한 장씩 추론한다."
                " 배치를 쓰려면 `uv run python -m scripts.export_onnx` 로 다시 내보내라"
                " (분류 모델은 dynamic=True 로 나간다)",
                config.model_path.name,
            )
        self._cache: dict[int, _CacheEntry] = {}
        self._calls = 0
        self._hits = 0
        self._gated_small = 0
        log.info(
            "분류 모델 적재 — %s (클래스 %s → %s)",
            config.model_path.name,
            list(self._names.values()),
            dict(config.class_map),
        )

    # -- 계측 (heartbeat §2.4) ---------------------------------------------

    @property
    def calls(self) -> int:
        """실제 모델 호출 수. 캐시 적중은 세지 않는다."""
        return self._calls

    @property
    def cache_hit_rate(self) -> float:
        total = self._calls + self._hits
        return self._hits / total if total else 0.0

    @property
    def gated_small(self) -> int:
        """크기 게이트에 걸려 분류하지 못한 횟수. **드러나야 하는 수치다** —
        카메라가 너무 멀면 안전모 판정이 통째로 사라지는데, 그 사실이 조용하면
        「위반이 없다」로 읽힌다."""
        return self._gated_small

    # -- 분류 --------------------------------------------------------------

    def classify(
        self,
        frame_bgr: npt.NDArray[np.uint8],
        detections: dict[int, Detection],
        *,
        at_s: float,
        min_crop_px: int,
        min_conf: float,
        cache_ms: float,
    ) -> dict[int, HelmetReading]:
        """트랙별 안전모 판정. 게이트를 통과한 트랙만 결과에 담긴다.

        `detections` 는 `{track_id: Detection}` 이며 **사람만** 담겨 있어야 한다.
        """
        results: dict[int, HelmetReading] = {}
        pending: list[tuple[int, npt.NDArray[np.float32]]] = []

        for track_id, detection in detections.items():
            if detection.box_height_px < min_crop_px:
                # 원거리라 크롭이 작다. 판정하지 않고 **직전 값도 새로 만들지 않는다** —
                # 부르는 쪽이 캐시된 마지막 판정을 유지할지 필드를 뺄지 정한다.
                self._gated_small += 1
                continue
            cached = self._cache.get(track_id)
            if cached is not None and (at_s - cached.at_s) * 1000.0 <= cache_ms:
                self._hits += 1
                results[track_id] = HelmetReading(
                    helmet=cached.reading.helmet, conf=cached.reading.conf, cached=True
                )
                continue
            crop = self._crop(frame_bgr, detection)
            if crop is not None:
                pending.append((track_id, crop))

        for track_id, reading in self._run(pending, min_conf=min_conf):
            results[track_id] = reading
            self._cache[track_id] = _CacheEntry(reading=reading, at_s=at_s)

        return results

    def forget(self, track_ids: set[int]) -> None:
        """소실된 트랙의 캐시를 버린다. 새 트랙이 같은 번호를 받을 수 있다."""
        for track_id in track_ids:
            self._cache.pop(track_id, None)

    # -- 내부 --------------------------------------------------------------

    def _crop(
        self,
        frame_bgr: npt.NDArray[np.uint8],
        detection: Detection,
    ) -> npt.NDArray[np.float32] | None:
        """사람 박스를 잘라 모델 입력으로 만든다.

        **비율을 유지한 채 패딩한다**(ultralytics `ClassifyLetterBox`). 정사각으로
        찌그러뜨리면 세로로 긴 사람 크롭이 학습 때와 다른 형태가 되어, 같은 사람이
        가까이 있을 때와 멀리 있을 때 다른 판정을 받는다.
        """
        height, width = frame_bgr.shape[:2]
        x1, y1, x2, y2 = detection.bbox
        px1 = max(round(x1 * width), 0)
        py1 = max(round(y1 * height), 0)
        px2 = min(round(x2 * width), width)
        py2 = min(round(y2 * height), height)
        if px2 <= px1 or py2 <= py1:
            return None

        crop = frame_bgr[py1:py2, px1:px2]
        size = self._config.input_size
        scale = min(size / crop.shape[0], size / crop.shape[1])
        new_w = max(round(crop.shape[1] * scale), 1)
        new_h = max(round(crop.shape[0] * scale), 1)
        resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((size, size, 3), _PAD_VALUE, dtype=np.uint8)
        top = (size - new_h) // 2
        left = (size - new_w) // 2
        canvas[top : top + new_h, left : left + new_w] = resized
        rgb = canvas[:, :, ::-1].astype(np.float32) / 255.0
        return np.ascontiguousarray(rgb.transpose(2, 0, 1))

    def _run(
        self,
        pending: list[tuple[int, npt.NDArray[np.float32]]],
        *,
        min_conf: float,
    ) -> list[tuple[int, HelmetReading]]:
        """모델을 부른다. 배치가 허용되면 한 번에, 아니면 하나씩."""
        if not pending:
            return []
        crops = [crop for _, crop in pending]
        batches = [np.stack(crops)] if self._batch else [crop[None] for crop in crops]

        scores: list[npt.NDArray[np.float32]] = []
        for batch in batches:
            self._calls += batch.shape[0]
            scores.append(np.asarray(self._session.run(batch)[0], dtype=np.float32))
        stacked = np.concatenate(scores, axis=0)

        readings: list[tuple[int, HelmetReading]] = []
        for (track_id, _), row in zip(pending, stacked, strict=True):
            index = int(np.argmax(row))
            conf = float(row[index])
            if conf < min_conf:
                # 신뢰도 미달. **낮은 확신을 결과로 만들지 않는다** — 부르는 쪽이
                # 직전 값을 유지하거나 필드를 생략한다(§6.3).
                continue
            name = self._names.get(index)
            mapped = self._config.class_map.get(name) if name is not None else None
            if mapped is None:
                log.warning("분류 클래스 %r 이 config 의 classify.classes 에 없다", name)
                continue
            readings.append((track_id, HelmetReading(helmet=mapped, conf=conf, cached=False)))
        return readings
