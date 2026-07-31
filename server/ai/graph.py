"""LLM 심층 분석 — LangGraph 단계 흐름. FN-AI-05

기능명세서 §4.5 — 위반 유형, 구역, 주변 지게차와 거리, 지속시간, 반복 횟수, 자세,
이상 점수, 유사 사례, 규정 조항을 **하나의 구조화 컨텍스트**로 합성해 Gemini Flash 에
전달한다. LangGraph 가 단계별 흐름을 제어하며 메인 서버에서 실행된다.

```
수집 ──▶ 임베딩 ──▶ 유사 사례 ──▶ 분석문 생성
 │         │            │              │
 │         └ 실패해도    └ 벡터 없으면   └ 클라우드 없으면
 │           다음으로      건너뛴다        분석문만 비운다
 └ 규정 조항은 사전 테이블에서 (클라우드와 무관)
```

★ **어느 단계가 실패해도 앞 단계의 결과는 저장된다.** 임베딩만 되고 분석문이 비는
것과, 아무것도 없는 것은 다르다 — 전자는 검색이 되고 후자는 안 된다.

★ **규정 조항은 LLM 이 만들지 않는다**(FN-AI-06). 사전 테이블이 먼저 붙고, 그 결과가
프롬프트에 **입력으로** 들어간다. 모델에게 조항을 물어보면 그럴듯한 번호를 지어낸다.

★ **결과를 저장한다**(§6 `events.llm_analysis`). 조회할 때마다 다시 부르면 같은
이벤트가 볼 때마다 다른 설명을 갖게 되고, 「그때 무엇을 근거로 조치했는가」를 사후에
재현할 수 없다. 비용도 조회 수에 비례해 늘어난다.

★ **이 그래프는 안전 루프 밖에서 돈다**(FN-SYS-03). 확정 → 경고는 이 코드를 기다리지
않는다. `AiService` 가 배경 태스크로 띄우고, 실패는 `CloudGuard` 에서 멈춘다.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from aegis_contracts import EventDetail, RegulationRef, SimilarIncident
from server.ai.regulations import regulations_for

__all__ = ["AnalysisInput", "AnalysisResult", "build_analysis_graph", "compose_prompt"]

log = logging.getLogger("server.ai.graph")


@dataclass(slots=True)
class AnalysisInput:
    """분석 한 건의 재료. **읽기 전용 맥락이다** — 여기서 판정하지 않는다."""

    event: EventDetail
    keyframe: bytes | None = None
    """확정 시점 키프레임. 없으면 임베딩과 멀티모달 분석을 건너뛴다."""
    anomaly_score: float | None = None
    """그 시각 그 카메라의 이상 점수(§6.8). 없으면 프롬프트에서 뺀다."""


@dataclass(slots=True)
class AnalysisResult:
    """그래프가 만든 것. 저장할 값만 담는다."""

    regulation_refs: list[RegulationRef] = field(default_factory=list)
    embedding: list[float] | None = None
    similar_incidents: list[SimilarIncident] = field(default_factory=list)
    llm_analysis: str | None = None

    def as_changes(self) -> dict[str, Any]:
        """저장소 `update` 에 넘길 변경분. **비어 있는 칸은 넣지 않는다.**

        `None` 을 그대로 쓰면 앞선 분석 결과를 덮어 지운다 — 재실행이 개선이 아니라
        손실이 된다.
        """
        changes: dict[str, Any] = {
            "regulation_refs": [ref.model_dump(mode="json") for ref in self.regulation_refs]
        }
        if self.embedding is not None:
            changes["embedding"] = self.embedding
        if self.similar_incidents:
            changes["similar_incidents"] = [
                item.model_dump(mode="json") for item in self.similar_incidents
            ]
        if self.llm_analysis:
            changes["llm_analysis"] = self.llm_analysis
        return changes


class _State(TypedDict, total=False):
    """그래프가 들고 다니는 상태. 노드는 **덮어쓸 칸만** 돌려준다."""

    source: AnalysisInput
    result: AnalysisResult


#: 노드가 쓰는 협력자들. 그래프는 클라우드를 직접 모른다.
EmbedFn = Callable[[bytes], Awaitable[list[float] | None]]
MatchFn = Callable[[str, list[float] | None], Awaitable[list[SimilarIncident]]]
GenerateFn = Callable[[str, list[bytes]], Awaitable[str | None]]


def build_analysis_graph(
    *,
    embed: EmbedFn,
    match: MatchFn,
    generate: GenerateFn,
) -> Any:
    """FN-AI-05 그래프를 컴파일해 돌려준다.

    협력자를 주입받는 이유: 그래프 자체는 순서와 조건만 알고, 클라우드 호출·격리는
    바깥(`CloudGuard`)에 둔다. 그래야 테스트가 클라우드 없이 네 단계를 그대로 돌린다.
    """
    # 그래프 라이브러리는 여기서만 쓴다 — 순수 모듈들이 langgraph 를 모르게 둔다.
    from langgraph.graph import END, START, StateGraph

    async def collect(state: _State) -> _State:
        """① 규정 조항 — **사전 테이블이다.** 클라우드가 죽어도 이 칸은 채워진다."""
        source = state["source"]
        result = AnalysisResult(
            regulation_refs=regulations_for(source.event.violation_type),
        )
        return {"result": result}

    async def embed_node(state: _State) -> _State:
        """② 키프레임 임베딩(FN-AI-01). 실패하면 `None` 인 채로 다음 단계로 간다."""
        source, result = state["source"], state["result"]
        if source.keyframe is not None:
            result.embedding = await embed(source.keyframe)
        return {"result": result}

    async def similar(state: _State) -> _State:
        """③ 유사 사례(FN-AI-07). 벡터가 없으면 빈 목록이다 — 유사도를 지어내지 않는다."""
        source, result = state["source"], state["result"]
        result.similar_incidents = await match(source.event.violation_type.value, result.embedding)
        return {"result": result}

    async def analyze(state: _State) -> _State:
        """④ 분석문 생성. 앞 세 단계의 결과가 전부 프롬프트에 들어간다."""
        source, result = state["source"], state["result"]
        images = [source.keyframe] if source.keyframe is not None else []
        result.llm_analysis = await generate(compose_prompt(source, result), images)
        return {"result": result}

    graph = StateGraph(_State)
    graph.add_node("collect", collect)
    graph.add_node("embed", embed_node)
    graph.add_node("similar", similar)
    graph.add_node("analyze", analyze)
    graph.add_edge(START, "collect")
    graph.add_edge("collect", "embed")
    graph.add_edge("embed", "similar")
    graph.add_edge("similar", "analyze")
    graph.add_edge("analyze", END)
    return graph.compile()


_TYPE_LABEL = {
    "no_helmet": "안전모 미착용",
    "zone_intrusion": "금지구역 침입",
    "proximity": "지게차 근접",
    "fall": "쓰러짐",
}


def compose_prompt(source: AnalysisInput, result: AnalysisResult) -> str:
    """기능명세서 §4.5 — 아홉 가지를 **하나의 구조화 컨텍스트**로 합성한다.

    자유 서술이 아니라 표에 가깝게 적는 이유: 모델이 빠진 항목을 상상으로 메우지
    않게 하기 위해서다. 값이 없으면 그 줄을 아예 넣지 않는다 — 「없음」이라고 적으면
    그것이 관측된 사실처럼 읽힌다.

    ★ **조항은 이미 정해져 있다.** 프롬프트가 조항을 묻지 않고 **알려준다**(FN-AI-06).
    """
    event = source.event
    lines: list[str] = [
        f"위반 유형: {_TYPE_LABEL.get(event.violation_type.value, event.violation_type.value)}",
        f"카메라: {event.cam_id}번 · 추적번호 {event.track_id}",
    ]
    if event.zone_id:
        lines.append(f"구역: {event.zone_id}")
    if event.confirmed_at is not None:
        lines.append(f"확정 시각: {event.confirmed_at.isoformat()}")
    if event.resolution_sec is not None:
        lines.append(f"시정 소요: {event.resolution_sec}초")
    if event.repeat_count_7d:
        lines.append(
            f"최근 7일 같은 유형 반복: {event.repeat_count_7d}회 (같은 트랙 또는 같은 구역)"
        )
    if event.posture:
        lines.append(f"자세: {event.posture}")
    if event.height_ratio is not None:
        lines.append(f"높이 비율: {event.height_ratio}")
    if event.min_distance_m is not None:
        lines.append(f"최소 근접 거리: {event.min_distance_m} m (마스크 최근접 · 호모그래피)")
    for vehicle in event.nearby_snapshot:
        moving = "이동 중" if vehicle.moving else "정지"
        lines.append(
            f"주변 지게차 #{vehicle.track_id}: {vehicle.dist_m} m · {moving}"
            f"{' · 위험 반경 안' if vehicle.within_danger_radius else ''}"
        )
    if source.anomaly_score is not None:
        lines.append(f"이상 점수: {source.anomaly_score} (정상 풀 대비 k-NN 평균 코사인 거리)")
    for ref in result.regulation_refs:
        lines.append(f"관련 규정(확정된 사실): {ref.code} {ref.title}")
    for incident in result.similar_incidents:
        lines.append(f"유사 사례: {incident.title} (유사도 {incident.similarity})")

    context = "\n".join(f"- {line}" for line in lines)
    return (
        "너는 중소 제조현장의 안전관리자를 돕는 분석가다.\n"
        "아래는 CCTV 기반 안전 시스템이 확정한 위반 1건의 관측 사실이다.\n\n"
        f"{context}\n\n"
        "다음 규칙을 지켜 한국어로 3~5문장으로 서술해라.\n"
        "1. 위에 적힌 사실만 쓴다. 없는 수치·시간·인물을 만들지 않는다.\n"
        "2. 규정 조항 번호를 새로 만들지 마라. 위에 주어진 것만 인용한다.\n"
        "3. 무엇이 위험했는지, 왜 그런지, 현장에서 무엇을 바꿔야 하는지 순서로 쓴다.\n"
        "4. 작업자 개인을 특정하거나 책임을 묻는 표현을 쓰지 않는다. "
        "추적번호는 신원이 아니다.\n"
    )
