"""추론 세션 한 겹. 모델 세 개(감지·분류·뎁스)가 같은 방식으로 열리게 한다.

**백엔드가 갈리는 곳은 여기 하나다.** 부르는 쪽은 `Session(path, runtime).run(blob)`
만 알면 되므로, 노트북(onnxruntime · CPU)이든 젯슨(TensorRT · GPU)이든 감지·분류·뎁스
코드는 그대로다.

| | 노트북 | 젯슨 Orin Nano |
|---|---|---|
| `runtime.backend` | `onnx` | `tensorrt` |
| 모델 파일 | `models/weights/*.onnx` | `models/engines/*.engine` |

클래스 이름 파싱도 여기 있다 — 세 모델이 같은 규약을 쓰므로 한 곳에서 읽는다.
다만 **어디서 읽는지는 백엔드마다 다르다.** ONNX 는 파일 안의 메타데이터에 들어 있고,
TensorRT 엔진은 그것을 물고 가지 않으므로 엔진 옆 사이드카 JSON 에서 읽는다
(`scripts/build_engines.py` 가 빌드할 때 함께 써 둔다).

**무거운 의존성은 지연 import 한다.** `tensorrt` 와 `cuda` 는 젯슨에만 있고,
`onnxruntime` 은 노트북에만 둘 수도 있다. 모듈을 읽는 것만으로 없는 쪽이 죽으면
같은 코드가 두 기계에서 돈다는 전제가 깨진다.
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
import numpy.typing as npt

from .config import RuntimeConfig

if TYPE_CHECKING:
    from types import TracebackType

__all__ = ["Session"]

log = logging.getLogger(__name__)

#: 클래스 이름 사이드카. `foo.engine` 옆의 `foo.names.json` 을 본다.
#: ONNX 와 엔진이 같은 이름을 쓰므로 확장자만 갈아 끼우면 양쪽 다 같은 규약이 된다.
_NAMES_SUFFIX = ".names.json"


class _Backend(Protocol):
    """세션 구현이 갖춰야 할 것. 두 백엔드가 이 모양을 맞춘다."""

    @property
    def input_name(self) -> str: ...

    def accepts_batch(self) -> bool: ...

    def run(self, blob: npt.NDArray[np.float32]) -> list[npt.NDArray[np.float32]]: ...

    def metadata(self, key: str) -> str | None: ...


class Session:
    """추론 세션. 입력이 하나인 모델만 다룬다(세 모델 모두 그렇다)."""

    def __init__(self, path: Path, runtime: RuntimeConfig) -> None:
        self._path = path
        # **모르는 백엔드를 조용히 onnx 로 떨어뜨리지 않는다.** 오타 하나로 젯슨이
        # CPU 추론을 돌면 8fps 가 안 나오는 이유를 한참 찾게 된다(절대규칙 9).
        if runtime.backend == "onnx":
            self._impl: _Backend = _OnnxBackend(path, runtime)
        elif runtime.backend == "tensorrt":
            self._impl = _TensorRTBackend(path)
        else:
            msg = f"모르는 추론 백엔드다: {runtime.backend!r} (쓸 수 있는 것: onnx · tensorrt)"
            raise ValueError(msg)

    @property
    def input_name(self) -> str:
        return self._impl.input_name

    def accepts_batch(self) -> bool:
        """입력의 배치 축이 열려 있는가.

        ONNX 를 `dynamic=False` 로 내보내면 배치가 1로 **고정**되고, 크롭을 여러 장
        묶어 넣는 순간 `Got: 4 Expected: 1` 로 죽는다. 부르는 쪽이 미리 확인해서
        설정과 모델이 어긋난 사실을 드러낼 수 있게 한다.
        """
        return self._impl.accepts_batch()

    def run(self, blob: npt.NDArray[np.float32]) -> list[npt.NDArray[np.float32]]:
        return self._impl.run(blob)

    def metadata(self, key: str) -> str | None:
        return self._impl.metadata(key)

    def class_names(self) -> dict[int, str]:
        """모델이 학습한 클래스 이름.

        **읽지 못하면 인덱스로 대체하지 않는다.** 인덱스로 매핑하면 학습 순서가 바뀐
        모델에서 사람과 차량이 조용히 뒤바뀐 채 돈다 — 빈 표를 돌려주고 로그를 남겨서
        「매핑이 없다」로 드러나게 한다(절대규칙 9).
        """
        raw = self._impl.metadata("names")
        if raw is None:
            raw = _sidecar_names(self._path)
        if not raw:
            log.error(
                "%s: 클래스 이름을 찾지 못했다 — 매핑할 수 없다 (사이드카: %s)",
                self._path.name,
                self._path.with_suffix(_NAMES_SUFFIX).name,
            )
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


def _sidecar_names(path: Path) -> str | None:
    """엔진 옆 `<이름>.names.json` 을 읽어 파이썬 리터럴 문자열로 돌려준다.

    ONNX 메타데이터와 **같은 모양으로 맞춰서** 돌려주므로, 부르는 쪽은 어디서 왔는지
    알 필요가 없다. 파일이 없거나 깨졌으면 `None` 이고 그 사실은 부르는 쪽이 로그로
    드러낸다.
    """
    sidecar = path.with_suffix(_NAMES_SUFFIX)
    if not sidecar.is_file():
        return None
    try:
        loaded = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.exception("%s: 사이드카를 읽지 못했다", sidecar.name)
        return None
    if not isinstance(loaded, dict):
        log.error("%s: 사이드카가 매핑이 아니다: %r", sidecar.name, loaded)
        return None
    return repr({int(index): str(name) for index, name in loaded.items()})


class _OnnxBackend:
    """onnxruntime. 노트북(CPU)에서 쓴다."""

    def __init__(self, path: Path, runtime: RuntimeConfig) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        if runtime.intra_op_threads:
            # **둘 다 막아야 한다.** `intra_op` 만 정하면 `inter_op` 이 여전히 논리 코어
            # 수만큼 잡혀서 상한이 새어 나간다. 같이 굶는 것은 같은 노트북에서 도는
            # ffmpeg 송출이고, 그러면 라이브가 검게 죽는다(`edge/config.yaml` 주석).
            options.intra_op_num_threads = runtime.intra_op_threads
            options.inter_op_num_threads = runtime.intra_op_threads
        providers = list(runtime.providers) or ["CPUExecutionProvider"]
        self._session = ort.InferenceSession(str(path), options, providers=providers)
        self._input = str(self._session.get_inputs()[0].name)

    @property
    def input_name(self) -> str:
        return self._input

    def accepts_batch(self) -> bool:
        shape = self._session.get_inputs()[0].shape
        return bool(shape) and not isinstance(shape[0], int)

    def run(self, blob: npt.NDArray[np.float32]) -> list[npt.NDArray[np.float32]]:
        outputs = self._session.run(None, {self._input: blob})
        return [np.asarray(item, dtype=np.float32) for item in outputs]

    def metadata(self, key: str) -> str | None:
        value = self._session.get_modelmeta().custom_metadata_map.get(key)
        return None if value is None else str(value)


class _TensorRTBackend:
    """TensorRT. 젯슨(GPU)에서 쓴다.

    **엔진은 빌드한 GPU·TensorRT 버전에 종속된다.** 노트북에서 만든 엔진은 젯슨에서
    열리지 않으므로 `scripts/build_engines.py` 를 젯슨에서 돌려야 한다.

    TensorRT 10 의 텐서 이름 기반 API(`set_input_shape` · `set_tensor_address` ·
    `execute_async_v3`)를 쓴다. JetPack 6 이 싣는 버전이다.
    """

    def __init__(self, path: Path) -> None:
        import tensorrt as trt
        from cuda import cudart

        self._trt = trt
        self._cudart = cudart
        self._path = path

        logger = trt.Logger(trt.Logger.WARNING)
        # `init_libnvinfer_plugins` — YOLO 계열이 NMS 플러그인을 쓰면 이것 없이는
        # 역직렬화가 조용히 None 을 돌려준다.
        trt.init_libnvinfer_plugins(logger, "")
        runtime = trt.Runtime(logger)
        engine = runtime.deserialize_cuda_engine(path.read_bytes())
        if engine is None:
            msg = (
                f"TensorRT 엔진을 열지 못했다: {path}. "
                "다른 GPU 나 다른 TensorRT 버전에서 빌드한 엔진일 수 있다 — "
                "젯슨에서 scripts/build_engines.py 로 다시 빌드해라."
            )
            raise RuntimeError(msg)
        self._engine = engine
        self._context = engine.create_execution_context()

        names = [engine.get_tensor_name(i) for i in range(engine.num_io_tensors)]
        inputs = [n for n in names if engine.get_tensor_mode(n) == trt.TensorIOMode.INPUT]
        if len(inputs) != 1:
            msg = f"입력이 하나인 엔진만 다룬다: {path.name} 의 입력 {len(inputs)}개 {inputs}"
            raise RuntimeError(msg)
        self._input = str(inputs[0])
        self._outputs = [n for n in names if engine.get_tensor_mode(n) == trt.TensorIOMode.OUTPUT]

        err, self._stream = cudart.cudaStreamCreate()
        _check(cudart, err, "cudaStreamCreate")
        #: 텐서 이름 → (디바이스 포인터, 잡아 둔 바이트). **크기별로 다시 잡지 않고
        #: 키운다** — 프레임마다 cudaMalloc 하면 그 자체가 병목이 된다.
        self._buffers: dict[str, tuple[int, int]] = {}

    @property
    def input_name(self) -> str:
        return self._input

    def accepts_batch(self) -> bool:
        """엔진 프로파일의 배치 축이 열려 있는가.

        `-1` 이면 동적이라 크롭을 묶어 넣을 수 있다. `trtexec` 에 `--minShapes` 등을
        주지 않고 빌드하면 ONNX 의 고정 배치가 그대로 굳으므로 여기서 드러난다.
        """
        shape = self._engine.get_tensor_shape(self._input)
        return bool(len(shape)) and int(shape[0]) == -1

    def run(self, blob: npt.NDArray[np.float32]) -> list[npt.NDArray[np.float32]]:
        cudart = self._cudart
        contiguous = np.ascontiguousarray(blob, dtype=np.float32)
        self._context.set_input_shape(self._input, contiguous.shape)
        if not self._context.all_shape_inputs_specified:
            msg = f"{self._path.name}: 입력 모양이 정해지지 않았다 — {contiguous.shape}"
            raise RuntimeError(msg)

        source = self._reserve(self._input, contiguous.nbytes)
        _check(
            cudart,
            cudart.cudaMemcpyAsync(
                source,
                contiguous.ctypes.data,
                contiguous.nbytes,
                cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
                self._stream,
            )[0],
            "cudaMemcpyAsync(H2D)",
        )
        self._context.set_tensor_address(self._input, source)

        # 출력 버퍼는 **입력 모양을 넣은 뒤에** 잡는다. 동적 배치면 출력 모양이
        # 입력에 따라 달라지므로, 먼저 잡으면 배치 2 부터 모자란다.
        holders: list[tuple[str, npt.NDArray[np.float32], int]] = []
        for name in self._outputs:
            shape = tuple(int(dim) for dim in self._context.get_tensor_shape(name))
            dtype = self._trt.nptype(self._engine.get_tensor_dtype(name))
            host = np.empty(shape, dtype=dtype)
            device = self._reserve(name, host.nbytes)
            self._context.set_tensor_address(name, device)
            holders.append((name, host, device))

        if not self._context.execute_async_v3(self._stream):
            msg = f"{self._path.name}: TensorRT 추론이 실패했다"
            raise RuntimeError(msg)

        for _, host, device in holders:
            _check(
                cudart,
                cudart.cudaMemcpyAsync(
                    host.ctypes.data,
                    device,
                    host.nbytes,
                    cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                    self._stream,
                )[0],
                "cudaMemcpyAsync(D2H)",
            )
        _check(cudart, cudart.cudaStreamSynchronize(self._stream)[0], "cudaStreamSynchronize")

        # FP16 엔진은 반정밀도로 뱉는다. 부르는 쪽(감지·분류·뎁스)은 float32 를
        # 기대하므로 여기서 맞춘다 — ONNX 경로와 같은 계약이다.
        return [np.asarray(host, dtype=np.float32) for _, host, _ in holders]

    def metadata(self, key: str) -> str | None:
        """엔진은 ONNX 메타데이터를 물고 가지 않는다.

        `None` 을 돌려주면 부르는 쪽이 사이드카를 본다. 여기서 빈 문자열이나 인덱스를
        지어내면 사이드카가 없는 사실이 묻힌다.
        """
        _ = key
        return None

    def _reserve(self, name: str, nbytes: int) -> int:
        """이 텐서용 디바이스 버퍼를 확보한다. 이미 충분히 크면 그대로 쓴다."""
        held = self._buffers.get(name)
        if held is not None and held[1] >= nbytes:
            return held[0]
        if held is not None:
            _check(self._cudart, self._cudart.cudaFree(held[0])[0], "cudaFree")
        err, pointer = self._cudart.cudaMalloc(nbytes)
        _check(self._cudart, err, f"cudaMalloc({nbytes})")
        self._buffers[name] = (int(pointer), nbytes)
        return int(pointer)

    def close(self) -> None:
        for pointer, _ in self._buffers.values():
            self._cudart.cudaFree(pointer)
        self._buffers.clear()
        if getattr(self, "_stream", None):
            self._cudart.cudaStreamDestroy(self._stream)
            self._stream = 0

    def __enter__(self) -> _TensorRTBackend:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _check(cudart: object, err: object, what: str) -> None:
    """CUDA 반환코드를 확인한다. **삼키지 않는다** — 실패한 복사는 조용히 0을 남긴다."""
    success = cudart.cudaError_t.cudaSuccess  # type: ignore[attr-defined]
    if err != success:
        msg = f"CUDA 오류 {err} — {what}"
        raise RuntimeError(msg)
