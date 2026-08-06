"""`edge/session.py` — 백엔드 분기와 클래스 이름 출처.

**하드웨어 없이 검증할 수 있는 것만 덮는다.** TensorRT 추론 자체는 젯슨 GPU 가
있어야 하므로 여기서 돌리지 않는다. 대신 그 앞뒤 — 어느 백엔드로 갈라지는가,
엔진의 클래스 이름을 사이드카에서 읽는가, 없을 때 조용히 인덱스로 때우지 않는가 —
는 전부 노트북에서 확인할 수 있고, 실제로 틀리기 쉬운 곳도 그쪽이다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from edge.config import RuntimeConfig
from edge.session import Session, _sidecar_names


def runtime(backend: str) -> RuntimeConfig:
    return RuntimeConfig(backend=backend, providers=("CPUExecutionProvider",), intra_op_threads=0)


def test_unknown_backend_is_rejected(tmp_path: Path) -> None:
    """모르는 백엔드를 조용히 onnx 로 떨어뜨리지 않는다.

    대소문자 오타 하나로 젯슨이 CPU 추론을 돌면 8fps 가 안 나오는 이유를 한참 찾게 된다.
    """
    model = tmp_path / "model.onnx"
    model.write_bytes(b"")
    with pytest.raises(ValueError, match="모르는 추론 백엔드"):
        Session(model, runtime("tensorRT"))


def test_tensorrt_backend_fails_loudly_without_tensorrt(tmp_path: Path) -> None:
    """`tensorrt` 가 없는 기계에서 엔진을 열려 하면 실패해야 한다.

    조용히 onnxruntime 으로 넘어가면 `.engine` 을 ONNX 로 읽으려다 엉뚱한 곳에서
    죽고, 원인이 백엔드 설정이라는 사실이 묻힌다.
    """
    engine = tmp_path / "model.engine"
    engine.write_bytes(b"")
    with pytest.raises((ImportError, RuntimeError)):
        Session(engine, runtime("tensorrt"))


def test_sidecar_names_are_read_next_to_the_engine(tmp_path: Path) -> None:
    engine = tmp_path / "detector.engine"
    engine.write_bytes(b"")
    (tmp_path / "detector.names.json").write_text(
        json.dumps({"0": "toy_person", "1": "toy_truck"}),
        encoding="utf-8",
    )
    assert _sidecar_names(engine) == repr({0: "toy_person", 1: "toy_truck"})


def test_missing_sidecar_is_none(tmp_path: Path) -> None:
    engine = tmp_path / "detector.engine"
    engine.write_bytes(b"")
    assert _sidecar_names(engine) is None


def test_broken_sidecar_is_logged_not_swallowed(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = tmp_path / "detector.engine"
    engine.write_bytes(b"")
    (tmp_path / "detector.names.json").write_text("{깨진 json", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="edge.session"):
        assert _sidecar_names(engine) is None
    assert "사이드카를 읽지 못했다" in caplog.text


def test_sidecar_must_be_a_mapping(tmp_path: Path) -> None:
    """리스트로 두면 인덱스가 곧 순서라는 가정이 숨는다 — 학습 순서가 바뀌면 뒤집힌다."""
    engine = tmp_path / "detector.engine"
    engine.write_bytes(b"")
    (tmp_path / "detector.names.json").write_text('["toy_person"]', encoding="utf-8")
    assert _sidecar_names(engine) is None


def test_onnx_and_engine_share_one_sidecar_name(tmp_path: Path) -> None:
    """확장자만 갈아 끼우므로 두 백엔드가 같은 규약을 공유한다."""
    (tmp_path / "m.names.json").write_text(json.dumps({"0": "person"}), encoding="utf-8")
    assert _sidecar_names(tmp_path / "m.onnx") == _sidecar_names(tmp_path / "m.engine")
