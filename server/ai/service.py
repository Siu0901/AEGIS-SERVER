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
    SceneSearchFilters,
    SceneSearchItem,
    SceneSearchRequest,
    SceneSearchResponse,
    TableAttachment,
)
from aegis_vision.clock import Clock
from server.ai.assistant import route_of
from server.ai.graph import AnalysisInput, AnalysisResult, build_analysis_graph
from server.ai.guard import CloudGuard
from server.ai.incidents import IncidentMatcher
from server.ai.ports import Embedder, Llm
from server.ai.search import parse_query
from server.ai.vectors import anomaly_score

__all__ = ["ANOMALY_THRESHOLD", "AiService", "time_bucket"]

log = logging.getLogger("server.ai")

#: 이 점수를 넘으면 이상 플래그를 만든다(§6.8). 정상 풀이 얇은 초기에는 거리가
#: 크게 나오므로 풀이 `MIN_POOL` 을 넘기 전에는 판정하지 않는다.
ANOMALY_THRESHOLD = 0.35

#: 판정을 시작하기 위한 최소 정상 샘플 수. k-NN 의 k 보다 넉넉해야 한 장의 이상치가
#: 평균을 끌고 다니지 않는다.
MIN_POOL = 12

#: 정상 풀에서 비교할 최근 샘플 수. 시간대별로 나뉘므로 이 정도면 며칠치가 담긴다.
POOL_LIMIT = 200

#: 이상 판정에 쓰는 k(§6.8 「k-최근접 평균 코사인 거리」).
ANOMALY_K = 5

#: 검색 결과 기본 개수. §4.3 요청이 `top_k` 를 주면 그것을 쓴다.
DEFAULT_TOP_K = 12
MAX_TOP_K = 50


def time_bucket(at: datetime) -> str:
    """정상 풀을 나누는 시간대 키(기능명세서 §4.5 「시간대별로 정상 풀을 분리 축적」).

    조명과 그림자가 시간대마다 달라서, 아침 풀과 야간 풀을 섞으면 정상 조명 변화가
    곧 이상으로 잡힌다. 3시간 단위로 나눈다 — 더 잘게 나누면 풀이 채워지지 않는다.
    """
    hour = at.astimezone(UTC).hour
    return f"{hour // 3 * 3:02d}"


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


