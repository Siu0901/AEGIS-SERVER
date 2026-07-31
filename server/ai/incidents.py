"""유사 사고사례 매칭 — 확정 시 **1회 계산해 저장**한다. FN-AI-07

기능명세서 §4.5 · §6 `events.similar_incidents` · API명세서 §4.1

★ **조회할 때마다 다시 계산하지 않는다.** 시드가 바뀌면 지나간 이벤트의 근거가 소급해서
달라지고, 그러면 「그때 무엇을 근거로 조치했는가」를 사후에 설명할 수 없다.

★ **재지 않은 유사도를 지어내지 않는다.** §4.1 의 `similarity` 는 필수이고, 이 목록의
정의 자체가 「임베딩 유사도로 매칭된 사례」다. 그래서 클라우드를 부를 수 없으면 같은
유형의 사례를 유사도 없이 채우는 대신 **빈 목록**을 남긴다 — `0.0` 은 "전혀 닮지
않았다"는 주장이고, 유형만 같은 사례에 임의의 숫자를 붙이면 그 숫자가 곧 근거가 된다.
화면은 그 자리에 「클라우드 분석 전」이라고 적는다.

목록이 비는 것은 안전 기능과 무관하다(FN-SYS-03) — 감지·경고·시정 판정은 이 값을
읽지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from aegis_contracts import SimilarIncident
from aegis_contracts.enums import ViolationType
from server.ai.ports import Embedder
from server.ai.vectors import cosine_similarity

__all__ = ["INCIDENTS_PATH", "IncidentCase", "IncidentMatcher", "load_incidents"]

log = logging.getLogger("server.ai.incidents")

#: 사례 시드 위치.
INCIDENTS_PATH = Path(__file__).resolve().parents[2] / "assets" / "seeds" / "incidents.yaml"

#: 이벤트 하나에 붙일 사례 수. 넘치면 화면이 근거가 아니라 목록이 된다.
TOP_K = 3


@dataclass(frozen=True, slots=True)
class IncidentCase:
    """시드 한 건. `text` 가 임베딩 대상이다."""

    id: str
    title: str
    violation_type: str
    year: int
    text: str
    url: str | None = None


@lru_cache(maxsize=1)
def load_incidents(path: Path | None = None) -> tuple[IncidentCase, ...]:
    """사례 시드를 읽는다. 형식이 틀리면 조용히 비우지 않고 오류를 낸다."""
    source = path or INCIDENTS_PATH
    raw: Any = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("incidents"), list):
        msg = f"사고사례 시드 형식이 잘못됐다: {source}"
        raise ValueError(msg)
    cases = tuple(
        IncidentCase(
            id=str(entry["id"]),
            title=str(entry["title"]),
            violation_type=str(entry["violation_type"]),
            year=int(entry["year"]),
            text=" ".join(str(entry["text"]).split()),
            url=entry.get("url"),
        )
        for entry in raw["incidents"]
    )
    unknown = sorted({case.violation_type for case in cases} - set(ViolationType))
    if unknown:
        msg = f"사고사례 시드에 없는 위반 유형이 있다: {', '.join(unknown)}"
        raise ValueError(msg)
    return cases


class IncidentMatcher:
    """사례 벡터를 한 번 만들어 들고 있다가 이벤트마다 비교한다.

    시드가 10건 수준이라 전수 비교로 충분하다 — 인덱스를 두면 그 근사 오차가 곧
    "왜 이 사례가 붙었나"를 설명할 수 없게 만든다.
    """

    def __init__(self, embedder: Embedder | None = None, *, top_k: int = TOP_K) -> None:
        self._embedder = embedder
        self._top_k = top_k
        self._vectors: dict[str, list[float]] = {}

    async def warm(self) -> int:
        """사례 문장을 임베딩해 캐시한다. 실패하면 0을 돌려주고 폴백으로 돈다.

        기동 때 한 번 부른다. 사례 수만큼(약 8회) 호출이 나가지만 **이벤트마다가
        아니라 프로세스마다 한 번**이다.
        """
        if self._embedder is None:
            return 0
        made = 0
        for case in load_incidents():
            if case.id in self._vectors:
                continue
            try:
                self._vectors[case.id] = await self._embedder.embed_text(case.text)
                made += 1
            except Exception as exc:  # 클라우드 실패는 여기서 끝난다(FN-SYS-03)
                log.warning("사례 임베딩 실패 — 유형 매칭으로 대신한다: %s", exc)
                return made
        return made

    async def match(
        self,
        violation_type: str,
        embedding: list[float] | None,
    ) -> list[SimilarIncident]:
        """확정 이벤트 하나에 붙일 사례들.

        `embedding` 은 그 이벤트 키프레임의 벡터다. 그것이 없거나 사례 벡터가 없으면
        **빈 목록**이다 — 재지 않은 유사도를 지어내지 않는다.
        """
        del violation_type  # 유형은 시드가 들고 있고, 여기서 좁히면 교차 유형 사례를 놓친다
        if not embedding or not self._vectors:
            return []
        scored = [
            (cosine_similarity(embedding, vector), case)
            for case in load_incidents()
            if (vector := self._vectors.get(case.id)) is not None
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            SimilarIncident(title=case.title, source="KOSHA", similarity=round(score, 4))
            for score, case in scored[: self._top_k]
        ]
