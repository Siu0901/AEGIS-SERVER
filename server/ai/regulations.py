"""규정 매핑 — **검색이 아니라 사전 테이블이다.** FN-AI-06

기능명세서 §4.5 · API명세서 §4.1 `regulation_refs`

★ **LLM 이 조항을 생성하지 않는다.** 위반 유형 → 조항은 `assets/seeds/regulations.yaml`
이 결정적으로 연결하고, LLM 에는 그 결과를 **입력으로** 넣는다.

조항 번호는 사실이고 생성 모델은 그럴듯한 번호를 만들어낸다. 관리자는 이 화면을 보고
시정 조치를 지시하는데, 존재하지 않는 조항이 근거로 붙으면 틀린 것보다 나쁘다 —
틀렸다는 사실조차 확인할 수 없기 때문이다.

**클라우드와 무관하다.** 인터넷이 끊겨도 이벤트 상세의 규정 칸은 채워진다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from aegis_contracts import RegulationRef
from aegis_contracts.enums import ViolationType

__all__ = ["REGULATIONS_PATH", "load_regulations", "regulations_for"]

#: 매핑표 위치. `assets/` 는 코드가 아니라 자료다(CLAUDE.md 디렉토리).
REGULATIONS_PATH = Path(__file__).resolve().parents[2] / "assets" / "seeds" / "regulations.yaml"


@lru_cache(maxsize=1)
def load_regulations(path: Path | None = None) -> dict[str, tuple[RegulationRef, ...]]:
    """매핑표를 읽어 {위반 유형: 조항들} 로 만든다.

    **파일이 없으면 조용히 비우지 않는다**(절대규칙 9). 규정 칸이 항상 비어 있는 것과
    「이 유형에 매핑된 조항이 없다」는 다른 사실이고, 전자는 배포 사고다.
    """
    source = path or REGULATIONS_PATH
    raw: Any = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("mappings"), dict):
        msg = f"규정 매핑표 형식이 잘못됐다: {source}"
        raise ValueError(msg)

    table: dict[str, tuple[RegulationRef, ...]] = {}
    for key, entries in raw["mappings"].items():
        if key not in set(ViolationType):
            msg = f"규정 매핑표에 없는 위반 유형이 있다: {key!r}"
            raise ValueError(msg)
        table[key] = tuple(
            RegulationRef(code=str(entry["code"]), title=str(entry["title"]))
            for entry in entries or []
        )

    missing = sorted(set(ViolationType) - set(table))
    if missing:
        # 유형이 늘어났는데 표가 따라오지 않으면 그 유형만 근거 없이 남는다.
        msg = f"규정 매핑이 없는 위반 유형이 있다: {', '.join(missing)}"
        raise ValueError(msg)
    return table


def regulations_for(violation_type: str | ViolationType) -> list[RegulationRef]:
    """그 위반 유형에 걸리는 조항들. 순서는 표에 적힌 그대로다(중요도 순)."""
    key = violation_type.value if isinstance(violation_type, ViolationType) else str(violation_type)
    return list(load_regulations().get(key, ()))
