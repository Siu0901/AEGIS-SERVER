"""ONNX 세션 한 겹. 모델 세 개(감지·분류·뎁스)가 같은 방식으로 열리게 한다.

젯슨(TensorRT)으로 옮길 때 **바뀌는 곳을 여기 하나로 모은다.** 부르는 쪽은
`Session(path, runtime).run(blob)` 만 알면 되므로, 백엔드가 바뀌어도 감지·분류·뎁스
코드는 그대로다.

클래스 이름 파싱도 여기 있다 — ultralytics 가 ONNX 메타데이터에 `names` 를 파이썬
리터럴 문자열로 넣어 두는데, 세 모델이 같은 규약을 쓰므로 한 곳에서 읽는다.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from .config import RuntimeConfig

__all__ = ["Session"]

log = logging.getLogger(__name__)


class Session:
    """ONNX 추론 세션. 입력이 하나인 모델만 다룬다(세 모델 모두 그렇다)."""

    def __init__(self, path: Path, runtime: RuntimeConfig) -> None:
        options = ort.SessionOptions()
        if runtime.intra_op_threads:
            # **둘 다 막아야 한다.** `intra_op` 만 정하면 `inter_op` 이 여전히 논리 코어
            # 수만큼 잡혀서 상한이 새어 나간다. 같이 굶는 것은 같은 노트북에서 도는
            # ffmpeg 송출이고, 그러면 라이브가 검게 죽는다(`edge/config.yaml` 주석).
            options.intra_op_num_threads = runtime.intra_op_threads
            options.inter_op_num_threads = runtime.intra_op_threads
        providers = list(runtime.providers) or ["CPUExecutionProvider"]
        self._session = ort.InferenceSession(str(path), options, providers=providers)
        self._input = self._session.get_inputs()[0].name
        self._path = path

    @property
    def input_name(self) -> str:
        return str(self._input)

    def accepts_batch(self) -> bool:
        """입력의 배치 축이 열려 있는가.

        ONNX 를 `dynamic=False` 로 내보내면 배치가 1로 **고정**되고, 크롭을 여러 장
        묶어 넣는 순간 `Got: 4 Expected: 1` 로 죽는다. 부르는 쪽이 미리 확인해서
        설정과 모델이 어긋난 사실을 드러낼 수 있게 한다.
        """
        shape = self._session.get_inputs()[0].shape
        return bool(shape) and not isinstance(shape[0], int)

    def run(self, blob: npt.NDArray[np.float32]) -> list[npt.NDArray[np.float32]]:
        outputs = self._session.run(None, {self._input: blob})
        return [np.asarray(item, dtype=np.float32) for item in outputs]

    def metadata(self, key: str) -> str | None:
        value = self._session.get_modelmeta().custom_metadata_map.get(key)
        return None if value is None else str(value)

    def class_names(self) -> dict[int, str]:
        """모델이 학습한 클래스 이름.

        **읽지 못하면 인덱스로 대체하지 않는다.** 인덱스로 매핑하면 학습 순서가 바뀐
        모델에서 사람과 차량이 조용히 뒤바뀐 채 돈다 — 빈 표를 돌려주고 로그를 남겨서
        「매핑이 없다」로 드러나게 한다(절대규칙 9).
        """
        raw = self.metadata("names")
        if not raw:
            log.error("%s: 메타데이터에 클래스 이름이 없다 — 매핑할 수 없다", self._path.name)
            return {}
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            log.exception("%s: 클래스 이름을 읽지 못했다: %r", self._path.name, raw)
            return {}
        if not isinstance(parsed, dict):
            log.error("%s: 클래스 이름이 매핑이 아니다: %r", self._path.name, raw)
            return {}
        return {int(index): str(name) for index, name in parsed.items()}
