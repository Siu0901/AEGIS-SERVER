"""지능 기능 — 규정 매핑 · 검색 파싱 · 라우팅 · 이상 점수 · 분석 그래프.

★ **이 파일 전체가 클라우드 없이 돈다.** 그것이 FN-SYS-03 의 검증이기도 하다 —
어댑터 자리에 대역을 넣고, 대역이 죽었을 때 무엇이 남는지를 본다.

여기서 확인하는 판단들:

* 규정 조항은 **LLM 이 만들지 않는다** — 사전 테이블이 결정적으로 연결한다(FN-AI-06)
* 통계 질의에 **벡터 검색을 쓰지 않는다** — 구조화 조건이 SQL 로 먼저 간다(FN-AI-02)
* 이상 탐지는 **경고를 발동하지 않는다**(FN-AI-04)
* 분석 결과는 **저장된다** — 조회할 때마다 다시 부르지 않는다(FN-AI-05)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aegis_contracts import (
    ChatRequest,
    EventDetail,
    EventStatus,
    EventSummary,
    MetricsSummary,
    SceneSearchFilters,
    SceneSearchRequest,
    SimilarIncident,
    TableAttachment,
    ViolationType,
)
from aegis_vision.clock import FakeClock
from server.ai.assistant import route_of
from server.ai.graph import AnalysisInput, AnalysisResult, build_analysis_graph, compose_prompt
from server.ai.guard import CloudGuard
from server.ai.incidents import IncidentMatcher, load_incidents
from server.ai.ports import CloudError
from server.ai.regulations import load_regulations, regulations_for
from server.ai.search import parse_query
from server.ai.service import (
    ANOMALY_THRESHOLD,
    HISTORY_TURNS,
    MIN_POOL,
    AiService,
    time_bucket,
)
from server.ai.vectors import anomaly_score, cosine_similarity
from server.domain.cloud_state import CloudRuntime

NOW = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# FN-AI-06 · 규정 매핑 — 사전 테이블이다
# --------------------------------------------------------------------------


def test_every_violation_type_has_a_regulation() -> None:
    """유형이 늘었는데 표가 따라오지 않으면 그 유형만 근거 없이 남는다."""
    table = load_regulations()
    assert set(table) == set(ViolationType)
    for refs in table.values():
        assert refs, "조항이 비어 있는 유형이 있다"


def test_regulations_are_deterministic() -> None:
    """★ 두 번 불러 같은 값이다. LLM 이 만들면 이 검사가 통과할 수 없다."""
    assert regulations_for("no_helmet") == regulations_for(ViolationType.NO_HELMET)
    assert [ref.code for ref in regulations_for("proximity")] == [
        ref.code for ref in regulations_for("proximity")
    ]


def test_regulation_codes_are_not_invented() -> None:
    """조항 문자열이 실제 규칙 이름 형태인지 최소한으로 잠근다."""
    for refs in load_regulations().values():
        for ref in refs:
            assert "제" in ref.code and "조" in ref.code
            assert ref.title


# --------------------------------------------------------------------------
# FN-AI-02 · 검색 질의 파싱 — 구조화 조건은 SQL 로
# --------------------------------------------------------------------------


def test_structured_only_query_does_not_need_a_vector() -> None:
    """★ 통계·태그 질의에 벡터 검색을 쓰지 않는다(기능명세서 §4.5).

    조건을 다 뽑아내고 나면 랭킹할 문장이 없으므로 `mode` 가 `sql` 이고, 그 경로는
    클라우드 없이 돈다.
    """
    parsed = parse_query("지난주 1번 카메라 안전모", None, FakeClock(NOW))
    assert parsed.cam_id == 1
    assert parsed.violation_type is ViolationType.NO_HELMET
    assert parsed.from_ is not None
    assert parsed.free_text == ""
    assert parsed.mode == "sql"


def test_free_sentence_with_filters_is_hybrid() -> None:
    parsed = parse_query("어제 2번 카메라 사다리 옆 작업 장면", None, FakeClock(NOW))
    assert parsed.cam_id == 2
    assert "사다리" in parsed.free_text
    assert parsed.mode == "hybrid"


def test_pure_sentence_is_vector() -> None:
    parsed = parse_query("사다리 옆에서 자재를 옮기는 모습", None, FakeClock(NOW))
    assert parsed.mode == "vector"
    assert parsed.cam_id is None


def test_explicit_filters_win_over_the_sentence() -> None:
    """화면에서 고른 값이 문장 속 표현을 덮는다 — 고른 것과 다른 결과가 나오면 안 된다."""
    parsed = parse_query(
        "지난주 1번 카메라 장면",
        SceneSearchFilters.model_validate({"from": "2026-08-01", "to": "2026-08-02", "cam_id": 2}),
        FakeClock(NOW),
    )
    assert parsed.cam_id == 2
    assert parsed.from_ is not None and parsed.from_.date().isoformat() == "2026-08-01"
    # `to` 는 그 날의 끝까지다 — 0시로 두면 8월 2일 하루가 통째로 빠진다.
    assert parsed.to is not None
    assert parsed.to.date().isoformat() == "2026-08-02", "그 날 하루가 통째로 빠지면 안 된다"
    assert parsed.to.hour == 23


# --------------------------------------------------------------------------
# FN-AI-08 · 라우팅
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("이번 주 위반 몇 건이야", "sql"),
        ("이번 달 시정률 알려줘", "sql"),
        ("사다리 근처 작업 장면 찾아줘", "vector"),
        ("지금 2번 카메라 상황은?", "vision"),
        ("현재 현장 브리핑", "vision"),
    ],
)
def test_routing_follows_the_spec_table(message: str, expected: str) -> None:
    """기능명세서 §4.5 라우팅 표 그대로다."""
    assert route_of(message).route == expected


def test_vision_route_picks_up_the_camera() -> None:
    assert route_of("지금 2번 카메라 상황은?").cam_id == 2


def test_unknown_question_falls_back_to_scene_search() -> None:
    """★ 모르겠으면 그림을 보여준다 — 틀린 숫자보다 틀린 그림이 낫다."""
    assert route_of("음").route == "vector"


# --------------------------------------------------------------------------
# §6.8 · 이상 점수
# --------------------------------------------------------------------------


def test_empty_pool_has_no_score() -> None:
    """★ `0.0` 이 아니라 `None` 이다 — "완전히 정상"과 "비교할 것이 없다"는 다르다."""
    assert anomaly_score([1.0, 0.0], []) is None


def test_score_is_zero_for_an_identical_sample() -> None:
    assert anomaly_score([1.0, 0.0], [[1.0, 0.0], [1.0, 0.0]]) == 0.0


def test_score_grows_as_the_sample_departs() -> None:
    pool = [[1.0, 0.0]] * 5
    near = anomaly_score([0.99, 0.14], pool)
    far = anomaly_score([0.0, 1.0], pool)
    assert near is not None and far is not None
    assert far > near


def test_cosine_similarity_rejects_a_zero_vector() -> None:
    """영벡터를 0(직교)으로 읽으면 임베딩 결함이 「닮지 않았다」로 둔갑한다."""
    with pytest.raises(ValueError, match="영벡터"):
        cosine_similarity([0.0, 0.0], [1.0, 0.0])


def test_time_bucket_splits_the_day() -> None:
    """시간대별로 정상 풀을 나눈다 — 아침과 야간을 섞으면 조명 변화가 이상이 된다."""
    assert time_bucket(datetime(2026, 8, 14, 5, 0, tzinfo=UTC)) == "03"
    assert time_bucket(datetime(2026, 8, 14, 23, 0, tzinfo=UTC)) == "21"


# --------------------------------------------------------------------------
# FN-SYS-03 · 클라우드 격리
# --------------------------------------------------------------------------


async def _boom() -> str:
    msg = "쿼터 초과"
    raise CloudError(msg)


async def _fine() -> str:
    return "ok"


def test_guard_turns_a_failure_into_state_not_an_exception() -> None:
    """★ 실패가 밖으로 새지 않는다. 대신 상태와 `system` 메시지로 드러난다."""
    runtime = CloudRuntime()
    published: list[Any] = []

    async def publish(message: Any) -> None:
        published.append(message)

    guard = CloudGuard(runtime, FakeClock(NOW), publish)
    assert asyncio.run(guard.call("테스트", _boom())) is None
    assert runtime.available is False
    assert runtime.last_error == "쿼터 초과"
    # 기동 직후도 `down` 이라 상태가 바뀌지 않았다 — 메시지를 만들지 않는 것이 맞다(§5.3).
    assert published == []


def test_guard_reports_recovery() -> None:
    runtime = CloudRuntime()
    published: list[Any] = []

    async def publish(message: Any) -> None:
        published.append(message)

    guard = CloudGuard(runtime, FakeClock(NOW), publish)
    assert asyncio.run(guard.call("테스트", _fine())) == "ok"
    assert runtime.available is True
    assert [message.component for message in published] == ["cloud_api"]
    assert published[0].state == "ok"


# --------------------------------------------------------------------------
# FN-AI-05 · 분석 그래프
# --------------------------------------------------------------------------


def _event(**overrides: Any) -> EventDetail:
    body: dict[str, Any] = {
        "event_id": "EV-20260814-0231",
        "cam_id": 1,
        "track_id": 3,
        "violation_type": "proximity",
        "zone_id": "forklift_lane",
        "status": EventStatus.ALERTED,
        "detected_at": NOW,
        "confirmed_at": NOW,
        "alerted_at": NOW,
        "last_alerted_at": NOW,
        "note": None,
        "resolved_at": None,
        "resolution_sec": None,
        "alert_count": 1,
        "min_distance_m": 1.55,
        "posture": "standing",
        "repeat_count_7d": 4,
        "thumbnail_url": None,
        "clip_url": None,
        "clip_status": "pending",
        "clip_error": None,
        "alert_suppressed": False,
        "keyframe_urls": [],
        "helmet_conf": None,
        "stillness_s": 0.4,
        "height_ratio": 0.97,
        "depth_verified": False,
        "nearby_snapshot": [
            {
                "class": "vehicle",
                "track_id": 11,
                "dist_m": 1.55,
                "depth_verified": False,
                "moving": True,
                "within_danger_radius": True,
            }
        ],
        "llm_analysis": None,
        "regulation_refs": [],
        "similar_incidents": [],
        "timeline": [],
        **overrides,
    }
    return EventDetail.model_validate(body)


def test_graph_fills_regulations_even_without_a_cloud() -> None:
    """★ 클라우드가 죽어도 규정 칸은 채워진다 — 사전 테이블이기 때문이다(FN-AI-06)."""

    async def embed(image: bytes) -> list[float] | None:
        del image
        return None

    async def match(violation_type: str, vector: list[float] | None) -> list[SimilarIncident]:
        del violation_type, vector
        return []

    async def generate(prompt: str, images: list[bytes]) -> str | None:
        del prompt, images
        return None

    graph = build_analysis_graph(embed=embed, match=match, generate=generate)
    state = asyncio.run(graph.ainvoke({"source": AnalysisInput(event=_event())}))
    result: AnalysisResult = state["result"]
    assert result.regulation_refs, "규정은 클라우드와 무관하게 붙어야 한다"
    assert result.llm_analysis is None
    assert result.embedding is None


def test_graph_runs_all_four_steps_when_the_cloud_answers() -> None:
    calls: list[str] = []

    async def embed(image: bytes) -> list[float] | None:
        calls.append("embed")
        del image
        return [0.1, 0.2]

    async def match(violation_type: str, vector: list[float] | None) -> list[SimilarIncident]:
        calls.append("match")
        del violation_type
        assert vector == [0.1, 0.2], "임베딩 결과가 사례 매칭으로 이어져야 한다"
        return [SimilarIncident(title="지게차 후진 충돌", source="KOSHA", similarity=0.84)]

    async def generate(prompt: str, images: list[bytes]) -> str | None:
        calls.append("generate")
        assert "제172조" in prompt, "규정이 프롬프트에 **입력으로** 들어가야 한다"
        assert "유사 사례" in prompt
        assert images, "키프레임이 있으면 멀티모달로 간다"
        return "분석문"

    graph = build_analysis_graph(embed=embed, match=match, generate=generate)
    state = asyncio.run(
        graph.ainvoke({"source": AnalysisInput(event=_event(), keyframe=b"\xff\xd8\xff\xd9")})
    )
    result: AnalysisResult = state["result"]
    assert calls == ["embed", "match", "generate"]
    assert result.llm_analysis == "분석문"
    assert result.similar_incidents[0].similarity == 0.84


def test_empty_result_does_not_erase_a_previous_analysis() -> None:
    """★ 재실행이 손실이 되면 안 된다 — 비어 있는 칸은 `changes` 에 넣지 않는다."""
    changes = AnalysisResult(regulation_refs=regulations_for("fall")).as_changes()
    assert "llm_analysis" not in changes
    assert "embedding" not in changes
    assert "similar_incidents" not in changes
    assert changes["regulation_refs"]


def test_prompt_does_not_ask_for_article_numbers() -> None:
    """★ 조항을 **묻지 않고 알려준다.** 물어보면 그럴듯한 번호를 지어낸다(FN-AI-06)."""
    prompt = compose_prompt(
        AnalysisInput(event=_event()),
        AnalysisResult(regulation_refs=regulations_for("proximity")),
    )
    assert "규정 조항 번호를 새로 만들지 마라" in prompt
    assert "관련 규정(확정된 사실)" in prompt


def test_prompt_omits_missing_values_instead_of_writing_none() -> None:
    """값이 없으면 그 줄을 아예 뺀다 — 「없음」이라고 적으면 관측된 사실처럼 읽힌다."""
    prompt = compose_prompt(AnalysisInput(event=_event(zone_id=None)), AnalysisResult())
    assert "구역:" not in prompt
    assert "None" not in prompt


# --------------------------------------------------------------------------
# FN-AI-07 · 유사 사례
# --------------------------------------------------------------------------


def test_incident_seed_types_are_known() -> None:
    cases = load_incidents()
    assert cases
    assert {case.violation_type for case in cases} <= set(ViolationType)


def test_incidents_are_empty_without_an_embedding() -> None:
    """★ 재지 않은 유사도를 지어내지 않는다 — 유형만 같은 사례에 숫자를 붙이지 않는다."""
    matcher = IncidentMatcher(None)
    assert asyncio.run(matcher.match("proximity", None)) == []


# --------------------------------------------------------------------------
# FN-AI-04 · 이상 탐지는 경고를 발동하지 않는다
# --------------------------------------------------------------------------


class _Frames:
    async def keyframe(self, cam_id: int, at: datetime) -> bytes:
        del cam_id, at
        return b"\xff\xd8\xff\xd9"


class _Embedder:
    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    @property
    def dimensions(self) -> int:
        return len(self._vector)

    async def embed_image(self, image: bytes, *, mime_type: str = "image/jpeg") -> list[float]:
        del image, mime_type
        return list(self._vector)

    async def embed_text(self, text: str) -> list[float]:
        del text
        return list(self._vector)


class _AiStore:
    def __init__(self, pool: list[list[float]]) -> None:
        self._pool = pool
        self.samples: list[list[float]] = []
        self.anomalies: list[tuple[int, float]] = []

    async def add_sample(
        self, cam_id: int, time_bucket: str, vector: list[float], at: datetime
    ) -> None:
        del cam_id, time_bucket, at
        self.samples.append(vector)

    async def pool(self, cam_id: int, time_bucket: str, limit: int) -> list[list[float]]:
        del cam_id, time_bucket, limit
        return list(self._pool)

    async def create_anomaly(
        self,
        cam_id: int,
        score: float,
        at: datetime,
        *,
        keyframe_path: str | None = None,
        llm_note: str | None = None,
    ) -> int:
        del at, keyframe_path, llm_note
        self.anomalies.append((cam_id, score))
        return len(self.anomalies)

    async def list_anomalies(
        self, from_: datetime | None, limit: int
    ) -> list[tuple[int, int, float, datetime, str | None, str | None]]:
        del from_, limit
        return [
            (index, cam, score, NOW, None, None)
            for index, (cam, score) in enumerate(self.anomalies, start=1)
        ]


def _service(store: _AiStore, embedder: _Embedder | None) -> tuple[AiService, list[Any]]:
    published: list[Any] = []

    async def publish(message: Any) -> None:
        published.append(message)

    service = AiService(
        clock=FakeClock(NOW),
        guard=CloudGuard(CloudRuntime(), FakeClock(NOW)),
        store=store,
        frames=_Frames(),
        embedder=embedder,
        llm=None,
        publish=publish,
        cam_ids=(1,),
    )
    return service, published


def test_anomaly_publishes_a_notice_and_never_an_alert() -> None:
    """★ FN-AI-04 — 대시보드 '주의' 알림만이다. `AlertService` 를 부르지 않는다."""
    far_pool = [[1.0, 0.0] for _ in range(MIN_POOL)]
    store = _AiStore(far_pool)
    service, published = _service(store, _Embedder([0.0, 1.0]))

    made = asyncio.run(service.sample_once())

    assert made, "거리가 임계를 넘었으니 플래그가 생겨야 한다"
    assert store.anomalies[0][1] >= ANOMALY_THRESHOLD
    assert [message.type for message in published] == ["anomaly"]
    # 경고 메시지(§5.2 `event_created`)도 MQTT 도 나가지 않는다.
    assert all(message.type == "anomaly" for message in published)


def test_a_thin_pool_does_not_produce_anomalies() -> None:
    """★ 축적 초기의 큰 거리는 「이상」이 아니라 「모른다」다."""
    store = _AiStore([[1.0, 0.0]] * 3)
    service, published = _service(store, _Embedder([0.0, 1.0]))

    assert asyncio.run(service.sample_once()) == []
    assert published == []
    assert store.samples, "판정하지 않아도 샘플은 쌓는다"


def test_samples_accumulate_even_when_flagged() -> None:
    """이상이었던 프레임을 빼면 풀이 좁아져 정상의 정의가 스스로 조여든다."""
    store = _AiStore([[1.0, 0.0] for _ in range(MIN_POOL)])
    service, _ = _service(store, _Embedder([0.0, 1.0]))
    asyncio.run(service.sample_once())
    assert len(store.samples) == 1


def test_no_embedder_means_no_sampling() -> None:
    store = _AiStore([])
    service, published = _service(store, None)
    assert asyncio.run(service.sample_once()) == []
    assert store.samples == []
    assert published == []


# --------------------------------------------------------------------------
# FN-AI-08 · 챗봇 — 통계는 클라우드 없이도 답이 나온다
# --------------------------------------------------------------------------


def _summary() -> MetricsSummary:
    return MetricsSummary(
        period="today",
        correction_rate=0.87,
        undetermined_rate=0.05,
        total_violations=24,
        resolved=20,
        resolved_late=1,
        unresolved=2,
        undetermined=1,
        suppressed=1,
        avg_resolution_sec=41,
        fall_events=0,
        anomaly_flags=1,
    )


def _chat_service(
    summary: MetricsSummary | None = None,
) -> tuple[AiService, _Events, list[tuple[Any, Any]]]:
    """통계 경로를 볼 수 있는 최소 조립. 어느 구간으로 집계했는지 기록한다."""
    asked: list[tuple[Any, Any]] = []
    fixed = summary or _summary()

    async def stats(*, from_: datetime | None = None, to: datetime | None = None) -> MetricsSummary:
        asked.append((from_, to))
        return fixed

    events = _Events([])
    service = AiService(
        clock=FakeClock(NOW),
        guard=CloudGuard(CloudRuntime(), FakeClock(NOW)),
        events=events,
        report_stats=stats,
    )
    return service, events, asked


def test_sql_answer_works_without_a_cloud() -> None:
    """★ §7 가용성 — 인터넷이 끊겨도 SQL 통계는 답이 나와야 한다."""
    service, _, _ = _chat_service()
    response = asyncio.run(service.chat(ChatRequest(session_id="s1", message="이번 주 위반 몇 건")))
    assert response.route == "sql"
    assert "87%" in response.answer
    assert "판정 불가 5%" in response.answer, "시정률과 판정 불가율은 항상 병기한다"
    table = response.attachments[0]
    assert isinstance(table, TableAttachment)
    # ★ 단위가 항목 이름에 있고 값은 백분율 정수다 — 화면이 숫자의 뜻을 추측하지 않는다.
    assert table.rows[0] == ["방송 후 시정률 (%)", 87]


def test_sql_table_keeps_null_as_null() -> None:
    """★ 표의 `null` 을 `–` 로 바꾸지 않는다 — 그 판단은 화면이 한다(§4.4 셀 타입)."""
    empty = _summary().model_copy(update={"correction_rate": None, "undetermined_rate": None})
    service, _, _ = _chat_service(empty)
    response = asyncio.run(service.chat(ChatRequest(session_id="s1", message="시정률 통계")))
    table = response.attachments[0]
    assert isinstance(table, TableAttachment)
    assert table.rows[0] == ["방송 후 시정률 (%)", None]
    assert "–" in response.answer


# --------------------------------------------------------------------------
# FN-AI-08 · 대화 흐름 — `session_id` 가 실제로 일한다
# --------------------------------------------------------------------------


def test_question_period_reaches_the_aggregation() -> None:
    """★ 「이번 주」라고 물으면 이번 주로 집계한다.

    전에는 라우터가 `summary()` 를 인자 없이 불러 **항상 오늘치**를 넘겼다. 문장은
    그럴듯하고 숫자만 틀려서 아무도 알아채지 못한다 — 지표 시스템에서 가장 나쁜 종류의
    결함이다.
    """
    service, _, asked = _chat_service()
    asyncio.run(service.chat(ChatRequest(session_id="s1", message="이번 주 위반 몇 건")))
    from_, _to = asked[-1]
    assert from_ is not None, "기간이 집계까지 닿지 않았다"
    assert (NOW - from_).days >= 6, f"이번 주가 아니라 {from_} 부터로 집계했다"


def test_today_is_the_default_period() -> None:
    service, _, asked = _chat_service()
    asyncio.run(service.chat(ChatRequest(session_id="s1", message="위반 건수 알려줘")))
    assert asked[-1] == (None, None), "기간 표현이 없으면 오늘이다"


def test_follow_up_inherits_the_period() -> None:
    """★ 「이번 주 …」 다음의 「각각 무슨 위반이야?」는 **같은 기간**이어야 한다.

    물려받지 않으면 같은 대화 안에서 두 숫자가 조용히 어긋난다.
    """
    service, _, asked = _chat_service()
    asyncio.run(service.chat(ChatRequest(session_id="s1", message="이번 주 위반 몇 건")))
    asyncio.run(service.chat(ChatRequest(session_id="s1", message="각각 무슨 위반이야?")))
    assert asked[0] == asked[1], f"기간이 바뀌었다: {asked}"


def test_follow_up_stays_on_the_statistics_route() -> None:
    """★ 통계를 이어 묻는데 갑자기 장면 검색으로 새면 안 된다 — 실제로 그랬다."""
    service, _, _ = _chat_service()
    first = asyncio.run(service.chat(ChatRequest(session_id="s1", message="이번 주 위반 몇 건")))
    # 「더 알려줘」에는 세 경로 어느 쪽 신호도 없다 — 앞 대화가 없었다면 `vector` 다.
    second = asyncio.run(service.chat(ChatRequest(session_id="s1", message="더 알려줘")))
    assert first.route == "sql"
    assert second.route == "sql"


def test_sessions_do_not_leak_into_each_other() -> None:
    """다른 사람의 대화가 내 후속 질의의 맥락이 되면 안 된다."""
    service, _, _ = _chat_service()
    asyncio.run(service.chat(ChatRequest(session_id="s1", message="이번 주 위반 몇 건")))
    other = asyncio.run(service.chat(ChatRequest(session_id="s2", message="더 알려줘")))
    # s2 에는 앞 대화가 없으므로 기본 경로로 간다.
    assert other.route == "vector"


def test_forget_clears_the_session() -> None:
    """화면의 「대화 지우기」. 지운 뒤의 후속 질의는 맥락을 물려받지 않는다."""
    service, _, _ = _chat_service()
    asyncio.run(service.chat(ChatRequest(session_id="s1", message="이번 주 위반 몇 건")))
    service.forget("s1")
    after = asyncio.run(service.chat(ChatRequest(session_id="s1", message="더 알려줘")))
    assert after.route == "vector"


def test_history_is_bounded() -> None:
    """경계 없는 dict 를 서버에 두지 않는다 — 며칠 돌면 계속 자란다."""
    service, _, _ = _chat_service()
    for index in range(HISTORY_TURNS + 5):
        asyncio.run(service.chat(ChatRequest(session_id="s1", message=f"위반 건수 {index}")))
    # 비공개 필드를 직접 본다 — 상한은 **바깥에서 관측할 수 없는 성질**이라
    # 행동으로만 확인하려면 서버를 며칠 돌려야 한다.
    assert len(service._history["s1"]) == HISTORY_TURNS


def test_briefing_says_it_could_not_look_when_there_is_no_frame() -> None:
    """★ 「이상 없음」이라고 하지 않는다 — 보지 않고 판단한 것이 되기 때문이다."""

    class _NoFrames:
        async def keyframe(self, cam_id: int, at: datetime) -> bytes:
            del cam_id, at
            msg = "REC 없음"
            raise RuntimeError(msg)

    service = AiService(
        clock=FakeClock(NOW),
        guard=CloudGuard(CloudRuntime(), FakeClock(NOW)),
        frames=_NoFrames(),
        cam_ids=(1, 2),
    )
    response = asyncio.run(service.briefing([1, 2]))
    assert "확인할 수 없다" in response.summary
    assert "이상 없" not in response.summary


# --------------------------------------------------------------------------
# FN-AI-02 · 검색 실행 — SQL 경로는 유사도가 `null` 이다
# --------------------------------------------------------------------------


def _summary_row() -> EventSummary:
    """검색 결과로 나올 이벤트 하나. §4.1 목록 항목이다."""
    return EventSummary.model_validate(_event().model_dump(include=set(EventSummary.model_fields)))


class _Events:
    def __init__(self, rows: list[tuple[Any, float | None, str | None]]) -> None:
        self._rows = rows
        self.last: dict[str, Any] = {}
        self.window: tuple[Any, Any] | None = None

    async def get(self, event_id: str) -> EventDetail | None:
        del event_id
        return None

    async def update(self, event_id: str, changes: Any) -> None:
        del event_id, changes

    async def search_events(self, **kwargs: Any) -> list[tuple[Any, float | None, str | None]]:
        self.last = kwargs
        return self._rows

    async def aggregate_rows(self, from_: Any, to: Any) -> list[Any]:
        self.window = (from_, to)
        return []


def test_structured_query_never_builds_a_vector() -> None:
    """★ 통계·태그 질의는 임베딩을 부르지 않는다 — 조건이 유사도에 밀리면 안 된다."""
    events = _Events([(_summary_row(), None, None)])
    service = AiService(
        clock=FakeClock(NOW),
        guard=CloudGuard(CloudRuntime(), FakeClock(NOW)),
        events=events,
        embedder=_Embedder([0.1, 0.2]),
    )
    response = asyncio.run(
        service.search(
            SceneSearchRequest(
                query="지난주 1번 카메라 안전모", top_k=5, filters=SceneSearchFilters()
            )
        )
    )
    assert response.mode == "sql"
    assert events.last["vector"] is None
    assert events.last["cam_id"] == 1
    assert events.last["violation_type"] == "no_helmet"
    assert response.items[0].similarity is None


def test_free_sentence_ranks_by_vector() -> None:
    events = _Events([(_summary_row(), 0.94, "/media/clips/x.mp4")])
    service = AiService(
        clock=FakeClock(NOW),
        guard=CloudGuard(CloudRuntime(), FakeClock(NOW)),
        events=events,
        embedder=_Embedder([0.1, 0.2]),
    )
    response = asyncio.run(
        service.search(
            SceneSearchRequest(
                query="사다리 옆에서 자재를 옮기는 장면", top_k=5, filters=SceneSearchFilters()
            )
        )
    )
    assert response.mode == "vector"
    assert events.last["vector"] == [0.1, 0.2]
    assert response.items[0].similarity == 0.94


def test_search_falls_back_to_sql_when_the_cloud_is_down() -> None:
    """★ 임베딩에 실패하면 **실제로 돈 경로**를 실어야 한다 — `hybrid` 라고 하면 거짓이다."""

    class _Broken(_Embedder):
        async def embed_text(self, text: str) -> list[float]:
            del text
            msg = "쿼터 초과"
            raise CloudError(msg)

    events = _Events([(_summary_row(), None, None)])
    service = AiService(
        clock=FakeClock(NOW),
        guard=CloudGuard(CloudRuntime(), FakeClock(NOW)),
        events=events,
        embedder=_Broken([0.1, 0.2]),
    )
    response = asyncio.run(
        service.search(
            SceneSearchRequest(query="사다리 옆 장면", top_k=5, filters=SceneSearchFilters())
        )
    )
    assert response.mode == "sql"
    assert response.items[0].similarity is None


def test_report_is_generated_from_sql_numbers() -> None:
    """FN-AI-10 — 클라우드가 없어도 집계만으로 된 보고서가 나온다."""

    async def stats(*, from_: datetime | None = None, to: datetime | None = None) -> MetricsSummary:
        del from_, to
        return _summary()

    service = AiService(
        clock=FakeClock(NOW),
        guard=CloudGuard(CloudRuntime(), FakeClock(NOW)),
        report_stats=stats,
    )

    async def run() -> dict[str, Any]:
        report_id = await service.start_weekly_report(NOW - timedelta(days=7), NOW)
        await asyncio.gather(
            *[task for task in asyncio.all_tasks() if task.get_name().startswith("ai-report")]
        )
        found = service.report(report_id)
        assert found is not None
        return found

    report = asyncio.run(run())
    assert report["status"] == "ready"
    assert "87%" in str(report["body"])
    assert report["stats"]["total_violations"] == 24
