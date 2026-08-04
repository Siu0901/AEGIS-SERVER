"""학습된 `.pt` → `.onnx` 변환. **일회성이며 엣지 런타임은 이것을 쓰지 않는다.**

    uv sync --all-packages --group export        # torch·ultralytics 설치 (수 GB, 한 번만)
    uv run python -m scripts.export_onnx --inspect     # 클래스 이름만 확인
    uv run python -m scripts.export_onnx              # 변환

노트북(Intel CPU)에는 TensorRT 가 없으므로 ONNX 로 바꿔 `onnxruntime` 으로 돌린다.
젯슨에서는 이 스크립트를 쓰지 않는다 — 거기서는 `.pt` 에서 TensorRT 엔진을 직접
빌드하며, **엔진은 빌드한 GPU 에 종속되므로 노트북에서 만들 수 없다**(`models/README.md`).

★ **제로샷을 쓰지 않는다.** 감지 모델이 YOLOE 계열이라도 이미 `person` · `vehicle` 로
학습된 가중치이므로 `set_classes()` 를 부르지 않는다. 텍스트 프롬프트로 클래스를
정하는 경로는 이 프로젝트에 존재하지 않는다(CLAUDE.md 절대규칙 11).

★ **입력 형태를 `edge/config.yaml` 에서 읽는다.** 여기에 640×384 를 다시 적으면 설정과
어긋날 수 있고, 학습·추론 입력이 다르면 도메인 시프트가 생긴다. 형태의 원천은 하나다.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from typing import Any

import yaml

__all__ = ["export", "inspect_model", "main"]

#: 레포 루트. `scripts/export_onnx.py` 기준 한 단계 위다.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: ONNX opset. onnxruntime 1.20+ 가 읽고 TensorRT 도 무난히 받는 범위다.
OPSET = 17

# `uv run python -m ...` 로 돌리면 출력이 파이프가 되어 한글 Windows 는 cp949 로
# 떨어진다. '—' 하나에 UnicodeEncodeError 로 죽지 않게 한다(tasks.py 와 같은 처리).
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _config() -> dict[str, Any]:
    raw = yaml.safe_load((REPO_ROOT / "edge" / "config.yaml").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "edge/config.yaml 을 읽을 수 없다"
        raise SystemExit(msg)
    return raw


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _load(weights: Path) -> Any:
    """`ultralytics.YOLO` 로 연다. **여기서만 torch 가 필요하다.**"""
    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - 설치 안내 경로
        msg = "ultralytics 가 없다 — `uv sync --all-packages --group export` 로 설치해라"
        raise SystemExit(msg) from exc
    if not weights.is_file():
        msg = f"가중치를 찾을 수 없다: {weights}"
        raise SystemExit(msg)
    return YOLO(str(weights))


def inspect_model(weights: Path) -> dict[int, str]:
    """모델이 학습한 클래스 이름을 돌려준다.

    **이 이름을 `edge/config.yaml` 의 `classes:` 표에 적어야 한다.** 학습 때 쓴 라벨이
    무엇이든(`truck` · `forklift` · `head`) 계약 클래스는 `person` / `vehicle` 2종과
    `on` / `off` 뿐이므로, 매핑을 사람이 확인하고 적는다. 자동으로 추측하면 이름이
    비슷하다는 이유로 틀린 클래스에 붙을 수 있다.
    """
    model = _load(weights)
    names = model.names
    if isinstance(names, dict):
        return {int(index): str(name) for index, name in names.items()}
    return {index: str(name) for index, name in enumerate(names)}


def export(
    weights: Path,
    imgsz: int | list[int],
    destination: Path,
    *,
    dynamic: bool = False,
) -> Path:
    """ONNX 로 내보내고 목적지로 옮긴다. ultralytics 는 `.pt` 옆에 파일을 만든다.

    ★ **분류 모델은 `dynamic=True` 여야 한다.** 사람이 여러 명이면 크롭을 한 번에
    묶어 넣는데(FN-DET-05 `batch`), 배치 축이 1로 고정된 모델은 그 호출에서
    `Got: 4 Expected: 1` 로 죽는다. 감지 모델은 프레임 한 장씩이라 고정으로 둔다 —
    고정 형태가 CPU 에서 더 빠르다.
    """
    model = _load(weights)
    produced = Path(
        model.export(format="onnx", imgsz=imgsz, opset=OPSET, simplify=True, dynamic=dynamic)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if produced.resolve() != destination.resolve():
        produced.replace(destination)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="학습된 .pt 를 ONNX 로 변환한다")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="변환하지 않고 클래스 이름만 출력한다 (config.yaml 의 classes: 표를 적을 때)",
    )
    args = parser.parse_args(argv)

    config = _config()
    detect, classify = config["detect"], config["classify"]
    targets: list[tuple[str, Path, int | list[int], Path, bool]] = [
        (
            "detect",
            _resolve(detect["weights"]),
            [int(value) for value in detect["imgsz"]],
            _resolve(detect["onnx"]),
            False,
        ),
        (
            "classify",
            _resolve(classify["weights"]),
            int(classify["input_size"]),
            _resolve(classify["onnx"]),
            # 사람 여러 명의 크롭을 한 번에 넣으므로 배치 축이 열려 있어야 한다.
            True,
        ),
    ]

    for label, weights, imgsz, destination, dynamic in targets:
        names = inspect_model(weights)
        print(f"[{label}] {weights.name}")
        print(f"  클래스 {len(names)}종: {names}")
        if args.inspect:
            continue
        result = export(weights, imgsz, destination, dynamic=dynamic)
        size_mb = result.stat().st_size / 1_048_576
        shape = "동적 배치" if dynamic else "고정 배치"
        print(f"  → {result.relative_to(REPO_ROOT)}  ({size_mb:.1f} MB, imgsz={imgsz}, {shape})")

    if args.inspect:
        print("\n위 이름을 edge/config.yaml 의 `classes:` 표에 적어라.")
        print("계약 클래스는 person · vehicle 2종과 on · off 뿐이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