class AiStore(Protocol):
    """`DbAiRepository` 중 이 서비스가 쓰는 부분."""

    async def add_sample(
        self, cam_id: int, time_bucket: str, vector: list[float], at: datetime
    ) -> None: ...

    async def pool(self, cam_id: int, time_bucket: str, limit: int) -> list[list[float]]: ...

    async def create_anomaly(
        self,
        cam_id: int,
        score: float,
        at: datetime,
        *,
        keyframe_path: str | None = None,
        llm_note: str | None = None,
    ) -> int: ...

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
        self._incidents = IncidentMatcher(embedder)
        self._policies = Policies()
        self._tasks: set[asyncio.Task[None]] = set()
        # 보고서는 메모리에 둔다. **예약 큐가 아니라 결과 캐시다** — 서버가 죽으면
        # 다시 요청하면 되고, 클립 예약(FN-REC-03)처럼 놓치면 증거가 사라지는 것이
        # 아니다. DB 테이블을 늘리는 대신 그 사실을 여기 적어 둔다.
        self._reports: dict[str, dict[str, Any]] = {}
        self._graph = build_analysis_graph(
            embed=self._embed_keyframe,
            match=self._incidents.match,
            generate=self._generate,
        )

    def set_policies(self, policies: Policies) -> None:
        """`anomaly_sample_interval_min` 을 DB 값으로 받는다(절대규칙 6)."""
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

    async def chat(self, request: ChatRequest, summary: MetricsSummary) -> ChatResponse:
        """§4.4 `POST /assistant/chat` — 라우팅 후 해당 경로만 실행한다.

        `summary` 는 라우터가 `GET /metrics/summary` 와 **같은 코드로** 만든 집계다.
        서비스가 지표 저장소를 또 들고 있으면 같은 숫자를 두 곳에서 만들게 되고,
        그때 챗봇과 개요 화면이 서로 다른 시정률을 말한다.
        """
        routing = route_of(request.message)
        if routing.route == "sql":
            return await self._answer_sql(request, summary)
        if routing.route == "vision":
            return await self._answer_vision(routing.cam_id)
        return await self._answer_vector(request)

    async def _answer_sql(self, request: ChatRequest, summary: MetricsSummary) -> ChatResponse:
        """통계 답변. **숫자는 SQL 이 만들고 LLM 은 문장만 만든다.**

        표(`kind = "table"`)를 함께 실어 사람이 문장과 원본을 대조할 수 있게 한다 —
        문장만 주면 그 숫자가 어디서 왔는지 확인할 방법이 없다.

        클라우드가 없으면 서버가 조립한 문장을 그대로 쓴다 — §7 가용성이 「인터넷 단절
        시 SQL 통계 정상 동작」을 요구한다.
        """
        sentence = _summary_sentence(summary)
        table = TableAttachment(
            kind="table",
            columns=["항목", "값"],
            # ★ 셀은 `string` / `number` / `null` 만이다(§4.4). 비율의 `null` 을
            #   문자열 "–" 로 바꾸지 않는다 — 화면이 그 판단을 해야 한다.
            rows=[
                ["방송 후 시정률", summary.correction_rate],
                ["판정 불가율", summary.undetermined_rate],
                ["전체", summary.total_violations],
                ["시정", summary.resolved],
                ["늦은 시정", summary.resolved_late],
                ["미시정", summary.unresolved],
                ["판정 불가", summary.undetermined],
                ["방송 없음(일시중지)", summary.suppressed],
                ["쓰러짐", summary.fall_events],
                ["평균 시정 시간(초)", summary.avg_resolution_sec],
            ],
            label=f"{summary.period} 집계",
        )
        answer = sentence
        if self._llm is not None:
            written = await self._guard.call(
                "통계 문장",
                self._llm.generate(
                    "아래는 안전 관제 시스템이 SQL 로 집계한 사실이다. "
                    "숫자를 바꾸거나 새로 만들지 말고 2~3문장의 한국어로 다듬어라. "
                    "시정률을 말할 때는 판정 불가율을 반드시 함께 적는다.\n\n"
                    f"질문: {request.message}\n집계: {sentence}\n"
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
            "- 보이는 것만 쓴다. 안 보이는 것을 추측하지 않는다.\n"
            "- 사람·지게차의 위치와 눈에 띄는 위험 요인을 우선 적는다.\n"
            "- 작업자 개인을 특정하지 않는다.\n"
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
        self._reports[report_id] = {
            "report_id": report_id,
            "status": "generating",
            "from": from_.date().isoformat(),
            "to": to.date().isoformat(),
            "body": None,
        }
        task = asyncio.create_task(
            self._write_report(report_id, from_, to), name=f"ai-report:{report_id}"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return report_id

    def report(self, report_id: str) -> dict[str, Any] | None:
        """예약된 보고서의 현재 상태. 없으면 `None`."""
        return self._reports.get(report_id)

    async def _write_report(self, report_id: str, from_: datetime, to: datetime) -> None:
        """기간 집계 + 반복 순위를 읽어 보고서 본문을 만든다.

        ★ **숫자는 SQL 이 만든다.** LLM 은 그 숫자를 문장으로 옮길 뿐이고, 집계 원문이
        `stats` 로 함께 남아 사람이 대조할 수 있다. 클라우드가 없으면 집계만으로 된
        보고서가 나간다 — 비어 있는 것보다 낫다.
        """
        report = self._reports[report_id]
        stats = self._report_stats
        summary: MetricsSummary | None = None
        if stats is not None:
            try:
                summary = await stats(from_=from_, to=to)
            except Exception:
                log.exception("보고서 집계를 읽지 못했다 — %s", report_id)
        if summary is None:
            report["status"] = "failed"
            report["body"] = "집계를 읽지 못해 보고서를 만들지 못했다."
            return
        report["stats"] = summary.model_dump(mode="json")
        sentence = _summary_sentence(summary)
        body = sentence
        if self._llm is not None:
            written = await self._guard.call(
                "주간 보고서",
                self._llm.generate(
                    "너는 제조현장 안전관리자를 위한 주간 보고서를 쓴다.\n"
                    f"기간: {report['from']} ~ {report['to']}\n"
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
        report["body"] = body
        report["status"] = "ready"
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
        at = self._clock.now()
        bucket = time_bucket(at)
        made: list[int] = []
        for cam_id in self._cam_ids:
            image = await self._capture(cam_id, at)
            if image is None:
                continue
            vector = await self._guard.call("정상 풀 임베딩", self._embedder.embed_image(image))
            if vector is None:
                # 클라우드가 죽었다. 다음 주기에 다시 시도한다 — 안전 기능과 무관하다.
                return made
            pool = await self._store.pool(cam_id, bucket, POOL_LIMIT)
            score = anomaly_score(vector, pool, k=ANOMALY_K)
            # 샘플은 **판정 여부와 무관하게** 쌓는다. 이상이었던 프레임을 빼면 풀이
            # 점점 좁아져 정상의 정의가 스스로 조여든다.
            await self._store.add_sample(cam_id, bucket, vector, at)
            if score is None or len(pool) < MIN_POOL:
                # 풀이 아직 얇다. 이때의 큰 거리는 "이상"이 아니라 "모른다"이다.
                continue
            if score < ANOMALY_THRESHOLD:
                continue
            note = await self._explain(image)
            anomaly_id = await self._store.create_anomaly(cam_id, score, at, llm_note=note)
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
                        keyframe_url=None,
                    )
                )
        return made

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


def _summary_sentence(summary: MetricsSummary) -> str:
    """집계를 한 문장으로. ★ **시정률과 판정 불가율을 항상 병기한다**(§6.7 표기 규칙).

    분모가 0이면 `–` 다 — `0%` 는 "아무도 시정하지 않았다"는 주장이고 실제로는
    "판정 가능한 이벤트가 없다"이다.
    """
    return (
        f"{summary.period} 기준 위반 {summary.total_violations}건, "
        f"방송 후 시정률 {_percent(summary.correction_rate)} "
        f"(판정 불가 {_percent(summary.undetermined_rate)}). "
        f"시정 {summary.resolved} · 늦은 시정 {summary.resolved_late} · "
        f"미시정 {summary.unresolved} · 판정 불가 {summary.undetermined} · "
        f"방송 없음 {summary.suppressed} · 쓰러짐 {summary.fall_events}건, "
        f"평균 시정 {summary.avg_resolution_sec}초."
    )


def _percent(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"
