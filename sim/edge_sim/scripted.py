"""시나리오 파일(`sim/cases/*.yaml`)을 시각 순서대로 메시지로 바꾼다.

이 모듈은 **판단하지 않는다.** YAML에 적힌 것을 `aegis_contracts` 스키마로 검증해
그대로 내보낼 뿐이며, 위반 여부·확정·해소는 전부 서버가 정한다.

시나리오 형식:

    name: no_helmet_resolved
    cam_id: 1
    timeline:
      - at: 0.0            # 시작 기준 경과 초
        type: frame        # 나머지 키는 API명세서 §2 메시지 본문 그대로
        cam_id: 1
        objects: [...]

`ts`(`track_lost` 는 `last_ts`)는 적지 않는다. 시작 시각에 `at` 을 더해 주입한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import TypeAdapter

from aegis_contracts import EdgeMessage

__all__ = ["CASES_DIR", "ScheduledMessage", "load_case", "resolve_case_path"]

#: 시나리오 파일 디렉토리.
CASES_DIR = Path(__file__).resolve().parent.parent / "cases"

#: 메시지 유형별 타임스탬프 필드 이름. API명세서 §2.
_TS_FIELD: Final[dict[str, str]] = {
    "frame": "ts",
    "candidate": "ts",
    "track_lost": "last_ts",
    "heartbeat": "ts",
}

_ADAPTER: TypeAdapter[Any] = TypeAdapter(EdgeMessage)


@dataclass(frozen=True, slots=True)
class ScheduledMessage:
    """`at_s` 초 뒤에 보낼 메시지 하나."""

    at_s: float
    message: Any
    """`aegis_contracts.EdgeMessage` 판별 유니온의 인스턴스."""


def resolve_case_path(case: str) -> Path:
    """케이스 이름 또는 경로를 파일 경로로 바꾼다."""
    direct = Path(case)
    if direct.suffix and direct.exists():
        return direct
    candidate = CASES_DIR / f"{case}.yaml"
    if not candidate.exists():
        available = ", ".join(sorted(p.stem for p in CASES_DIR.glob("*.yaml"))) or "(없음)"
        msg = f"시나리오를 찾을 수 없다: {case}  —  사용 가능: {available}"
        raise FileNotFoundError(msg)
    return candidate


def load_case(case: str, start: datetime) -> list[ScheduledMessage]:
    """시나리오를 읽어 시각 순으로 정렬된 메시지 목록을 만든다.

    Args:
        case: 케이스 이름(`no_helmet_resolved`) 또는 yaml 경로.
        start: `at: 0.0` 에 대응하는 절대 시각. 호출자가 `Clock` 에서 얻어 넘긴다.
    """
    path = resolve_case_path(case)
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"시나리오 최상위는 매핑이어야 한다: {path}"
        raise ValueError(msg)

    timeline: Any = raw.get("timeline")
    if not isinstance(timeline, list):
        msg = f"시나리오에 timeline 리스트가 없다: {path}"
        raise ValueError(msg)

    scheduled: list[ScheduledMessage] = []
    for index, entry in enumerate(timeline):
        if not isinstance(entry, dict):
            msg = f"timeline[{index}] 는 매핑이어야 한다: {path}"
            raise ValueError(msg)

        payload: dict[str, Any] = dict(entry)
        at_s = float(payload.pop("at", 0.0))

        kind = payload.get("type")
        ts_field = _TS_FIELD.get(str(kind))
        if ts_field is None:
            msg = f"timeline[{index}] 의 type 이 올바르지 않다: {kind!r} ({path})"
            raise ValueError(msg)

        # 시각은 시나리오가 적지 않는다. 시작 시각 + 경과로 주입한다.
        payload[ts_field] = start + timedelta(seconds=at_s)

        scheduled.append(ScheduledMessage(at_s=at_s, message=_ADAPTER.validate_python(payload)))

    scheduled.sort(key=lambda item: item.at_s)
    return scheduled
