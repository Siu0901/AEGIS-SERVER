"""`.onnx` → TensorRT `.engine` 빌드. **젯슨에서만 돈다.**

    uv run python -m scripts.build_engines --list      # 무엇을 빌드할지만 본다
    uv run python -m scripts.build_engines             # 세 모델 전부 FP16 으로

★ **엔진은 빌드한 GPU 와 TensorRT 버전에 종속된다.** 노트북에서 만든 엔진은 젯슨에서
열리지 않고, 그 반대도 마찬가지다. 그래서 `models/engines/` 는 git 에서 제외돼 있고
(`models/README.md`) 이 스크립트를 **젯슨 위에서** 돌려야 한다.

★ **클래스 이름 사이드카를 함께 쓴다.** `trtexec` 로 만든 엔진은 ONNX 의 `names`
메타데이터를 물고 가지 않는다. 그대로 두면 엣지가 클래스를 매핑하지 못해 감지가
0건이 되므로(`edge/session.py` `class_names()`), 원본 ONNX 에서 뽑아 엔진 옆에
`<이름>.names.json` 으로 남긴다.

★ **정밀도는 FP16 이다.** Orin Nano Super 에서 INT8 은 FP16 보다 약 0.8ms 빠르지만
mAP 가 0.480 → 0.449 로 떨어진다. 속도 여유가 있으므로 정확도를 택한다
(기능명세서 §3 「정밀도 방침」). 실측에서 부족할 때만 INT8 을 검토한다.

경로의 원천은 `edge/config.yaml` 이다 — 여기에 다시 적으면 설정과 어긋난다
(CLAUDE.md 절대규칙 6).
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

__all__ = ["build", "main", "sidecar_names", "targets"]

#: 레포 루트. `scripts/build_engines.py` 기준 한 단계 위다.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: `edge/config.yaml` 에서 모델을 들고 있는 절과, 그 절의 ONNX·엔진 키.
#: 뎁스는 `onnx` 가 주석 처리돼 있을 수 있다 — 없으면 건너뛰고 그 사실을 알린다.
_SECTIONS = ("detect", "classify", "depth")

#: 뎁스 모델(DepthAnythingV2)의 패치 크기. 입력이 이 배수여야 한다
#: (`edge/depth.py` 의 `_PATCH` 와 같은 값이며 그쪽이 원본이다).
_DEPTH_PATCH = 14

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _say(message: str = "") -> None:
    print(message, flush=True)


def _config() -> dict[str, Any]:
    raw = yaml.safe_load((REPO_ROOT / "edge" / "config.yaml").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "edge/config.yaml 을 읽을 수 없다"
        raise SystemExit(msg)
    return raw


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def input_shape(name: str, section: dict[str, Any]) -> tuple[int, int] | None:
    """이 절의 모델이 실제로 받는 (높이, 너비). 모르면 `None`.

    **엣지가 만드는 blob 과 같은 규칙으로 계산한다** — 다르게 계산하면 엔진과 런타임이
    어긋나고, 그 어긋남은 빌드 때가 아니라 **추론 중에** 터진다(실측: 뎁스 엔진이
    `[1,3,1,1]` 로 구워져 `[1,3,518,518]` 요청에서 죽었다).

    | 절 | 규칙 | 근거 |
    |---|---|---|
    | `detect` | `imgsz: [H, W]` 그대로 | `edge/letterbox.py` |
    | `classify` | `input_size` 정사각 | `edge/classify.py` `_crop` |
    | `depth` | `input_size` 를 14 의 배수로 내림, 정사각 | `edge/depth.py` `_PATCH` |
    """
    if name == "detect":
        imgsz = section.get("imgsz")
        if isinstance(imgsz, (list, tuple)) and len(imgsz) == 2:
            return int(imgsz[0]), int(imgsz[1])
        return None
    size = section.get("input_size")
    if not isinstance(size, int):
        return None
    if name == "depth":
        size -= size % _DEPTH_PATCH
    return (size, size) if size > 0 else None


def targets(config: dict[str, Any]) -> list[tuple[str, Path, Path]]:
    """(절 이름, ONNX 경로, 엔진 경로) 목록.

    **`onnx` 와 `engine` 이 둘 다 있는 절만 고른다.** 한쪽만 있으면 무엇을 무엇으로
    바꿔야 할지 정해지지 않으므로 조용히 넘기지 않고 이유를 적어 알린다.
    """
    found: list[tuple[str, Path, Path]] = []
    for name in _SECTIONS:
        section = config.get(name)
        if not isinstance(section, dict):
            _say(f"  · {name}: 절이 없다 — 건너뛴다")
            continue
        onnx, engine = section.get("onnx"), section.get("engine")
        if not onnx or not engine:
            missing = "onnx" if not onnx else "engine"
            _say(f"  · {name}: `{missing}:` 가 비어 있다 — 건너뛴다")
            continue
        found.append((name, _resolve(str(onnx)), _resolve(str(engine))))
    return found


def dynamic_input(onnx_path: Path) -> tuple[str, list[Any]] | None:
    """입력에 동적 축이 있으면 (이름, 차원목록). 전부 고정이면 `None`.

    ★ **이걸 안 보면 조용히 망가진 엔진이 나온다.** `trtexec` 는 동적 축에 형상을
      주지 않아도 실패하지 않는다 — 최소값으로 굳혀 버린다. 실측으로 뎁스 엔진이
      `[1,3,1,1]` 로 구워졌고, 추론 중에 `Static dimension mismatch` 로 죽었다.
      빌드는 성공했다고 나왔으므로 그 시점에는 아무도 몰랐다.
    """
    try:
        import onnx
    except ImportError as exc:
        # ★ **`None` 을 돌려주면 안 된다.** 그건 「고정 입력이다」라는 뜻이 되어
        #   형상 없이 굽게 되고, 망가진 엔진이 성공으로 보고된다. 판단할 수 없으면
        #   통과가 아니라 오류다(절대규칙 9).
        msg = (
            "`onnx` 가 없어 입력이 동적인지 판단할 수 없다.\n"
            "  형상을 모른 채 구우면 최소값으로 굳어 추론에서 죽는다.\n"
            "  `python -m pip install onnx` 후 다시 실행해라 "
            "(uv 환경이면 `uv pip install onnx`)."
        )
        raise SystemExit(msg) from exc
    model = onnx.load(str(onnx_path), load_external_data=False)
    first = model.graph.input[0]
    dims = [
        d.dim_value if d.HasField("dim_value") else (d.dim_param or "?")
        for d in first.type.tensor_type.shape.dim
    ]
    return (first.name, dims) if any(isinstance(d, str) for d in dims) else None


def sidecar_names(onnx_path: Path, engine_path: Path) -> bool:
    """ONNX 메타데이터의 `names` 를 엔진 옆 JSON 으로 뽑는다.

    `onnx` 패키지 하나만 쓴다 — onnxruntime 도 torch 도 필요 없다. 젯슨에 무거운 것을
    올리지 않기 위해서다.

    뎁스 모델처럼 클래스가 없는 모델은 `names` 가 없는 것이 정상이라 조용히 넘어간다.
    """
    try:
        import onnx
    except ImportError:
        _say("    ! `onnx` 가 없어 클래스 이름을 뽑지 못했다")
        _say("      `python -m pip install onnx` 후 다시 실행해라")
        _say("      (uv 환경이면 `uv pip install onnx`)")
        return False

    model = onnx.load(str(onnx_path), load_external_data=False)
    raw = next((prop.value for prop in model.metadata_props if prop.key == "names"), None)
    if not raw:
        _say("    · `names` 메타데이터가 없다 (클래스 없는 모델이면 정상)")
        return False

    import ast

    parsed = ast.literal_eval(raw)
    if not isinstance(parsed, dict):
        _say(f"    ! `names` 가 매핑이 아니다: {raw!r}")
        return False

    table = {str(int(index)): str(value) for index, value in parsed.items()}
    sidecar = engine_path.with_suffix(".names.json")
    sidecar.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    _say(f"    · 클래스 이름 {len(table)}개 → {sidecar.name}  {list(table.values())}")
    return True


def build(
    name: str,
    onnx_path: Path,
    engine_path: Path,
    *,
    workspace_mb: int,
    shape: tuple[int, int] | None = None,
) -> None:
    """`trtexec` 로 FP16 엔진을 만든다.

    ★ **동적 입력에는 형상을 반드시 준다.** 주지 않으면 `trtexec` 가 최소값으로 굳혀
      쓸 수 없는 엔진을 만들면서도 **성공으로 끝난다**. 그래서 여기서 막지 않으면
      실패가 추론 시점까지 미뤄진다(절대규칙 9).
    """
    if not onnx_path.is_file():
        msg = f"{name}: ONNX 가 없다 — {onnx_path}"
        raise SystemExit(msg)

    trtexec = shutil.which("trtexec") or "/usr/src/tensorrt/bin/trtexec"
    if not Path(trtexec).is_file() and shutil.which("trtexec") is None:
        msg = (
            "trtexec 를 찾지 못했다. JetPack 의 TensorRT 가 깔려 있는지 확인해라 "
            "(보통 /usr/src/tensorrt/bin/trtexec). 이 스크립트는 젯슨에서 돌린다."
        )
        raise SystemExit(msg)

    engine_path.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        trtexec,
        f"--onnx={onnx_path}",
        f"--saveEngine={engine_path}",
        "--fp16",
        f"--memPoolSize=workspace:{workspace_mb}M",
    ]

    dynamic = dynamic_input(onnx_path)
    if dynamic is not None:
        tensor, dims = dynamic
        if shape is None:
            msg = (
                f"{name}: ONNX 입력 {tensor!r} 이 동적인데({dims}) 형상을 정할 수 없다.\n"
                f"  `edge/config.yaml` 의 {name} 절에서 크기를 읽지 못했다 — "
                "detect 는 `imgsz`, classify·depth 는 `input_size` 다.\n"
                "  형상 없이 구우면 최소값으로 굳어 추론에서 죽는다."
            )
            raise SystemExit(msg)
        height, width = shape
        spec = f"{tensor}:1x3x{height}x{width}"
        argv += [f"--minShapes={spec}", f"--optShapes={spec}", f"--maxShapes={spec}"]
        _say(f"    · 동적 입력 {tensor} {dims} → 1x3x{height}x{width} 로 고정")
    _say(f"  $ {' '.join(argv)}")
    # **출력을 삼키지 않는다.** trtexec 는 지원하지 않는 연산자를 경고로만 알리고
    # 계속 진행하는 일이 있어서, 로그를 감추면 느린 엔진이 만들어진 이유를 놓친다.
    result = subprocess.run(argv, check=False)
    if result.returncode != 0:
        msg = f"{name}: trtexec 가 코드 {result.returncode} 로 실패했다"
        raise SystemExit(msg)

    size_mb = engine_path.stat().st_size / (1024 * 1024)
    _say(f"    · {engine_path.name}  {size_mb:,.1f} MB")
    sidecar_names(onnx_path, engine_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_engines",
        description="ONNX → TensorRT FP16 엔진 (젯슨 전용)",
    )
    parser.add_argument("--list", action="store_true", help="빌드 대상만 보고 끝낸다")
    parser.add_argument(
        "--workspace-mb",
        type=int,
        default=2048,
        help="trtexec 작업 메모리 상한 (기본 2048 · Orin Nano 8GB 기준)",
    )
    args = parser.parse_args(argv)

    _say("[engines] edge/config.yaml 에서 대상을 읽는다")
    config = _config()
    found = targets(config)
    if not found:
        msg = (
            "빌드할 대상이 없다 — config.yaml 의 detect·classify·depth 에 "
            "onnx 와 engine 을 둘 다 적어라"
        )
        raise SystemExit(msg)

    shapes = {name: input_shape(name, config.get(name) or {}) for name, _, _ in found}
    for name, onnx_path, engine_path in found:
        shape = shapes[name]
        size = f"  입력 1x3x{shape[0]}x{shape[1]}" if shape else "  입력 크기 미확인"
        _say(f"  · {name}: {onnx_path.name} → {engine_path.name}{size}")
    if args.list:
        return 0

    _say()
    for name, onnx_path, engine_path in found:
        _say(f"[engines] {name}")
        build(
            name,
            onnx_path,
            engine_path,
            workspace_mb=args.workspace_mb,
            shape=shapes[name],
        )
        _say()

    _say("=" * 34)
    _say(f"엔진 {len(found)}개 빌드 완료")
    _say("edge/config.yaml 의 runtime.backend 를 tensorrt 로 바꿔라")
    return 0


if __name__ == "__main__":
    sys.exit(main())
