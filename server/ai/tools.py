"""어시스턴트 도구 — 모델이 부를 수 있는 것 전량. FN-AI-08 · API명세서 §4.4

★ **경로를 키워드로 가르지 않는다.** 예전에는 질문에서 낱말을 찾아 `sql`/`vector`/
`vision` 셋 중 하나를 골랐다. 그러면 「이번 주 위반 분석해주고 어떻게 해결할지」처럼
집계와 반복 순위를 **함께** 봐야 하는 질문에 원리적으로 답할 수 없다 — 경로를 하나만
고르는 구조이기 때문이다. 실제로 그 질문이 장면 검색으로 새서 「관련 장면 5건을
찾았다」만 돌아왔다.

이제 도구를 등록하고 **모델이 무엇을 부를지 고른다.** 필요하면 여럿을, 필요하면
연달아 부른다.

---

**지켜지는 것 두 가지** — 도구로 바뀌어도 이건 그대로다.

1. **숫자는 도구가 만든다.** 모델은 무엇을 부를지 고르고 결과를 읽을 뿐이며, 집계는
   `EventService.summary` 와 `server/domain/aggregates` 가 낸다 — 개요·분석 화면과
   **같은 코드**다. 두 곳에서 세면 화면과 챗봇이 다른 시정률을 말한다.
2. **규정 조항은 모델이 만들지 않는다**(FN-AI-06). `regulations` 도구가 사전 매핑
   테이블을 읽어 돌려주고, 모델은 그 결과만 인용한다.

**도구는 Gemini 를 모른다.** `@tool` 이 만든 JSON Schema 를 `ToolSpec` 으로 옮기고,
공급자 형식(`FunctionDeclaration`)으로 바꾸는 일은 어댑터가 한다(§7 어댑터 계층).

**첨부는 곁길로 모은다.** 도구가 모델에게 돌려주는 것은 요약 JSON 이고, 클립·표 같은
화면용 첨부는 `ToolBox.attachments` 에 쌓인다 — 모델 맥락에 URL 을 흘려보내면 그것을
문장에 지어내 쓰기 시작한다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool, tool

from aegis_contracts import (
    ChatAttachment,
    ClipAttachment,
    EventRefAttachment,
    SceneSearchFilters,
    SceneSearchRequest,
    TableAttachment,
)
from aegis_vision.clock import Clock
from server.ai.ports import ToolSpec
from server.ai.regulations import regulations_for
from server.app.event_service import day_start

__all__ = ["ToolBox", "specs_of"]

log = logging.getLogger("server.ai.tools")

#: 한 질문에서 장면 검색이 돌려줄 최대 개수. 넘으면 첨부가 대화를 덮는다.
SCENE_LIMIT = 5

#: 반복 순위 기본 개수.
REPEAT_LIMIT = 10


def specs_of(tools: Sequence[BaseTool]) -> list[ToolSpec]:
    """`@tool` 이 만든 스키마 → 포트의 `ToolSpec`.

    `args_schema` 는 pydantic 모델이므로 JSON Schema 를 그대로 뽑을 수 있다.
    도구 정의가 공급자를 모르는 채로 남는 지점이 여기다.
    """
    specs: list[ToolSpec] = []
    for item in tools:
        schema: dict[str, Any] = {"type": "object", "properties": {}}
        if item.args_schema is not None:
            schema = item.args_schema.model_json_schema()  # type: ignore[union-attr]
            # `title` · `default` 는 모델에게 필요 없고, 스키마만 길어진다.
            schema.pop("title", None)
        specs.append(ToolSpec(name=item.name, description=item.description, parameters=schema))
    return specs


def _dump(value: Any) -> str:
    """도구 결과를 모델이 읽을 JSON 으로. **숫자를 문자열로 바꾸지 않는다.**"""
    return json.dumps(value, ensure_ascii=False, default=str)


class ToolBox:
    """서비스에 묶인 도구 묶음. 질문 하나마다 새로 만든다.

    **질문마다 새로 만드는 이유**: `attachments` 가 이번 답변의 첨부를 모으는 자리라
    재사용하면 지난 질문의 클립이 따라온다.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        summary: Any = None,
        breakdown: Any = None,
        repeat: Any = None,
        search: Any = None,
        briefing: Any = None,
        anomalies: Any = None,
        events: Any = None,
        cam_ids: Sequence[int] = (),
        timezone: ZoneInfo | None = None,
    ) -> None:
        self._clock = clock
        self._summary = summary
        self._breakdown = breakdown
        self._repeat = repeat
        self._search = search
        self._briefing = briefing
        self._anomalies = anomalies
        self._events = events
        self._cam_ids = tuple(cam_ids)
        self._tz = timezone or ZoneInfo("UTC")
        self.attachments: list[ChatAttachment] = []
        self.used: list[str] = []
        self.tools: list[BaseTool] = self._build()

    # -- 기간 계산 ------------------------------------------------------

    def _window(self, days: int) -> tuple[datetime, datetime]:
        """`days` 일 전 **현지 자정**부터 지금까지.

        **자정 기준이다.** 「이번 주」를 168시간 전으로 자르면 같은 질문을 오후에
        물었을 때와 오전에 물었을 때 모집단이 달라진다.

        시간대는 설정(`REPORT_TIMEZONE`)에서 온다 — 챗봇이 말하는 「오늘」과 화면의
        「오늘」이 다르면, 같은 시각에 두 숫자가 어긋나고 그 이유를 아무도 모른다.
        """
        now = self._clock.now()
        return day_start(now, self._tz, days_ago=max(0, days - 1)), now

    # -- 도구 정의 ------------------------------------------------------

    def _build(self) -> list[BaseTool]:
        box = self

        @tool
        async def metrics_summary(days: int = 7) -> str:
            """기간의 안전 지표 집계. 위반 건수, 방송 후 시정률, 판정 불가율,
            해소/늦은 시정/미시정/판정 불가 건수, 평균 시정 시간, 쓰러짐 건수.

            시정률을 말할 때는 판정 불가율을 반드시 함께 적어야 한다.
            days: 최근 며칠을 볼지. 기본 7.
            """
            box.used.append(f"metrics_summary(days={days})")
            if box._summary is None:
                return _dump({"error": "지표 집계가 연결되지 않았다"})
            start, end = box._window(days)
            found = await box._summary(from_=start, to=end)
            body = found.model_dump(mode="json")
            box.attachments.append(
                TableAttachment(
                    kind="table",
                    columns=["항목", "값"],
                    rows=[
                        ["방송 후 시정률 (%)", _percent(found.correction_rate)],
                        ["판정 불가율 (%)", _percent(found.undetermined_rate)],
                        ["전체", found.total_violations],
                        ["시정", found.resolved],
                        ["늦은 시정", found.resolved_late],
                        ["미시정", found.unresolved],
                        ["판정 불가", found.undetermined],
                        ["방송 없음(일시중지)", found.suppressed],
                        ["쓰러짐", found.fall_events],
                        ["평균 시정 시간(초)", found.avg_resolution_sec],
                    ],
                    label=f"최근 {days}일 집계",
                )
            )
            return _dump(body)

        @tool
        async def violation_breakdown(days: int = 7) -> str:
            """기간의 위반 유형별 건수. 어떤 위반이 몇 건인지 알아야 할 때 쓴다.
            유형은 안전모 미착용 / 금지구역 침입 / 지게차 근접 / 쓰러짐 넷뿐이다.

            days: 최근 며칠을 볼지. 기본 7.
            """
            box.used.append(f"violation_breakdown(days={days})")
            if box._breakdown is None:
                return _dump({"error": "유형별 집계가 연결되지 않았다"})
            start, end = box._window(days)
            buckets = await box._breakdown(start, end)
            return _dump([{"유형": name, "건수": count} for name, count in buckets])

        @tool
        async def repeat_ranking(days: int = 7, limit: int = REPEAT_LIMIT) -> str:
            """반복 위반 순위. 어느 카메라·구역·추적번호에서 같은 위반이 몇 번
            되풀이됐는지 돌려준다. 원인을 짚거나 개선 대상을 고를 때 쓴다.

            추적번호는 세션 안의 번호일 뿐 작업자 신원이 아니다.
            days: 최근 며칠. limit: 몇 줄까지.
            """
            box.used.append(f"repeat_ranking(days={days})")
            if box._repeat is None:
                return _dump({"error": "반복 순위가 연결되지 않았다"})
            rows = await box._repeat(days, limit)
            return _dump(rows)

        @tool
        async def search_scenes(query: str, days: int = 30, top_k: int = SCENE_LIMIT) -> str:
            """과거 이벤트 장면을 자연어로 검색한다. 「무엇이 찍혔는지 보고 싶다」는
            질문에만 쓴다. 통계를 묻는 질문에는 쓰지 않는다.

            결과 클립은 화면에 자동으로 첨부되므로 URL 을 문장에 적지 않는다.
            query: 찾고 싶은 장면 설명. days: 최근 며칠. top_k: 개수.
            """
            box.used.append(f"search_scenes({query!r})")
            if box._search is None:
                return _dump({"error": "검색이 연결되지 않았다"})
            found = await box._search(
                SceneSearchRequest(
                    query=query, top_k=min(top_k, SCENE_LIMIT), filters=SceneSearchFilters()
                )
            )
            del days  # 기간은 질의 문장에서 파서가 뽑는다(§4.3)
            for item in found.items:
                if item.clip_url and item.thumbnail_url:
                    box.attachments.append(
                        ClipAttachment(
                            kind="clip",
                            event_id=item.event_id,
                            clip_url=item.clip_url,
                            thumbnail_url=item.thumbnail_url,
                            label=item.title,
                        )
                    )
                else:
                    box.attachments.append(
                        EventRefAttachment(
                            kind="event_ref", event_id=item.event_id, label=item.title
                        )
                    )
            return _dump(
                {
                    "mode": found.mode,
                    "items": [
                        {
                            "event_id": item.event_id,
                            "title": item.title,
                            "occurred_at": item.occurred_at,
                            "similarity": item.similarity,
                        }
                        for item in found.items
                    ],
                }
            )

        @tool
        async def current_scene(cam_id: int | None = None) -> str:
            """**지금** 카메라에 무엇이 보이는지. 현재 프레임을 캡처해 장면을 묘사한다.
            「지금」·「현재」 상황을 묻는 질문에만 쓴다. 과거를 묻는 질문에는 쓰지 않는다.

            cam_id: 특정 카메라만 볼 때. 생략하면 전체.
            """
            box.used.append(f"current_scene(cam_id={cam_id})")
            if box._briefing is None:
                return _dump({"error": "프레임 캡처가 연결되지 않았다"})
            found = await box._briefing([cam_id] if cam_id else list(box._cam_ids))
            return _dump({"captured_at": found.captured_at, "scene": found.summary})

        @tool
        async def regulations(violation_type: str) -> str:
            """위반 유형에 걸리는 산업안전보건기준 조항. **조항 번호를 지어내지 말고
            반드시 이 도구로 확인한 것만 인용한다.**

            violation_type: no_helmet / zone_intrusion / proximity / fall 중 하나.
            """
            box.used.append(f"regulations({violation_type})")
            refs = regulations_for(violation_type)
            return _dump([{"code": ref.code, "title": ref.title} for ref in refs])

        @tool
        async def recent_anomalies(days: int = 7) -> str:
            """이상 탐지 목록. 평소와 다른 장면으로 표시된 것들이다.
            **위반이 아니다** — 조명·날씨로도 점수가 오르며 경고 방송을 발동하지 않는다.

            days: 최근 며칠.
            """
            box.used.append(f"recent_anomalies(days={days})")
            if box._anomalies is None:
                return _dump({"error": "이상 탐지가 연결되지 않았다"})
            rows = await box._anomalies(days)
            return _dump(rows)

        @tool
        async def event_detail(event_id: str) -> str:
            """이벤트 한 건의 상세. 상태·시각·구역·자세·주변 지게차 거리와 저장된
            심층 분석문·유사 사례·규정 조항을 돌려준다.

            event_id: `EV-20260814-0231` 형식.
            """
            box.used.append(f"event_detail({event_id})")
            if box._events is None:
                return _dump({"error": "이벤트 저장소가 연결되지 않았다"})
            found = await box._events.get(event_id)
            if found is None:
                return _dump({"error": f"이벤트를 찾을 수 없다: {event_id}"})
            box.attachments.append(
                EventRefAttachment(kind="event_ref", event_id=event_id, label=event_id)
            )
            return _dump(found.model_dump(mode="json"))

        return [
            metrics_summary,
            violation_breakdown,
            repeat_ranking,
            search_scenes,
            current_scene,
            regulations,
            recent_anomalies,
            event_detail,
        ]


def _percent(value: float | None) -> int | None:
    """비율(0~1) → 백분율 정수. **`null` 은 `null` 로 둔다**(§6.7).

    분모가 0이면 `0%` 가 아니라 「재지 않았다」이며, 화면이 그 판단을 한다.
    """
    return None if value is None else round(value * 100)
