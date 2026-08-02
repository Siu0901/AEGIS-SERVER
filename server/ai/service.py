"""지능 기능 집행 — 조립과 수명주기. FN-AI-01 ~ 10

`server/ai` 의 다른 모듈은 순수하거나(규정·벡터·라우팅) 어댑터다(gemini). 여기가
그것들을 묶어 실제로 부르는 곳이며, **안전 루프 밖에서만** 돈다.

★ **확정 → 경고 경로는 이 파일을 기다리지 않는다**(FN-SYS-03). `EventService` 가 확정
전이를 집행할 때 `on_confirmed` 를 부르지만, 이 메서드가 하는 일은 배경 태스크 하나를
띄우는 것뿐이다. 분석이 20초 걸려도 방송은 이미 나갔다.

★ **실패는 여기서 멈춘다.** 모든 클라우드 호출이 `CloudGuard` 를 지나므로 예외가
바깥으로 새지 않고, 실패 사실은 `GET /system/status` 의 `cloud` 절과 §5.3 `system`
메시지로 드러난다.

---

**이상 탐지는 경고를 발동하지 않는다**(FN-AI-04). `anomaly` 메시지(§5.3)만 발행하고
`AlertService` 를 부르지 않는다 — 조명·날씨로도 점수가 오르므로 스피커가 울리면
현장이 경보를 무시하는 법을 배운다.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from aegis_contracts import (
    AnomalyMsg,
    BriefingResponse,
    ChatAttachment,
    ChatRequest,
    ChatResponse,
    ChatSource,
    ClipAttachment,
    EventDetail,
    EventRefAttachment,
    EventSummary,
    MetricsSummary,
    Policies,
    ReportDetail,
    ReportPeriod,
    SceneSearchFilters,
    SceneSearchItem,
    SceneSearchRequest,
    SceneSearchResponse,
    TableAttachment,
)
from aegis_contracts.enums import ChatRoute
from aegis_vision.clock import Clock
from server.ai.agent import run_agent
from server.ai.assistant import route_of
from server.ai.graph import AnalysisInput, AnalysisResult, build_analysis_graph
from server.ai.guard import CloudGuard
from server.ai.incidents import IncidentMatcher
from server.ai.ports import Embedder, Llm
from server.ai.search import ParsedQuery, parse_query
from server.ai.tools import ToolBox, specs_of
from server.ai.vectors import anomaly_score
from server.domain.aggregates import distribution

__all__ = ["AiService", "time_bucket"]

log = logging.getLogger("server.ai")

#: 정상 풀에서 비교할 최근 샘플 수. 시간대별로 나뉘므로 이 정도면 며칠치가 담긴다.
POOL_LIMIT = 200

#: 검색 결과 기본 개수. §4.3 요청이 `top_k` 를 주면 그것을 쓴다.
DEFAULT_TOP_K = 12
MAX_TOP_K = 50

#: 동시에 기억하는 세션 수. 넘으면 오래된 것부터 버린다 — 챗봇 이력은 놓쳐도 안전에
#: 영향이 없다(다시 물으면 된다). 경계 없는 dict 를 서버에 두지 않는다(§4.4).
HISTORY_SESSIONS = 50

#: 이상 키프레임 보존 기간(일). **이벤트 클립과 정책이 다르다**(§4.5) — 이쪽은
#: 진단용이라 30일이면 충분하고, 증거로 남기는 클립은 REC 의 7일 순환과 별개로 영구다.
ANOMALY_KEYFRAME_RETENTION_DAYS = 30


@dataclass(frozen=True, slots=True)
class ChatTurn:
    """대화 한 턴. **답변 전문이 아니라 요지만** 들고 있으면 될 것 같지만 그렇지 않다 —
    「각각 무슨 위반이야?」가 무엇을 가리키는지는 직전 답변의 내용에 있다."""

    question: str
    route: ChatRoute
    answer: str


def time_bucket(at: datetime, hours: int = 3) -> str:
    """정상 풀을 나누는 시간대 키(기능명세서 §4.5 「시간대별로 정상 풀을 분리 축적」).

    조명과 그림자가 시간대마다 달라서, 아침 풀과 야간 풀을 섞으면 정상 조명 변화가
    곧 이상으로 잡힌다. 잘게 나눌수록 조명이 균질해지지만 풀이 `anomaly_min_pool` 에
    도달하지 못하므로, 크기는 `anomaly_time_bucket_h`(기본 3) 정책값이다.
    """
    size = max(1, hours)
    hour = at.astimezone(UTC).hour
    return f"{hour // size * size:02d}"


class EventReader(Protocol):
    """`DbEventRepository` 중 이 서비스가 쓰는 부분."""

    async def get(self, event_id: str) -> EventDetail | None: ...

    async def update(self, event_id: str, changes: Mapping[str, Any]) -> None: ...

    async def search_events(
        self,
        *,
        vector: list[float] | None,
        from_: datetime | None,
        to: datetime | None,
        cam_id: int | None,
        violation_type: str | None,
        limit: int,
    ) -> list[tuple[EventSummary, float | None, str | None]]: ...

    async def aggregate_rows(self, from_: Any, to: Any) -> list[Any]:
        """유형별 내역의 원천(§4.2 `distribution` 과 같은 행). 분석 화면과 같은 코드를 쓴다."""
        ...


class AiStore(Protocol):
    """`DbAiRepository` 중 이 서비스가 쓰는 부분."""

    async def add_sample(
        self, cam_id: int, time_bucket: str, vector: list[float], at: datetime, model: str
    ) -> None: ...

    async def pool(
        self, cam_id: int, time_bucket: str, limit: int, model: str
    ) -> list[list[float]]: ...

    async def drop_other_models(self, model: str) -> int: ...

    async def create_anomaly(
        self,
        cam_id: int,
        score: float,
        at: datetime,
        *,
        keyframe_path: str | None = None,
        llm_note: str | None = None,
    ) -> int: ...

    async def set_anomaly_keyframe(self, anomaly_id: int, path: str) -> None: ...

    async def list_anomalies(
        self, from_: datetime | None, limit: int
    ) -> list[tuple[int, int, float, datetime, str | None, str | None]]: ...


class FrameSource(Protocol):
    """지금 이 순간의 프레임 한 장. REC 의 스냅샷 버퍼(§4.7)가 구현이다."""

    async def keyframe(self, cam_id: int, at: datetime) -> bytes: ...


class ReportStats(Protocol):
    """보고서가 쓰는 기간 집계. 구현은 `EventService.summary` 다.

    ★ **지표 계산을 여기서 다시 하지 않는다.** 같은 함수를 부르므로 보고서와 개요
    화면이 언제나 같은 시정률을 말한다.
    """

    async def __call__(
        self, *, from_: datetime | None = None, to: datetime | None = None
    ) -> MetricsSummary: ...


class AiService:
    """지능 기능 전체의 집행자."""

    def __init__(
        self,
        *,
        clock: Clock,
        guard: CloudGuard,
        events: EventReader | None = None,
        store: AiStore | None = None,
        frames: FrameSource | None = None,
        embedder: Embedder | None = None,
        llm: Llm | None = None,
        publish: Any = None,
        media_root: Path | None = None,
        cam_ids: Sequence[int] = (),
        report_stats: ReportStats | None = None,
        embedding_model: str = "",
    ) -> None:
        self._clock = clock
        self._guard = guard
        self._events = events
        self._store = store
        self._frames = frames
        self._embedder = embedder
        self._llm = llm
        self._publish = publish
        self._media_root = media_root
        self._cam_ids = tuple(cam_ids)
        self._report_stats = report_stats
        # 이 벡터가 **어느 공간에 사는지**를 행에 함께 적기 위한 이름(§6). 어댑터가
        # 없으면 빈 문자열이고, 그때는 임베딩 자체가 없으므로 풀에 쓸 일도 없다.
        self._embedding_model = embedding_model or getattr(embedder, "embed_model", "") or "unknown"
        self._pruned = False
        self._incidents = IncidentMatcher(embedder)
        self._policies = Policies()
        self._tasks: set[asyncio.Task[None]] = set()
        # 보고서는 메모리에 둔다. **예약 큐가 아니라 결과 캐시다** — 서버가 죽으면
        # 다시 요청하면 되고, 클립 예약(FN-REC-03)처럼 놓치면 증거가 사라지는 것이
        # 아니다. DB 테이블을 늘리는 대신 그 사실을 여기 적어 둔다.
        self._reports: dict[str, ReportDetail] = {}
        # §4.4 `session_id` 별 대화. **이것이 없으면 후속 질의가 성립하지 않는다** —
        # 「각각 무슨 위반이야?」가 무엇을 가리키는지 알 방법이 사라진다.
        self._history: dict[str, list[ChatTurn]] = {}
        self._graph = build_analysis_graph(
            embed=self._embed_keyframe,
            match=self._incidents.match,
            generate=self._generate,
        )

    def set_policies(self, policies: Policies) -> None:
        """이상 탐지 임계·주기와 대화 이력 길이를 DB 값으로 받는다(절대규칙 6).

        `anomaly_threshold` · `anomaly_knn_k` · `anomaly_min_pool` ·
        `anomaly_time_bucket_h` · `anomaly_sample_interval_min` · `assistant_history_turns`.
        전부 §4.5 정책 키이며 코드 상수로 두지 않는다 — 이상 탐지 임계는 조명·현장
        특성에 좌우되는 현장 조정 대상이다.
        """
        self._policies = policies

    @property
    def enabled(self) -> bool:
        """클라우드 어댑터가 붙어 있는가. 없어도 규정 매핑과 SQL 통계는 돈다."""
        return self._embedder is not None or self._llm is not None

    async def start(self) -> None:
        """사례 벡터를 미리 만든다. **이벤트마다가 아니라 프로세스마다 한 번**이다."""
        if self._embedder is None:
            log.info("클라우드 어댑터가 없다 — 규정 매핑과 SQL 통계만으로 동작한다")
            return
        made = await self._incidents.warm()
        log.info("사고사례 임베딩 %d건 준비", made)

    async def aclose(self) -> None:
        """배경 분석 태스크를 정리한다. 남기면 종료가 매달린다."""
        for task in list(self._tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # -- FN-AI-05 · 확정 시 심층 분석 ------------------------------------

    async def on_confirmed(self, event_id: str, cam_id: int, confirmed_at: datetime) -> None:
        """`EventService` 가 확정 전이에서 부른다. **기다리지 않는다.**

        시그니처가 `ClipScheduler` 와 같은 것은 우연이 아니다 — 둘 다 확정 순간에
        걸리는 후속 작업이고, 둘 다 안전 루프를 막지 않아야 한다.
        """
        del cam_id, confirmed_at  # 필요한 것은 저장된 이벤트에 전부 있다
        if self._events is None:
            return
        task = asyncio.create_task(self._analyze(event_id), name=f"ai-analyze:{event_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _analyze(self, event_id: str) -> None:
        """그래프를 돌리고 결과를 **저장한다**. 조회 때마다 다시 부르지 않기 위해서다."""
        if self._events is None:
            return
        try:
            event = await self._events.get(event_id)
        except Exception:
            log.exception("분석할 이벤트를 읽지 못했다 — %s", event_id)
            return
        if event is None:
            return

        # 키프레임은 클립 서비스가 확정 직후 배경에서 뽑는다. 아직 없을 수 있으므로
        # 잠깐 기다렸다가, 그래도 없으면 그림 없이 분석한다(임베딩·검색만 빠진다).
        keyframe = await self._read_keyframe(event)
        source = AnalysisInput(event=event, keyframe=keyframe)
        try:
            state = await self._graph.ainvoke({"source": source})
        except Exception:
            # 그래프 안의 클라우드 호출은 `CloudGuard` 가 이미 삼킨다. 여기 오는 것은
            # 조립·계약 오류이므로 조용히 넘기지 않는다(절대규칙 9).
            log.exception("분석 그래프가 실패했다 — %s", event_id)
            return

        result: AnalysisResult = state["result"]
        try:
            await self._events.update(event_id, result.as_changes())
        except Exception:
            log.exception("분석 결과를 저장하지 못했다 — %s", event_id)
            return
        log.info(
            "분석 저장 — %s (규정 %d · 사례 %d · 임베딩 %s · 분석문 %s)",
            event_id,
            len(result.regulation_refs),
            len(result.similar_incidents),
            "있음" if result.embedding else "없음",
            "있음" if result.llm_analysis else "없음",
        )

    async def _read_keyframe(self, event: EventDetail, *, wait_s: float = 3.0) -> bytes | None:
        """확정 이벤트의 키프레임 파일 한 장.

        URL 이 아니라 파일을 읽는다 — 같은 프로세스가 방금 쓴 것이고, HTTP 로 자기
        자신을 부르면 그 왕복이 실패 지점 하나를 더 만든다.
        """
        if self._media_root is None or self._events is None:
            return None
        deadline = wait_s
        while deadline > 0:
            urls = event.keyframe_urls
            if urls:
                path = self._media_root / Path(urls[0]).name
                if path.exists():
                    return await asyncio.to_thread(path.read_bytes)
                # `/media/keyframes/...` 를 그대로 붙인 경로도 본다.
                nested = self._media_root / "keyframes" / Path(urls[0]).name
                if nested.exists():
                    return await asyncio.to_thread(nested.read_bytes)
            await asyncio.sleep(0.5)
            deadline -= 0.5
            refreshed = await self._events.get(event.event_id)
            if refreshed is None:
                return None
            event = refreshed
        log.info("키프레임이 아직 없다 — 그림 없이 분석한다 (%s)", event.event_id)
        return None

    async def _embed_keyframe(self, image: bytes) -> list[float] | None:
        if self._embedder is None:
            return None
        return await self._guard.call("임베딩", self._embedder.embed_image(image))

    async def _generate(self, prompt: str, images: list[bytes]) -> str | None:
        if self._llm is None:
            return None
        return await self._guard.call("분석문 생성", self._llm.generate(prompt, images=images))

    # -- FN-AI-02 · 장면 검색 --------------------------------------------

    async def search(self, request: SceneSearchRequest) -> SceneSearchResponse:
        """§4.3 `POST /search/scenes` — 하이브리드.

        구조화 조건으로 먼저 좁히고 자유 문장만 벡터 랭킹한다. 남은 문장이 없으면
        **클라우드를 부르지 않는다** — 인터넷 없이도 이 경로가 돈다.
        """
        if self._events is None:
            return SceneSearchResponse(mode="sql", items=[])
        parsed = parse_query(request.query, request.filters, self._clock)
        limit = min(request.top_k or DEFAULT_TOP_K, MAX_TOP_K)

        vector: list[float] | None = None
        if parsed.free_text and self._embedder is not None:
            vector = await self._guard.call(
                "질의 임베딩", self._embedder.embed_text(parsed.free_text)
            )

        rows = await self._events.search_events(
            vector=vector,
            from_=parsed.from_,
            to=parsed.to,
            cam_id=parsed.cam_id,
            violation_type=(
                parsed.violation_type.value if parsed.violation_type is not None else None
            ),
            limit=limit,
        )
        # 벡터를 만들지 못했으면 실제로 돈 것은 SQL 이다. 요청한 경로가 아니라
        # **실제 경로**를 실어야 화면이 왜 순위가 시간순인지 설명할 수 있다.
        mode = parsed.mode if vector is not None else "sql"
        return SceneSearchResponse(
            mode=mode,
            items=[
                _search_item(summary, similarity, clip_url)
                for summary, similarity, clip_url in rows
            ],
        )

    # -- FN-AI-08 · 09 · 챗봇과 브리핑 -----------------------------------

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """§4.4 `POST /assistant/chat` — **도구를 등록하고 모델이 고르게 한다**. FN-AI-08

        ★ **경로를 키워드로 가르지 않는다.** 예전에는 질문에서 낱말을 찾아
        `sql`/`vector`/`vision` 셋 중 하나를 골랐는데, 그 구조로는 「이번 주 위반
        분석해주고 어떻게 해결할지」처럼 집계와 반복 순위를 **함께** 봐야 하는 질문에
        원리적으로 답할 수 없다 — 실제로 그 질문이 장면 검색으로 새서 「관련 장면
        5건을 찾았다」만 돌아왔다.

        ★ **`session_id` 를 실제로 쓴다.** 서버가 세션별 대화를 들고 있어야 「각각
        무슨 위반이야?」가 앞 질문에 이어진다(§4.4 대화 이력 규약).

        ★ **클라우드가 없으면 키워드 라우팅으로 떨어진다.** 도구를 고르는 주체가
        모델이므로 어댑터가 없으면 에이전트 자체가 성립하지 않는다. 그때는 예전
        경로가 그대로 돌아 SQL 통계는 계속 답한다.
        """
        history = self._history.get(request.session_id, [])
        if self._llm is not None:
            response = await self._answer_agent(request, history)
        else:
            response = await self._answer_keyword(request, history)
        self._remember(request.session_id, request.message, response)
        return response

    async def _answer_agent(self, request: ChatRequest, history: list[ChatTurn]) -> ChatResponse:
        """도구 호출 에이전트. 모델이 필요한 도구를 필요한 만큼 부른다.

        `route` 는 **실제로 무엇을 했는지**로 정한다(§4.4 `route`) — 화면이 그 값으로
        답변의 성격을 표시하므로, 도구를 하나도 안 불렀는데 「SQL 집계」라고 적으면
        근거가 없는 문장에 근거 딱지가 붙는다.
        """
        if self._llm is None:  # pragma: no cover - 호출자가 이미 가른다
            return await self._answer_keyword(request, history)
        box = ToolBox(
            clock=self._clock,
            summary=self._report_stats,
            breakdown=self._breakdown_for_window,
            repeat=self._repeat_rows,
            search=self.search,
            briefing=self.briefing,
            anomalies=self._anomaly_rows,
            events=self._events,
            cam_ids=self._cam_ids,
        )
        result = await self._guard.call(
            "어시스턴트",
            run_agent(
                self._llm,
                request.message,
                box.tools,
                specs_of(box.tools),
                history=_history_block(history),
            ),
        )
        if result is None:
            # 클라우드가 죽었다. 키워드 경로가 SQL 통계는 계속 답한다(§7 가용성).
            log.info("에이전트가 클라우드 실패로 끝났다 — 키워드 경로로 답한다")
            return await self._answer_keyword(request, history)

        sources = [ChatSource(type="tool", detail=name) for name in box.used]
        if result.truncated:
            # 상한에 걸린 사실을 숨기지 않는다 — 답이 짧은 이유가 화면에 드러나야 한다.
            sources.append(ChatSource(type="note", detail=f"도구 왕복 상한 {result.steps}회 도달"))
        return ChatResponse(
            route=_route_of_tools(box.used),
            answer=result.answer,
            attachments=box.attachments,
            sources=sources or [ChatSource(type="model", detail="도구 없이 답함")],
        )

    async def _answer_keyword(self, request: ChatRequest, history: list[ChatTurn]) -> ChatResponse:
        """키워드 라우팅 — **클라우드가 없을 때의 폴백**이다(§7 가용성).

        인터넷이 끊겨도 SQL 통계는 답해야 하는데, 도구를 고르는 주체가 모델이라
        에이전트는 그때 성립하지 않는다. 순수 함수인 이 경로가 그 자리를 지킨다.
        """
        routing = route_of(request.message, history[-1].route if history else None)
        if routing.route == "sql":
            return await self._answer_sql(request, history)
        if routing.route == "vision":
            return await self._answer_vision(routing.cam_id)
        return await self._answer_vector(request)

    async def _breakdown_for_window(self, start: datetime, end: datetime) -> list[tuple[str, int]]:
        """`violation_breakdown` 도구가 쓰는 유형별 집계. 분석 화면과 같은 코드다."""
        return await self._breakdown_for((start, end))

    async def _repeat_rows(self, days: int, limit: int) -> list[dict[str, Any]]:
        """`repeat_ranking` 도구가 쓰는 반복 순위. 저장소가 없으면 빈 목록.

        저장소는 `(subject, key, violation_type, count, last_at)` **튜플**을 돌려준다
        (§4.2). 구역 이름 붙이기는 라우터가 하므로 여기서는 키를 그대로 싣는다 —
        지어낸 이름을 모델에게 주면 그 이름이 답변에 그대로 인용된다.
        """
        rows = getattr(self._events, "repeat_ranking", None)
        if rows is None:
            return []
        since = today_since(self._clock, max(1, days))
        found = await rows(since, limit)
        return [
            {
                "대상": subject,
                "키": key,
                "위반": _TYPE_LABEL.get(violation_type, violation_type),
                "횟수": count,
                "마지막": last_at,
            }
            for subject, key, violation_type, count, last_at in found
        ]

    async def _anomaly_rows(self, days: int) -> list[dict[str, Any]]:
        """`recent_anomalies` 도구가 쓰는 이상 목록."""
        if self._store is None:
            return []
        since = today_since(self._clock, max(1, days))
        rows = await self._store.list_anomalies(since, 50)
        return [
            {"이상번호": aid, "카메라": cam, "점수": score, "시각": at, "무엇이 달랐나": note}
            for aid, cam, score, at, _path, note in rows
        ]

    def _remember(self, session_id: str, question: str, response: ChatResponse) -> None:
        """대화 한 턴을 기억한다. **경계가 있다** — 세션 수도 턴 수도 무한하지 않다.

        오래된 세션을 지우지 않으면 서버가 며칠 돌 때 이 dict 가 계속 자란다. 챗봇
        이력은 놓쳐도 안전에 영향이 없으므로(다시 물으면 된다) 상한을 두고 버린다.
        """
        turns = self._history.setdefault(session_id, [])
        turns.append(ChatTurn(question=question, route=response.route, answer=response.answer))
        del turns[: -max(1, self._policies.assistant_history_turns)]
        while len(self._history) > HISTORY_SESSIONS:
            self._history.pop(next(iter(self._history)))

    def forget(self, session_id: str) -> None:
        """세션 하나를 지운다. 화면의 「대화 지우기」가 부른다."""
        self._history.pop(session_id, None)

    def _window(
        self,
        parsed: ParsedQuery,
        history: list[ChatTurn],
    ) -> tuple[tuple[datetime | None, datetime | None], str]:
        """질문에서 뽑은 기간과 그 이름. 없으면 **오늘**이다.

        ★ 기간 표현이 없는 후속 질의(「각각 무슨 위반이야?」)는 **앞 질문의 기간을
        물려받아야** 한다. 그러지 않으면 「이번 주 몇 건」 다음 질문이 조용히 오늘치로
        바뀌어, 같은 대화 안에서 두 숫자가 어긋난다.
        """
        if parsed.from_ is not None or parsed.to is not None:
            return (parsed.from_, parsed.to), _window_label(parsed.from_, parsed.to)
        for turn in reversed(history):
            previous = parse_query(turn.question, None, self._clock)
            if previous.from_ is not None or previous.to is not None:
                return (
                    (previous.from_, previous.to),
                    _window_label(previous.from_, previous.to),
                )
        return (None, None), "오늘"

    async def _summary_for(self, window: tuple[datetime | None, datetime | None]) -> MetricsSummary:
        """그 구간의 집계. **`GET /metrics/summary` 와 같은 함수**를 부른다."""
        if self._report_stats is None:
            msg = "지표 집계가 연결되지 않았다"
            raise RuntimeError(msg)
        return await self._report_stats(from_=window[0], to=window[1])

    async def _breakdown_for(
        self, window: tuple[datetime | None, datetime | None]
    ) -> list[tuple[str, int]]:
        """유형별 (이름, 건수). 요약에는 이 축이 없어서 따로 센다.

        집계는 `server/domain/aggregates.distribution` 이 한다 — 분석 화면과 **같은
        코드**다. 여기서 다시 세면 두 화면이 다른 분포를 말하게 된다.
        """
        rows = getattr(self._events, "aggregate_rows", None)
        if rows is None:
            return []
        try:
            buckets = distribution(await rows(window[0], window[1]), by="violation_type")
        except Exception:
            log.warning("유형별 내역을 세지 못했다 — 요약만으로 답한다")
            return []
        return [(bucket.label, bucket.count) for bucket in buckets]

    async def _answer_sql(self, request: ChatRequest, history: list[ChatTurn]) -> ChatResponse:
        """통계 답변. **숫자는 SQL 이 만들고 LLM 은 문장만 만든다.**

        표(`kind = "table"`)를 함께 실어 사람이 문장과 원본을 대조할 수 있게 한다 —
        문장만 주면 그 숫자가 어디서 왔는지 확인할 방법이 없다.

        ★ **질문의 기간과 유형별 내역을 함께 낸다.** 요약만으로는 「각각 무슨
        위반이야?」에 답할 수 없다 — `total_violations` 에는 유형이 없다.

        클라우드가 없으면 서버가 조립한 문장을 그대로 쓴다 — §7 가용성이 「인터넷 단절
        시 SQL 통계 정상 동작」을 요구한다.
        """
        # ① 기간을 질문에서 뽑는다. 검색과 **같은 파서**를 쓴다 — 「지난주」의 뜻이
        #    두 화면에서 달라지면 안 된다.
        parsed = parse_query(request.message, None, self._clock)
        window, label = self._window(parsed, history)
        summary = await self._summary_for(window)
        breakdown = await self._breakdown_for(window)
        sentence = _summary_sentence(summary, label)
        if breakdown:
            sentence += " 유형별 — " + " · ".join(f"{name} {count}건" for name, count in breakdown)
        table = TableAttachment(
            kind="table",
            columns=["항목", "값"],
            # ★ 셀은 `string` / `number` / `null` 만이다(§4.4). 비율의 `null` 을
            #   문자열 "–" 로 바꾸지 않는다 — 화면이 그 판단을 해야 한다.
            #
            # ★ **단위를 항목 이름에 적는다.** 셀에 0~1 을 그대로 실으면 화면이 그 열이
            #   비율인지 건수인지 알 수 없어 `1.0` 을 「1건」처럼 그린다(실제로 그랬다).
            #   백분율로 바꿔 실으면 `null` 은 그대로 `null` 이면서 숫자가 자기 단위를
            #   설명한다 — 화면의 추측이 필요 없어진다.
            rows=[
                ["방송 후 시정률 (%)", _percent_value(summary.correction_rate)],
                ["판정 불가율 (%)", _percent_value(summary.undetermined_rate)],
                ["전체", summary.total_violations],
                ["시정", summary.resolved],
                ["늦은 시정", summary.resolved_late],
                ["미시정", summary.unresolved],
                ["판정 불가", summary.undetermined],
                ["방송 없음(일시중지)", summary.suppressed],
                ["쓰러짐", summary.fall_events],
                ["평균 시정 시간(초)", summary.avg_resolution_sec],
            ],
            # 내부 라벨(`custom`)이 아니라 사람이 읽는 기간을 쓴다.
            label=f"{label} 집계",
        )
        answer = sentence
        if self._llm is not None:
            written = await self._guard.call(
                "통계 문장",
                self._llm.generate(
                    "너는 안전 관제 시스템의 통계 응답을 다듬는다.\n"
                    "아래 「집계」는 SQL 이 낸 사실이다.\n\n"
                    f"{_history_block(history)}"
                    f"이번 질문: {request.message}\n"
                    f"집계({label}): {sentence}\n\n"
                    "규칙\n"
                    "1. 숫자를 바꾸거나 새로 만들지 마라. 집계에 없는 것은 답하지 마라.\n"
                    "2. 시정률을 말할 때는 판정 불가율을 반드시 함께 적는다.\n"
                    "3. **어느 기간의 숫자인지 밝힌다.**\n"
                    "4. 앞 대화가 있으면 그것에 이어서 답한다 — 같은 말을 반복하지 말고\n"
                    "   이번 질문이 묻는 것만 답해라.\n"
                    "5. 2~4문장의 한국어로 쓴다.\n"
                ),
            )
            if written:
                answer = written
        return ChatResponse(
            route="sql",
            answer=answer,
            attachments=[table],
            sources=[ChatSource(type="query", detail="events 집계 (GET /metrics/summary 와 동일)")],
        )

    async def _answer_vector(self, request: ChatRequest) -> ChatResponse:
        """장면 검색 답변. 결과는 **첨부**로 나간다(§4.4 `attachments[]`)."""
        found = await self.search(
            SceneSearchRequest(query=request.message, top_k=5, filters=SceneSearchFilters())
        )
        attachments: list[ChatAttachment] = []
        for item in found.items:
            # 클립 첨부는 재생과 썸네일이 **둘 다** 있어야 성립한다(§4.4). 하나라도
            # 없으면 상세로 가는 링크를 준다 — 빈손으로 돌려보내지 않는다.
            if item.clip_url and item.thumbnail_url:
                attachments.append(
                    ClipAttachment(
                        kind="clip",
                        event_id=item.event_id,
                        clip_url=item.clip_url,
                        thumbnail_url=item.thumbnail_url,
                        label=item.title,
                    )
                )
            else:
                attachments.append(
                    EventRefAttachment(kind="event_ref", event_id=item.event_id, label=item.title)
                )
        answer = (
            f"관련 장면 {len(found.items)}건을 찾았다."
            if found.items
            else "조건에 맞는 장면을 찾지 못했다."
        )
        return ChatResponse(
            route="vector",
            answer=answer,
            attachments=attachments,
            sources=[ChatSource(type="search", detail=f"mode={found.mode}")],
        )

    async def _answer_vision(self, cam_id: int | None) -> ChatResponse:
        """현재 상황 브리핑. 지금 프레임을 캡처해 멀티모달로 묻는다(FN-AI-09)."""
        summary = await self.briefing([cam_id] if cam_id else list(self._cam_ids))
        return ChatResponse(
            route="vision",
            answer=summary.summary,
            attachments=[],
            sources=[ChatSource(type="frame", detail=f"captured_at={summary.captured_at}")],
        )

    async def briefing(self, cam_ids: Sequence[int]) -> BriefingResponse:
        """§4.4 `POST /assistant/briefing` — 지금 화면을 보고 한 문단.

        **클라우드가 없으면 프레임 유무만 사실대로 적는다.** 「이상 없음」이라고 쓰면
        보지 않고 판단한 것이 되고, 그건 이 화면이 하려는 일과 정반대다.
        """
        at = self._clock.now()
        targets = list(cam_ids) or list(self._cam_ids)
        frames: list[tuple[int, bytes]] = []
        for cam_id in targets:
            image = await self._capture(cam_id, at)
            if image is not None:
                frames.append((cam_id, image))

        if not frames:
            return BriefingResponse(
                summary="현재 프레임을 가져오지 못해 현장 상황을 확인할 수 없다. "
                "녹화 컴포넌트(REC) 상태를 확인해라.",
                captured_at=at,
            )
        if self._llm is None:
            seen = ", ".join(f"{cam_id}번" for cam_id, _ in frames)
            return BriefingResponse(
                summary=f"카메라 {seen} 프레임을 확보했으나 클라우드 분석이 꺼져 있어 "
                "장면 설명을 만들지 못했다. 감지·경고·시정 판정은 정상 동작 중이다.",
                captured_at=at,
            )

        prompt = (
            "너는 제조현장 안전관제 화면을 보는 관리자다. 아래 CCTV 프레임"
            f"({', '.join(f'{cam_id}번 카메라' for cam_id, _ in frames)})을 보고 "
            "지금 상황을 2~3문장의 한국어로 요약해라.\n"
            "\n"
            "★ 규칙 (어기면 이 보고는 쓸모가 없다)\n"
            "1. **화면에 실제로 보이는 것만** 쓴다. 제조현장이라는 맥락에서 있을 법한\n"
            "   것을 채워 넣지 마라 — 사람이 안 보이면 사람을 쓰지 않는다.\n"
            "2. 화면이 **컬러바·테스트 패턴·정지 화면·검은 화면**이면 그 사실을 그대로\n"
            "   적고 끝낸다. 현장 장면인 척 묘사하지 마라.\n"
            "3. 사람·지게차가 보이면 위치와 눈에 띄는 위험 요인을 우선 적는다.\n"
            "4. 작업자 개인을 특정하지 않는다.\n"
        )
        written = await self._guard.call(
            "현장 브리핑", self._llm.generate(prompt, images=[image for _, image in frames])
        )
        return BriefingResponse(
            summary=written
            or "클라우드 분석에 실패해 장면 설명을 만들지 못했다. 안전 기능은 정상 동작 중이다.",
            captured_at=at,
        )

    # -- FN-AI-10 · 주간 보고서 ------------------------------------------

    async def start_weekly_report(self, from_: datetime, to: datetime) -> str:
        """§4.4 `POST /reports/weekly` — 생성을 **예약**하고 ID 를 즉시 돌려준다.

        동기로 만들면 요청이 LLM 왕복만큼 매달리고, 그동안 브라우저는 무엇이 되고
        있는지 알 수 없다. 진행 상태는 `GET /reports/{id}` 로 본다.
        """
        report_id = f"RP-{from_.strftime('%Y%m%d')}-{len(self._reports) + 1:02d}"
        self._reports[report_id] = ReportDetail(
            report_id=report_id,
            # §4.4 — `pending` 이다. 「생성 중」을 뜻하는 이름이 계약에 하나뿐이어야
            # 화면이 상태를 문자열로 짐작하지 않는다.
            status="pending",
            period=ReportPeriod.model_validate({"from": from_.date(), "to": to.date()}),
            created_at=self._clock.now(),
        )
        task = asyncio.create_task(
            self._write_report(report_id, from_, to), name=f"ai-report:{report_id}"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return report_id

    def report(self, report_id: str) -> ReportDetail | None:
        """예약된 보고서의 현재 상태(§4.4). 없으면 `None`."""
        return self._reports.get(report_id)

    async def _write_report(self, report_id: str, from_: datetime, to: datetime) -> None:
        """기간 집계 + 반복 순위를 읽어 보고서 본문을 만든다.

        ★ **숫자는 SQL 이 만든다.** LLM 은 그 숫자를 문장으로 옮길 뿐이고, 집계 원문이
        `stats` 로 함께 남아 사람이 대조할 수 있다. 클라우드가 없으면 집계만으로 된
        보고서가 나간다 — 비어 있는 것보다 낫다.
        """
        report = self._reports[report_id]
        period = f"{report.period.from_.isoformat()} ~ {report.period.to.isoformat()}"
        stats = self._report_stats
        summary: MetricsSummary | None = None
        if stats is not None:
            try:
                summary = await stats(from_=from_, to=to)
            except Exception:
                log.exception("보고서 집계를 읽지 못했다 — %s", report_id)
        if summary is None:
            report.status = "failed"
            report.error = "집계를 읽지 못해 보고서를 만들지 못했다."
            return
        report.stats = summary
        # 보고서는 자기 기간을 알고 있다 — 내부 라벨(`custom`)이 아니라 날짜를 쓴다.
        sentence = _summary_sentence(summary, period)
        body = sentence
        if self._llm is not None:
            written = await self._guard.call(
                "주간 보고서",
                self._llm.generate(
                    "너는 제조현장 안전관리자를 위한 주간 보고서를 쓴다.\n"
                    f"기간: {period}\n"
                    f"집계(SQL): {sentence}\n\n"
                    "아래 규칙으로 한국어 보고서를 써라.\n"
                    "1. 위 숫자만 쓴다. 새 수치를 만들지 않는다.\n"
                    "2. 시정률을 말할 때 판정 불가율을 반드시 병기한다.\n"
                    "3. 「요약 / 눈에 띄는 점 / 다음 주 조치」 세 단락으로 쓴다.\n"
                    "4. 작업자 개인을 특정하지 않는다.\n",
                ),
            )
            if written:
                body = written
        report.body = body
        report.status = "ready"
        log.info("주간 보고서 완료 — %s", report_id)

    async def _capture(self, cam_id: int, at: datetime) -> bytes | None:
        """REC 스냅샷 버퍼에서 지금 프레임 한 장(§4.7).

        **엣지 추론 예산과 무관하다**(기능명세서 §4.5) — 서버가 자체 보유한 1080p
        스트림에서 나온 것이다.
        """
        if self._frames is None:
            return None
        try:
            return await self._frames.keyframe(cam_id, at)
        except Exception as exc:
            log.info("cam%d 프레임을 가져오지 못했다: %s", cam_id, exc)
            return None

    # -- FN-AI-04 · 이상 탐지 --------------------------------------------

    async def sample_once(self) -> list[int]:
        """정상 풀 한 주기. 새로 만든 이상 플래그 ID들을 돌려준다.

        ★ **경고 방송을 발동하지 않는다.** `AlertService` 를 부르지 않고 §5.3 `anomaly`
        만 발행한다 — 조명·날씨로도 점수가 오르므로, 스피커가 울리면 현장이 경보를
        무시하는 법을 배운다.
        """
        if self._store is None or self._embedder is None:
            return []
        policies = self._policies
        at = self._clock.now()
        bucket = time_bucket(at, policies.anomaly_time_bucket_h)
        model = self._embedding_model
        made: list[int] = []
        for cam_id in self._cam_ids:
            image = await self._capture(cam_id, at)
            if image is None:
                continue
            vector = await self._guard.call("정상 풀 임베딩", self._embedder.embed_image(image))
            if vector is None:
                # 클라우드가 죽었다. 다음 주기에 다시 시도한다 — 안전 기능과 무관하다.
                return made
            # ★ **같은 모델의 벡터끼리만 비교한다**(§6 `normal_pool.embedding_model`).
            #   다른 공간의 벡터와 거리를 재면 그 값은 「평소와 다르다」가 아니라
            #   「비교할 수 없다」인데, 숫자는 그 둘을 구분하지 않는다.
            pool = await self._store.pool(cam_id, bucket, POOL_LIMIT, model)
            score = anomaly_score(vector, pool, k=policies.anomaly_knn_k)
            # 샘플은 **판정 여부와 무관하게** 쌓는다. 이상이었던 프레임을 빼면 풀이
            # 점점 좁아져 정상의 정의가 스스로 조여든다.
            await self._store.add_sample(cam_id, bucket, vector, at, model)
            if len(pool) + 1 >= policies.anomaly_min_pool:
                # 새 모델 풀이 찼다. 이제 옛 모델 행은 자리만 차지한다 —
                # **찬 뒤에** 지운다(먼저 지우면 교체 직후가 통째로 판정 불가가 된다).
                await self._prune_old_vectors(model)
            if score is None or len(pool) < policies.anomaly_min_pool:
                # 풀이 아직 얇다. 이때의 큰 거리는 "이상"이 아니라 "모른다"이다.
                continue
            if score < policies.anomaly_threshold:
                continue
            note = await self._explain(image)
            anomaly_id = await self._store.create_anomaly(cam_id, score, at, llm_note=note)
            # 키프레임은 **id 가 정해진 뒤에** 저장한다 — 파일명이 `{anomaly_id}.jpg` 다.
            keyframe_url = await self._save_anomaly_keyframe(anomaly_id, image)
            made.append(anomaly_id)
            log.info("이상 플래그 — cam%d score=%.3f (경고 방송 없음)", cam_id, score)
            if self._publish is not None:
                await self._publish(
                    AnomalyMsg(
                        anomaly_id=anomaly_id,
                        cam_id=cam_id,
                        score=score,
                        detected_at=at,
                        note=note,
                        keyframe_url=keyframe_url,
                    )
                )
        return made

    async def _prune_old_vectors(self, model: str) -> None:
        """옛 모델의 정상 풀 행을 정리한다(§6 `normal_pool.embedding_model`).

        **사람이 `DELETE FROM` 으로 비우게 하지 않는다.** 그건 아무 데도 적혀 있지 않은
        운영 절차라, 모델을 바꾼 사람이 그 사실을 모르면 이상 탐지가 조용히 망가진다.
        """
        if self._pruned or self._store is None:
            return
        self._pruned = True  # 주기마다 부르지 않는다 — 한 번이면 끝나는 일이다
        try:
            removed = await self._store.drop_other_models(model)
        except Exception:
            log.warning("옛 모델의 정상 풀을 정리하지 못했다 — 판정에는 쓰이지 않는다")
            return
        if removed:
            log.info("옛 임베딩 모델의 정상 풀 %d건 정리 — 현재 모델 %s", removed, model)

    async def _save_anomaly_keyframe(self, anomaly_id: int, image: bytes) -> str | None:
        """이상 프레임을 `media/anomalies/{id}.jpg` 로 남긴다(§4 `GET /anomalies`).

        ★ **이벤트 클립과 저장 위치를 나눈다.** 보존 정책이 다르기 때문이다 — 이상
        프레임은 진단용이라 30일 순환으로 충분하고, 증거로 남기는 클립과 섞이면 한쪽
        정책이 다른 쪽을 지운다.

        실패하면 `null` 이다(§5.2 규약). 없는 URL 을 문자열로 내보내지 않는다.
        """
        if self._media_root is None or self._store is None:
            return None
        folder = self._media_root / "anomalies"
        path = folder / f"{anomaly_id}.jpg"
        try:
            await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, image)
            await asyncio.to_thread(self._sweep_anomaly_keyframes, folder)
        except OSError:
            log.warning("이상 키프레임을 저장하지 못했다 — %s", anomaly_id)
            return None
        # ★ **경로를 행에 남긴다.** 이 갱신이 없으면 파일은 디스크에 있는데
        #   `GET /anomalies` 의 `keyframe_url` 은 영원히 `null` 이다 — 화면에는 저장이
        #   실패한 것과 똑같이 보인다(실측으로 그랬다).
        try:
            await self._store.set_anomaly_keyframe(anomaly_id, str(path))
        except Exception:
            log.warning("이상 키프레임 경로를 저장하지 못했다 — %s", anomaly_id)
            return None
        return f"/media/anomalies/{anomaly_id}.jpg"

    def _sweep_anomaly_keyframes(self, folder: Path) -> None:
        """30일 순환. 이 폴더만 훑는다 — 이벤트 클립·키프레임은 건드리지 않는다."""
        cutoff = (self._clock.now() - timedelta(days=ANOMALY_KEYFRAME_RETENTION_DAYS)).timestamp()
        for path in folder.glob("*.jpg"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:  # 지우지 못해도 다음 주기에 다시 만난다
                continue

    async def _explain(self, image: bytes) -> str | None:
        """이상 프레임에 「무엇이 평소와 다른지」 설명을 붙인다(기능명세서 §4.5).

        클라우드가 없으면 `null` 이다 — §5.3 `note` 가 `null` 을 허용하는 이유가 이것이다.
        """
        if self._llm is None:
            return None
        return await self._guard.call(
            "이상 설명",
            self._llm.generate(
                "이 제조현장 CCTV 프레임이 같은 시간대의 평소 모습과 통계적으로 다르다고 "
                "판정됐다. 무엇이 달라 보이는지 한국어 한 문장으로 적어라. "
                "위반이라고 단정하지 말고 보이는 차이만 적는다.",
                images=[image],
            ),
        )

    async def anomaly_flags(self, since: datetime | None) -> int:
        """지표의 `anomaly_flags`(§4.2). 저장소가 없으면 0."""
        if self._store is None:
            return 0
        try:
            rows = await self._store.list_anomalies(since, 500)
        except Exception:
            log.warning("이상 플래그를 세지 못했다")
            return 0
        return len(rows)

    @property
    def sample_interval_s(self) -> float:
        """`anomaly_sample_interval_min`(기본 5분)을 초로. 정책값이다(절대규칙 6)."""
        return max(60.0, float(self._policies.anomaly_sample_interval_min) * 60.0)


def _search_item(
    summary: EventSummary,
    similarity: float | None,
    clip_url: str | None,
) -> SceneSearchItem:
    """§4.3 응답 항목. `similarity` 가 `None` 이면 **SQL 경로**로 나온 것이다.

    `clip_url` 을 여기서 조립하지 않는다 — 경로 → URL 규칙은 저장소에만 있다
    (§5 경로 규약). 아직 추출 전이면 `None` 이고, 그때도 항목은 결과에 나온다.
    """
    return SceneSearchItem(
        event_id=summary.event_id,
        similarity=similarity,
        title=_title(summary),
        cam_id=summary.cam_id,
        occurred_at=summary.detected_at,
        thumbnail_url=summary.thumbnail_url,
        clip_url=clip_url,
    )


_TYPE_LABEL = {
    "no_helmet": "안전모 미착용",
    "zone_intrusion": "금지구역 침입",
    "proximity": "지게차 근접",
    "fall": "쓰러짐",
}


def _title(summary: EventSummary) -> str:
    label = _TYPE_LABEL.get(summary.violation_type.value, summary.violation_type.value)
    where = f" · {summary.zone_id}" if summary.zone_id else ""
    return f"{label} · 카메라 {summary.cam_id}{where}"


def today_since(clock: Clock, days: int) -> datetime:
    """지금부터 `days` 일 전 자정(UTC). 지표·이상 집계의 공통 기준이다."""
    now = clock.now().astimezone(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)


def _summary_sentence(summary: MetricsSummary, period: str | None = None) -> str:
    """집계를 한 문장으로. ★ **시정률과 판정 불가율을 항상 병기한다**(§6.7 표기 규칙).

    분모가 0이면 `–` 다 — `0%` 는 "아무도 시정하지 않았다"는 주장이고 실제로는
    "판정 가능한 이벤트가 없다"이다.

    `period` 를 주면 그것을 쓴다. `MetricsSummary.period` 는 구간을 지정했을 때
    **`"custom"`** 이 되는 내부 값인데, 그대로 문장에 넣으면 LLM 이 그 단어를 그대로
    옮겨 보고서에 「custom 기준 위반 82건」이 나온다(실측).
    """
    return (
        f"{period or summary.period} 기준 위반 {summary.total_violations}건, "
        f"방송 후 시정률 {_percent(summary.correction_rate)} "
        f"(판정 불가 {_percent(summary.undetermined_rate)}). "
        f"시정 {summary.resolved} · 늦은 시정 {summary.resolved_late} · "
        f"미시정 {summary.unresolved} · 판정 불가 {summary.undetermined} · "
        f"방송 없음 {summary.suppressed} · 쓰러짐 {summary.fall_events}건, "
        f"평균 시정 {summary.avg_resolution_sec}초."
    )


def _history_block(history: list[ChatTurn]) -> str:
    """프롬프트에 실을 앞 대화. 없으면 빈 문자열이다.

    ★ **답변까지 함께 싣는다.** 질문만 실으면 「각각 무슨 위반이야?」가 무엇을
    가리키는지 모델이 알 수 없다 — 가리키는 대상은 직전 **답변**에 있다.
    """
    if not history:
        return ""
    lines = [f"- 사람: {turn.question}\n  시스템: {turn.answer}" for turn in history]
    return "앞 대화(오래된 것부터):\n" + "\n".join(lines) + "\n\n"


def _window_label(from_: datetime | None, to: datetime | None) -> str:
    """사람이 읽는 기간 이름. **내부 라벨(`custom`)을 쓰지 않는다.**"""
    if from_ is None and to is None:
        return "오늘"
    start = from_.astimezone(UTC).date().isoformat() if from_ else "처음"
    end = to.astimezone(UTC).date().isoformat() if to else "지금"
    return f"{start} ~ {end}"


def _route_of_tools(used: Sequence[str]) -> ChatRoute:
    """부른 도구들 → §4.4 `route`. **실제로 무엇을 했는지**로 정한다.

    계약이 `sql`/`vector`/`vision` 셋이라 에이전트가 여럿을 불러도 하나로 접어야 한다.
    현재 프레임을 봤으면 그것이 답의 성격을 결정하고(가장 강한 근거), 다음이 집계,
    나머지가 장면 검색이다. 무엇을 불렀는지 전량은 `sources[]` 에 그대로 남는다.

    ⚠ §4.4 는 경로 셋을 전제로 쓰였다. 도구 호출로 바뀌면서 `route` 하나로는 답의
    근거를 다 담지 못한다 — `route: "agent"` 와 `tools_used[]` 를 둘지
    `docs/INDEX.md` 「명세서 확인 필요」에 올려 두었다.
    """
    joined = " ".join(used)
    if "current_scene" in joined:
        return "vision"
    if any(name in joined for name in ("metrics_summary", "violation_breakdown", "repeat_ranking")):
        return "sql"
    return "vector"


def _percent(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def _percent_value(value: float | None) -> int | None:
    """비율(0~1) → 백분율 정수. **`null` 은 `null` 로 둔다**(§6.7).

    표의 셀은 화면이 `–` 로 그린다 — 여기서 문자열로 바꾸면 서버가 그 판단을 한 것이
    되고, 화면은 「재지 않았다」와 「0%」를 다시 구분할 수 없다.
    """
    return None if value is None else round(value * 100)
