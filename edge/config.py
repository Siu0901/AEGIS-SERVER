"""`edge/config.yaml` 로딩. 모델 경로·입력 형태·백엔드를 코드에 적지 않는다.

CLAUDE.md 절대규칙 6 — 모델 경로·임계값·튜닝 파라미터를 코드에 하드코딩하지 않는다.
여기 있는 것은 **장비에 종속된 값**뿐이고, 판정 임계값(확정·해소 지속시간, 근접 임계,
분류 게이트)은 서버 DB `policies` 에서 받는다(`edge/client.py`).

**같은 코드가 노트북과 젯슨에서 돈다.** 다른 것은 `runtime.backend` 하나다.

| | 노트북 (지금) | 젯슨 (M9) |
|---|---|---|
| `runtime.backend` | `onnx` | `tensorrt` |
| 모델 파일 | `models/weights/*.onnx` | `models/engines/*.engine` |
| `decode.backend` | `cpu` | `nvdec` |

**빠진 키를 기본값으로 덮지 않는다.** 모델 경로가 없는데 조용히 넘어가면 감지가 0건인
채로 시스템이 "정상"으로 보인다(절대규칙 9). 없으면 `ConfigError` 로 죽인다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast, get_args

import yaml

from aegis_contracts.enums import HelmetState, ObjectClass

__all__ = [
    "ClassifyConfig",
    "ConfigError",
    "DecodeConfig",
    "DepthConfig",
    "DetectConfig",
    "EdgeConfig",
    "RuntimeConfig",
    "ServerConfig",
    "StreamConfig",
    "load_config",
]

#: 레포 루트. `edge/config.py` 기준 한 단계 위다. 모델 경로는 전부 이 기준의 상대경로다.
_REPO_ROOT: Final = Path(__file__).resolve().parent.parent

#: `runtime.backend` 별로 모델 경로를 어느 키에서 읽는가.
_MODEL_KEY: Final[Mapping[str, str]] = {"onnx": "onnx", "tensorrt": "engine"}


class ConfigError(ValueError):
    """설정이 잘못됐다. **기본값으로 덮지 않고 여기서 죽는다.**"""


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """추론 백엔드. 노트북은 `onnx`(CPU), 젯슨은 `tensorrt`."""

    backend: str
    providers: tuple[str, ...]
    intra_op_threads: int
    """0 이면 onnxruntime 기본값(코어 수)에 맡긴다."""


@dataclass(frozen=True, slots=True)
class StreamConfig:
    """카메라 한 대의 서브 스트림. 엣지는 서브만 받는다(메인은 서버 몫)."""

    cam_id: int
    rtsp_sub: str
    width: int
    height: int
    fps: int

    def __post_init__(self) -> None:
        # 16:9 가 아니면 정규화 좌표가 한쪽 축으로 눌려 대시보드 오버레이가 어긋난다
        # (API명세서 §1.2). 640×640 같은 정사각 설정을 여기서 막는다.
        if self.width * 9 != self.height * 16:
            msg = (
                f"cam{self.cam_id} 서브 스트림이 16:9 가 아니다: {self.width}×{self.height}"
                " — 메인(1920×1080)과 화면비가 같아야 정규화 좌표가 대응한다"
            )
            raise ConfigError(msg)


@dataclass(frozen=True, slots=True)
class DecodeConfig:
    backend: str
    """`nvdec`(젯슨 하드웨어) / `cpu`(노트북). CPU 디코딩은 2채널로 포화될 수 있다."""
    target_fps: float
    """목표 처리 fps. **실측값은 heartbeat 에 따로 싣는다** — 이 값을 보고하지 않는다."""


@dataclass(frozen=True, slots=True)
class DetectConfig:
    """1단계 감지 — seg 모델 하나. 클래스는 `person` · `vehicle` 2종 고정이다."""

    model_path: Path
    imgsz: tuple[int, int]
    """`(height, width)`. **정사각이 아니다** — 640×384 rect letterbox(기능명세서 §5)."""
    rect: bool
    conf: float
    iou: float
    class_map: Mapping[str, ObjectClass]
    """모델이 학습한 클래스명 → 계약 클래스.

    ★ **제로샷이 아니다.** 학습된 이름이 무엇이든(`truck` · `forklift` · `사람`) 여기서
    `person` / `vehicle` 두 개로 접는다. 계약에 없는 클래스로는 매핑할 수 없다
    (CLAUDE.md 절대규칙 11 · contracts 규칙).

    매핑에 없는 클래스는 **버린다.** 조용히 `person` 으로 떨어뜨리지 않는다.
    """


@dataclass(frozen=True, slots=True)
class ClassifyConfig:
    """2단계 안전모 분류. 사람 크롭을 받아 `on` / `off` 를 낸다(§6.3).

    크기·신뢰도 게이트 값(`cls_min_crop_px` · `cls_min_conf`)은 **여기 없다** —
    현장에서 화면으로 조정하는 값이라 서버 `policies` 소관이다.
    """

    model_path: Path
    input_size: int
    batch: bool
    class_map: Mapping[str, HelmetState]
    """모델 클래스명 → `on` / `off`. **`unknown` 은 없다**(판정 불가는 필드 생략)."""


@dataclass(frozen=True, slots=True)
class DepthConfig:
    """온디맨드 뎁스 검증(FN-DET-11). 없으면 `model_path` 가 `None` 이다.

    **없어도 나머지는 전부 돈다.** 뎁스는 근접 후보의 앞뒤 분리를 확인하는 보조
    수단이고, 모델이 없으면 `depth_verified` 가 `False` 로 남을 뿐이다. 다만 그
    사실이 로그에 드러나야 한다 — 조용히 "검증됨"으로 올리지 않는다.
    """

    model_path: Path | None
    input_size: int
    separation_max: float
    """두 영역의 깊이 중앙값 차이가 프레임 깊이 범위의 이 비율 이하면 **같은 평면**.

    상대 역깊이라 절대 단위가 없으므로 비율로 잰다. 모델과 화각에 딸린 값이라
    정책이 아니라 여기 있다.
    """
    variance_scale: float
    """깊이 분산을 0~1 근처로 옮기는 배율. 쓰러짐 보강(트리거 D)이 읽는다."""


@dataclass(frozen=True, slots=True)
class TrackConfig:
    """추적기 설정. 판정 임계가 아니라 **추적 품질** 파라미터라 여기 있다."""

    backend: str
    high_conf: float
    """이 이상이면 1단계 연결에 쓰고, 남으면 새 트랙을 시작한다."""
    low_conf: float
    """이 이상 `high_conf` 미만은 2단계 연결에만 쓴다 — 새 트랙을 만들지 않는다."""
    match_iou: float
    buffer_frames: int
    """이 프레임 수만큼 관측되지 않으면 `track_lost` 를 보낸다.

    **서버의 유예(15초)와 다른 값이다.** 이쪽은 「엣지가 트랙을 포기하는 시점」이고
    그쪽은 「포기 통지를 받은 뒤 이벤트를 종결하기까지」다(§2.3).
    """
    vehicle_moving_min_speed: float
    """이 속도(지면 단위/초) 이상이면 지게차가 이동 중이다(§2.1 `moving`).

    **단위는 캘리브레이션이 정한다.** 실측을 미터로 넣었으면 m/s, 보드 cm 로 넣었으면
    cm/s 다 — 호모그래피가 단위를 모르기 때문이다.
    """


@dataclass(frozen=True, slots=True)
class FootPointConfig:
    """접지점 신뢰도 산출 파라미터. API명세서 §6.1

    ★ **정책 키가 아니다.** 명세서 §4.5 의 정책 목록에 없으므로 여기 둔다. 카메라
    화각과 대상 크기에 딸린 값이고, 명세서를 고쳐야 한다고 판단되면 코드를 바꾸기
    전에 사람에게 보고한다(CLAUDE.md 절대규칙 8).
    """

    expected_band_pixels: float
    """접지 띠에 이 정도 점이 있으면 신뢰도 만점. 윤곽 점 수 기준이다."""
    max_spread_ratio: float
    """띠의 x 폭이 bbox 폭 대비 이 비율을 넘으면 그림자 혼입으로 보고 감점한다."""
    min_conf_for_depth: float
    """접지점 신뢰도가 이 값 미만이면 뎁스 트리거 C 가 걸린다(FN-DET-11)."""


@dataclass(frozen=True, slots=True)
class ServerConfig:
    ws_url: str
    rest_url: str
    heartbeat_interval_s: float


@dataclass(frozen=True, slots=True)
class EdgeConfig:
    runtime: RuntimeConfig
    streams: tuple[StreamConfig, ...]
    decode: DecodeConfig
    detect: DetectConfig
    classify: ClassifyConfig
    depth: DepthConfig
    track: TrackConfig
    footpoint: FootPointConfig
    server: ServerConfig


# --------------------------------------------------------------------------
# 로딩
# --------------------------------------------------------------------------


def load_config(path: Path | str | None = None) -> EdgeConfig:
    """`edge/config.yaml` 을 읽는다. 경로를 주지 않으면 레포의 것을 쓴다."""
    config_path = Path(path) if path is not None else _REPO_ROOT / "edge" / "config.yaml"
    if not config_path.is_file():
        msg = f"엣지 설정을 찾을 수 없다: {config_path}"
        raise ConfigError(msg)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"엣지 설정이 매핑이 아니다: {config_path}"
        raise ConfigError(msg)

    runtime = _runtime(_section(raw, "runtime"))
    return EdgeConfig(
        runtime=runtime,
        streams=_streams(raw),
        decode=_decode(_section(raw, "decode")),
        detect=_detect(_section(raw, "detect"), runtime.backend),
        classify=_classify(_section(raw, "classify"), runtime.backend),
        depth=_depth(_section(raw, "depth"), runtime.backend),
        track=_track(_section(raw, "track")),
        footpoint=_footpoint(_section(raw, "footpoint")),
        server=_server(_section(raw, "server")),
    )


def _section(raw: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        msg = f"설정에 `{name}` 절이 없다"
        raise ConfigError(msg)
    return value


def _require(section: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in section:
        msg = f"설정 `{where}.{key}` 가 없다"
        raise ConfigError(msg)
    return section[key]


def _runtime(section: Mapping[str, Any]) -> RuntimeConfig:
    backend = str(_require(section, "backend", "runtime"))
    if backend not in _MODEL_KEY:
        msg = f"runtime.backend 는 {sorted(_MODEL_KEY)} 중 하나여야 한다: {backend!r}"
        raise ConfigError(msg)
    providers = section.get("providers") or []
    return RuntimeConfig(
        backend=backend,
        providers=tuple(str(item) for item in providers),
        intra_op_threads=int(section.get("intra_op_threads", 0)),
    )


def _streams(raw: Mapping[str, Any]) -> tuple[StreamConfig, ...]:
    items = raw.get("streams")
    if not isinstance(items, list) or not items:
        msg = "설정에 `streams` 가 없거나 비어 있다 — 받을 카메라가 없다"
        raise ConfigError(msg)
    streams = tuple(
        StreamConfig(
            cam_id=int(_require(item, "cam_id", "streams[]")),
            rtsp_sub=str(_require(item, "rtsp_sub", "streams[]")),
            width=int(_require(item, "width", "streams[]")),
            height=int(_require(item, "height", "streams[]")),
            fps=int(_require(item, "fps", "streams[]")),
        )
        for item in items
    )
    seen = {stream.cam_id for stream in streams}
    if len(seen) != len(streams):
        msg = "streams 에 같은 cam_id 가 두 번 있다"
        raise ConfigError(msg)
    return streams


def _decode(section: Mapping[str, Any]) -> DecodeConfig:
    return DecodeConfig(
        backend=str(_require(section, "backend", "decode")),
        target_fps=float(_require(section, "target_fps", "decode")),
    )


def _model_path(section: Mapping[str, Any], backend: str, where: str) -> Path:
    """백엔드에 맞는 모델 파일. **없으면 죽는다.**

    `onnx` 백엔드인데 `engine` 만 적혀 있으면 그것을 쓰지 않는다 — 젯슨용 엔진은
    노트북에서 열리지 않으므로, 조용히 폴백하면 원인을 알 수 없는 실패가 된다.
    """
    key = _MODEL_KEY[backend]
    value = _require(section, key, where)
    path = Path(value)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    if not path.is_file():
        msg = f"`{where}.{key}` 모델 파일이 없다: {path}"
        raise ConfigError(msg)
    return path


def _detect(section: Mapping[str, Any], backend: str) -> DetectConfig:
    imgsz = _require(section, "imgsz", "detect")
    if not isinstance(imgsz, list) or len(imgsz) != 2:
        msg = f"detect.imgsz 는 [height, width] 두 값이어야 한다: {imgsz!r}"
        raise ConfigError(msg)
    height, width = int(imgsz[0]), int(imgsz[1])
    if height % 32 or width % 32:
        msg = f"detect.imgsz 는 stride 32 의 배수여야 한다: {height}×{width}"
        raise ConfigError(msg)
    return DetectConfig(
        model_path=_model_path(section, backend, "detect"),
        imgsz=(height, width),
        rect=bool(section.get("rect", True)),
        conf=float(_require(section, "conf", "detect")),
        iou=float(_require(section, "iou", "detect")),
        class_map=cast(
            Mapping[str, ObjectClass],
            _class_map(section, get_args(ObjectClass), "detect"),
        ),
    )


def _classify(section: Mapping[str, Any], backend: str) -> ClassifyConfig:
    return ClassifyConfig(
        model_path=_model_path(section, backend, "classify"),
        input_size=int(_require(section, "input_size", "classify")),
        batch=bool(section.get("batch", True)),
        class_map=cast(
            Mapping[str, HelmetState],
            _class_map(section, get_args(HelmetState), "classify"),
        ),
    )


def _depth(section: Mapping[str, Any], backend: str) -> DepthConfig:
    key = _MODEL_KEY[backend]
    common = {
        "input_size": int(_require(section, "input_size", "depth")),
        "separation_max": float(_require(section, "separation_max", "depth")),
        "variance_scale": float(_require(section, "variance_scale", "depth")),
    }
    # 뎁스만은 모델이 없어도 된다 — 나머지 기능이 전부 살아 있기 때문이다. 대신 키
    # 자체가 없는 것과 파일이 없는 것을 구분한다. 경로를 적어 놓고 파일이 없으면 오타다.
    if not section.get(key):
        return DepthConfig(model_path=None, **common)  # type: ignore[arg-type]
    return DepthConfig(model_path=_model_path(section, backend, "depth"), **common)  # type: ignore[arg-type]


def _track(section: Mapping[str, Any]) -> TrackConfig:
    return TrackConfig(
        backend=str(_require(section, "backend", "track")),
        high_conf=float(_require(section, "high_conf", "track")),
        low_conf=float(_require(section, "low_conf", "track")),
        match_iou=float(_require(section, "match_iou", "track")),
        buffer_frames=int(_require(section, "buffer_frames", "track")),
        vehicle_moving_min_speed=float(_require(section, "vehicle_moving_min_speed", "track")),
    )


def _footpoint(section: Mapping[str, Any]) -> FootPointConfig:
    return FootPointConfig(
        expected_band_pixels=float(_require(section, "expected_band_pixels", "footpoint")),
        max_spread_ratio=float(_require(section, "max_spread_ratio", "footpoint")),
        min_conf_for_depth=float(_require(section, "min_conf_for_depth", "footpoint")),
    )


def _server(section: Mapping[str, Any]) -> ServerConfig:
    return ServerConfig(
        ws_url=str(_require(section, "ws_url", "server")),
        rest_url=str(_require(section, "rest_url", "server")),
        heartbeat_interval_s=float(_require(section, "heartbeat_interval_s", "server")),
    )


def _class_map(
    section: Mapping[str, Any],
    allowed: tuple[str, ...],
    where: str,
) -> Mapping[str, str]:
    """`classes:` 표를 검증한다. 계약이 허용하는 값만 남는다.

    계약의 클래스 타입은 `Enum` 이 아니라 `Literal` 이므로(`aegis_contracts.enums`)
    허용 목록을 `get_args` 로 받아 문자열로 대조한다. 반환 타입을 좁히는 것은 호출부의
    `cast` 이고, **그 캐스트를 정당화하는 것이 이 함수의 검사다.**

    ★ **YAML 의 `on` · `off` 는 불리언이다.** 안전모 라벨을 따옴표 없이 적으면
    PyYAML 이 `True` · `False` 로 읽어 매핑이 통째로 어긋난다. 여기서 되돌려 주되,
    허용 목록에 없는 값은 죽인다 — `helmet` 은 `on` / `off` 두 개뿐이고 `unknown`
    같은 값을 만들어 낼 수 없다(contracts 규칙).
    """
    table = _require(section, "classes", where)
    if not isinstance(table, dict) or not table:
        msg = f"`{where}.classes` 가 비어 있다 — 모델 클래스명을 계약 클래스로 매핑해야 한다"
        raise ConfigError(msg)
    mapped: dict[str, str] = {}
    for name, target in table.items():
        text = "on" if target is True else "off" if target is False else str(target)
        if text not in allowed:
            msg = f"`{where}.classes.{name}` 값 {text!r} 은 허용되지 않는다 — {list(allowed)}"
            raise ConfigError(msg)
        mapped[str(name)] = text
    return mapped
