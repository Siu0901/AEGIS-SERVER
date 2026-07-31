"""자연어 장면 검색 — **하이브리드**. FN-AI-02 · API명세서 §4.3

기능명세서 §4.5 — 구조화 가능한 조건(기간·카메라·유형)은 SQL 필터로 먼저 좁히고,
자유 문장 부분만 임베딩 유사도로 순위화한다.

★ **통계 질문에 벡터 검색을 쓰지 않는다.** 「지난주 1번 카메라 안전모 미착용」은
전부 구조화 조건이므로 SQL 하나로 답이 나온다. 그것을 임베딩에 넣으면
① 클라우드 호출이 붙고 ② 조건이 유사도에 밀려 무시되며 ③ 결과를 설명할 수 없다.

**질의에서 뽑아내는 것**

| 뽑히는 것 | 어디로 | 예 |
|---|---|---|
| 기간 | SQL `WHERE detected_at` | 「지난주」 · 「어제」 · 「오늘」 |
| 카메라 | SQL `WHERE cam_id` | 「1번 카메라」 · 「2번 캠」 |
| 위반 유형 | SQL `WHERE violation_type` | 「안전모」 · 「지게차 근처」 · 「쓰러」 |
| 나머지 문장 | 임베딩 랭킹 | 「사다리 옆에서 뭘 옮기는 장면」 |

**남은 문장이 비면 `mode = "sql"` 이다.** 조건을 다 뽑아내고 나면 랭킹할 것이
없으므로 클라우드를 부르지 않는다 — 인터넷 없이도 이 경로는 그대로 돈다.

파싱은 정규식이다. LLM 에게 "이 질의를 SQL 로 바꿔줘"라고 시키지 않는 이유: 그 결과가
비결정적이라 같은 질문에 다른 결과가 나오고, 무엇보다 **DB 에 나가는 조건을 생성 모델이
정하게 된다.** 뽑아내지 못한 표현은 자유 문장으로 남아 벡터 쪽이 받는다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from aegis_contracts import SceneSearchFilters
from aegis_contracts.enums import SearchMode, ViolationType
from aegis_vision.clock import Clock

__all__ = ["ParsedQuery", "parse_query"]

log = logging.getLogger("server.ai.search")

#: 위반 유형을 가리키는 말들. **시안의 건설현장 용어는 넣지 않는다**(부록 B) —
#: 「굴착기」로 검색되면 존재하지 않는 도메인이 있는 것처럼 보인다.
_TYPE_WORDS: tuple[tuple[ViolationType, tuple[str, ...]], ...] = (
    (ViolationType.NO_HELMET, ("안전모", "헬멧", "보호구", "no_helmet")),
    (ViolationType.ZONE_INTRUSION, ("금지구역", "출입", "침입", "구역 침입", "zone_intrusion")),
    (ViolationType.PROXIMITY, ("지게차", "근접", "차량", "proximity")),
    (ViolationType.FALL, ("쓰러", "넘어", "전도", "fall")),
)

#: 기간 표현 → (며칠 전부터, 며칠 전까지). `None` 이면 지금까지.
_PERIOD_WORDS: tuple[tuple[str, int, int | None], ...] = (
    ("오늘", 0, None),
    ("어제", 1, 1),
    ("이번 주", 7, None),
    ("이번주", 7, None),
    ("지난주", 14, 7),
    ("지난 주", 14, 7),
    ("이번 달", 30, None),
    ("이번달", 30, None),
    ("최근", 7, None),
)

_CAM_RE = re.compile(r"(\d+)\s*번?\s*(?:카메라|캠|cam)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    """질의 하나를 SQL 조건과 자유 문장으로 가른 결과."""

    from_: datetime | None
    to: datetime | None
    cam_id: int | None
    violation_type: ViolationType | None
    free_text: str
    """구조화 조건을 빼고 남은 부분. 비어 있으면 벡터 랭킹이 필요 없다."""

    @property
    def mode(self) -> SearchMode:
        """§4.3 `mode` — 서버가 질의를 분석해 자동 선택한다.

        | 남은 문장 | 구조화 조건 | mode |
        |---|---|---|
        | 없음 | 있음 | `sql` |
        | 있음 | 없음 | `vector` |
        | 있음 | 있음 | `hybrid` |
        """
        if not self.free_text:
            return "sql"
        return "hybrid" if self.has_filters else "vector"

    @property
    def has_filters(self) -> bool:
        return any(
            value is not None for value in (self.from_, self.to, self.cam_id, self.violation_type)
        )


def parse_query(
    query: str,
    filters: SceneSearchFilters | None,
    clock: Clock,
) -> ParsedQuery:
    """자연어 + 명시 필터 → 구조화 조건과 남은 문장.

    **명시 필터가 이긴다**(§4.3 `filters`). 화면에서 고른 기간·카메라를 문장 속 표현이
    덮으면, 사용자가 고른 것과 다른 결과가 나오면서 화면에는 고른 값이 그대로 남는다.
    """
    remaining = query
    now = clock.now().astimezone(UTC)

    from_: datetime | None = None
    to: datetime | None = None
    for word, days_back, days_until in _PERIOD_WORDS:
        if word in remaining:
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            from_ = midnight - timedelta(days=days_back)
            to = None if days_until is None else midnight - timedelta(days=days_until - 1)
            remaining = remaining.replace(word, " ")
            break

    cam_id: int | None = None
    match = _CAM_RE.search(remaining)
    if match:
        cam_id = int(match.group(1))
        remaining = remaining[: match.start()] + " " + remaining[match.end() :]

    violation_type: ViolationType | None = None
    for candidate, words in _TYPE_WORDS:
        hit = next((word for word in words if word in remaining), None)
        if hit is not None:
            violation_type = candidate
            remaining = remaining.replace(hit, " ")
            break

    if filters is not None:
        # 화면이 고른 값이 문장에서 뽑은 값을 덮는다.
        from_ = _at_start(filters.from_) or from_
        to = _at_end(filters.to) or to
        cam_id = filters.cam_id if filters.cam_id is not None else cam_id

    free_text = " ".join(remaining.split()).strip(" ·,.")
    # 조사·서술어만 남은 경우다. 이런 문장을 임베딩하면 아무 장면이나 비슷하게 나온다.
    if len(free_text) < 2:
        free_text = ""
    return ParsedQuery(
        from_=from_,
        to=to,
        cam_id=cam_id,
        violation_type=violation_type,
        free_text=free_text,
    )


def _at_start(value: date | None) -> datetime | None:
    """§4.3 `filters.from` 은 **날짜**다. 그 날 0시(UTC)부터다."""
    return None if value is None else datetime.combine(value, time.min, tzinfo=UTC)


def _at_end(value: date | None) -> datetime | None:
    """§4.3 `filters.to` 는 **그 날의 끝**까지다.

    `2026-08-12` 를 0시로 읽으면 12일 하루가 통째로 빠진다 — 사용자는 12일을 포함해
    달라고 적은 것이다. 날짜 필터에서 이 실수는 화면에 「그 날은 위반이 없었다」로
    보이고, 그 사실은 아무 데도 드러나지 않는다.
    """
    return None if value is None else datetime.combine(value, time.max, tzinfo=UTC)
