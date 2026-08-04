"""엣지 테스트 공용 픽스처.

**가중치는 git 에 없다**(`models/README.md` — 사람이 관리한다). 그래서 설정 로딩
검증은 빈 파일을 만들어 경로만 맞춘다 — 로더가 보는 것은 `is_file()` 뿐이다.

실제 추론이 필요한 테스트만 `requires_weights` 로 건너뛴다. **건너뛴 것은 통과가
아니다** — pytest 가 skipped 로 따로 세므로 「모델이 없어서 검증하지 못했다」는
사실이 결과에 남는다(CLAUDE.md 절대규칙 9).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LIVE_CONFIG = REPO_ROOT / "edge" / "config.yaml"
WEIGHTS = REPO_ROOT / "models" / "weights"

#: 실제 가중치가 있어야만 도는 테스트에 붙인다.
requires_weights = pytest.mark.skipif(
    not (WEIGHTS / "re_label_train_lego_50.onnx").is_file(),
    reason="models/weights 의 ONNX 가 없다 (git 제외 · 사람이 관리한다)",
)


def live_config_raw() -> dict[str, Any]:
    """레포의 `edge/config.yaml` 원본. 테스트가 이것을 복사해 변형한다."""
    loaded = yaml.safe_load(LIVE_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture
def make_config(tmp_path: Path) -> Callable[[dict[str, Any]], Path]:
    """설정 dict 를 파일로 쓰고, 모델 경로에 **빈 파일**을 만들어 준다.

    가중치의 내용이 아니라 **설정 규칙**을 검증하는 자리이므로 파일이 있기만 하면 된다.
    """

    def build(raw: dict[str, Any]) -> Path:
        stub = tmp_path / "weights"
        stub.mkdir(exist_ok=True)
        for section in ("detect", "classify", "depth"):
            for key in ("onnx", "engine", "weights"):
                value = raw.get(section, {}).get(key)
                if not value:
                    continue
                target = stub / Path(str(value)).name
                if not target.exists():
                    target.write_bytes(b"")
                raw[section][key] = str(target)
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        return path

    return build
