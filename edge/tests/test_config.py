"""엣지 설정 로딩. **빠진 값을 기본값으로 덮지 않는지**가 핵심이다.

모델 경로가 없는데 조용히 넘어가면 감지가 0건인 채로 시스템이 "정상"으로 보인다
(CLAUDE.md 절대규칙 9).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from edge.config import ConfigError, load_config

from .conftest import LIVE_CONFIG, live_config_raw, requires_weights

Build = Callable[[dict[str, Any]], Path]


# --------------------------------------------------------------------------
# 규칙 — 가중치 없이도 검증한다
# --------------------------------------------------------------------------


def test_config_loads(make_config: Build) -> None:
    config = load_config(make_config(live_config_raw()))
    assert config.runtime.backend == "onnx"
    assert config.detect.model_path.is_file()
    assert config.classify.model_path.is_file()


def test_detect_input_is_rect_not_square(make_config: Build) -> None:
    """640×384 rect 다. 정사각으로 바꾸면 연산 픽셀이 약 1.67배가 된다(기능명세서 §5)."""
    config = load_config(make_config(live_config_raw()))
    assert config.detect.imgsz == (384, 640)
    assert config.detect.imgsz[0] != config.detect.imgsz[1]


def test_streams_are_16_9(make_config: Build) -> None:
    """서브가 메인(1920×1080)과 화면비가 같아야 정규화 좌표가 대응한다(§1.2)."""
    for stream in load_config(make_config(live_config_raw())).streams:
        assert stream.width * 9 == stream.height * 16


def test_classes_map_only_to_contract_values(make_config: Build) -> None:
    """계약 클래스는 `person` · `vehicle` 2종과 `on` · `off` 뿐이다(절대규칙 11)."""
    config = load_config(make_config(live_config_raw()))
    assert set(config.detect.class_map.values()) <= {"person", "vehicle"}
    assert set(config.classify.class_map.values()) <= {"on", "off"}


def test_helmet_labels_survive_yaml_booleans(make_config: Build) -> None:
    """★ YAML 에서 따옴표 없는 `on`/`off` 는 불리언이다.

    로더가 되돌려 주지 못하면 `{Helmet: True}` 가 되어 매핑이 통째로 어긋난다.
    """
    raw = live_config_raw()
    raw["classify"]["classes"] = {"Helmet": True, "No_Helmet": False}
    assert dict(load_config(make_config(raw)).classify.class_map) == {
        "Helmet": "on",
        "No_Helmet": "off",
    }


# --------------------------------------------------------------------------
# 거부 — 조용히 통과시키지 않는다
# --------------------------------------------------------------------------


def test_missing_model_file_is_rejected(make_config: Build, tmp_path: Path) -> None:
    """경로를 적어 놓고 파일이 없으면 오타다. **감지 0건으로 돌지 않는다.**"""
    raw = live_config_raw()
    path = make_config(raw)
    # 픽스처가 빈 파일을 만들어 준 뒤에 경로를 없는 것으로 바꾼다.
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(raw["detect"]["onnx"], str(tmp_path / "does_not_exist.onnx")),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="모델 파일이 없다"):
        load_config(path)


def test_engine_is_not_used_as_onnx_fallback(make_config: Build) -> None:
    """`onnx` 백엔드인데 `.onnx` 키가 없으면 **엔진으로 넘어가지 않고 죽는다.**

    젯슨용 엔진은 노트북에서 열리지 않으므로, 폴백하면 원인을 알 수 없는 실패가 된다.
    """
    raw = live_config_raw()
    del raw["detect"]["onnx"]
    with pytest.raises(ConfigError, match=re.escape("detect.onnx")):
        load_config(make_config(raw))


def test_square_sub_stream_is_rejected(make_config: Build) -> None:
    """640×640 같은 정사각 설정은 정규화 좌표를 눌러 오버레이를 어긋나게 한다."""
    raw = live_config_raw()
    raw["streams"][0]["height"] = 640
    with pytest.raises(ConfigError, match="16:9"):
        load_config(make_config(raw))


def test_non_stride32_imgsz_is_rejected(make_config: Build) -> None:
    raw = live_config_raw()
    raw["detect"]["imgsz"] = [380, 640]
    with pytest.raises(ConfigError, match="stride 32"):
        load_config(make_config(raw))


def test_unknown_helmet_class_is_rejected(make_config: Build) -> None:
    """`unknown` 은 존재하지 않는다 — 판정 불가는 **필드 생략**으로 표현한다(§6.3)."""
    raw = live_config_raw()
    raw["classify"]["classes"] = {"Helmet": "on", "No_Helmet": "unknown"}
    with pytest.raises(ConfigError, match="허용되지 않는다"):
        load_config(make_config(raw))


def test_unknown_object_class_is_rejected(make_config: Build) -> None:
    """`forklift` 같은 이름으로 매핑할 수 없다 — 계약은 2종 고정이다."""
    raw = live_config_raw()
    raw["detect"]["classes"] = {"toy_person": "person", "toy_truck": "forklift"}
    with pytest.raises(ConfigError, match="허용되지 않는다"):
        load_config(make_config(raw))


def test_missing_section_is_rejected(make_config: Build) -> None:
    raw = live_config_raw()
    del raw["footpoint"]
    with pytest.raises(ConfigError, match="footpoint"):
        load_config(make_config(raw))


def test_duplicate_cam_id_is_rejected(make_config: Build) -> None:
    raw = live_config_raw()
    raw["streams"] = [raw["streams"][0], dict(raw["streams"][0])]
    with pytest.raises(ConfigError, match="같은 cam_id"):
        load_config(make_config(raw))


def test_depth_may_be_absent(make_config: Build) -> None:
    """뎁스만은 없어도 나머지가 전부 돈다(FN-DET-11 은 보조 수단이다)."""
    raw = live_config_raw()
    del raw["depth"]["onnx"]
    assert load_config(make_config(raw)).depth.model_path is None


# --------------------------------------------------------------------------
# 레포의 실제 설정 — 가중치가 있을 때만
# --------------------------------------------------------------------------


@requires_weights
def test_repo_config_points_at_real_files() -> None:
    """가중치를 옮기거나 이름을 바꾸면 여기서 걸린다."""
    config = load_config(LIVE_CONFIG)
    assert config.detect.model_path.is_file()
    assert config.classify.model_path.is_file()
