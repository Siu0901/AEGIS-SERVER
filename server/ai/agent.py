"""어시스턴트 에이전트 — LangGraph 도구 호출 루프. FN-AI-08 · API명세서 §4.4

```
        ┌──────────┐   도구를 부르겠다   ┌──────────┐
START ─▶│  think   │────────────────────▶│   act    │
        │ (모델)    │◀────────────────────│ (도구 실행)│
        └────┬─────┘    결과를 돌려준다    └──────────┘
             │ 문장으로 답하겠다
             ▼
            END
```

★ **경로를 미리 고르지 않는다.** 모델이 등록된 도구(`tools.py`)를 보고 필요한 것을
필요한 만큼 부른다. 「이번 주 위반 분석해주고 어떻게 해결할지」 하나에
`metrics_summary` 와 `repeat_ranking` 이 **함께** 불린다 — 경로를 하나만 고르는
키워드 방식으로는 만들 수 없던 답이다.

★ **한 바퀴 안에서 끝나게 상한을 둔다.** 도구가 계속 실패하면 모델이 같은 것을
되부를 수 있고, 그 루프는 사용자 쪽에서 「응답 없음」으로만 보인다.

★ **도구 실패는 모델에게 문자열로 돌려준다.** 예외로 끊으면 답변 전체가 사라지지만,
「그 도구는 실패했다」를 알려주면 모델이 남은 것으로 답한다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool

from server.ai.ports import CloudError, Llm, LlmTurn, ToolExchange, ToolResult, ToolSpec

__all__ = ["MAX_STEPS", "MINIATURE_CONTEXT", "SYSTEM_PROMPT", "AgentResult", "run_agent"]

log = logging.getLogger("server.ai.agent")

#: 도구 왕복 상한. 넘으면 마지막 문장으로 끝낸다.
#:
#: 넉넉하면 모델이 도구를 탐색하듯 부르며 응답이 길어진다. 실측으로 대부분의 질문이
#: 1~2 바퀴에 끝난다.
MAX_STEPS = 4

#: 이 현장이 미니어처 모형이라는 사실. **모델이 이것을 모르면 답이 뒤집힌다.**
#:
#: 실측(2026-08-21) — 「지금 1번 카메라에 뭐가 보여?」에 모델이
#: 「레고 모형 피규어가 서 있다. **실제 작업자는 식별되지 않는다**」고 답했다.
#: 사람이 읽으면 「위험 없음」이다. 그런데 같은 프레임에서 감지 파이프라인은 그 인물들을
#: `person` 으로 잡아 위반을 확정하고 경고 방송까지 내보내고 있었다. 화면과 챗봇이
#: 정반대를 말하는 상태이고, 둘 중 사람이 믿는 쪽은 문장이다.
#:
#: **모형인지 여부는 이 시스템의 관심사가 아니다.** 감지·확정·경고·시정 판정이 전부
#: 모형을 대상으로 성립하도록 만들어져 있다(기능명세서 §4.7 축척 환산). 모델만
#: 혼자 다른 전제를 쓰면 그 답은 틀린 정도가 아니라 반대다.
MINIATURE_CONTEXT = """이 현장은 **미니어처 모형으로 구성된 시연 환경**이다(기능명세서 §4.7).

- 화면의 레고 인물은 **작업자**이고, 장난감 트럭·지게차는 **지게차**다. 감지 모델도
  그렇게 판정한다(`toy_person` → `person`, `toy_truck` → `vehicle`). 네가 보는 모형은
  이 시스템이 실제로 감시하고 경고를 내보내는 대상 그 자체다.
- 축척은 42.5배다. 모형 인물 4cm 가 작업자 신장 1.7m 에 해당하고, 모형 1cm 가 현장
  0.425m 다. 거리 임계값도 같은 축척으로 환산해 심어 두었으므로, 도구가 돌려준 거리
  수치는 그대로 쓰면 된다.
- **「모형이라 실제 위험은 없다」·「실제 작업자는 식별되지 않는다」고 쓰지 마라.**
  관리자가 알고 싶은 것은 모형인지 여부가 아니라 위반이 일어났는지다. 그 한 문장이
  감지·경고·시정 판정을 전부 부정하는 것으로 읽힌다.
- 장면을 묘사할 때도 모형 용어가 아니라 **현장 용어**로 쓴다 — 「레고 피규어 3개」가
  아니라 「작업자 3명」이고, 「장난감 트럭」이 아니라 「지게차」다.
- 다만 **없는 것을 지어내는 것과는 다르다.** 화면에 인물 모형이 없으면 작업자가 없는
  것이고, 컬러바·검은 화면이면 그 사실을 그대로 적는다.
"""

#: 시스템 지시. **여기서 막는 것이 곧 이 프로젝트의 규칙이다.**
SYSTEM_PROMPT = """너는 중소 제조현장 안전관제 시스템의 어시스턴트다.
관리자가 현장 상황을 묻고, 너는 등록된 도구로 사실을 확인해 답한다.

규칙 — 어기면 이 답변은 쓸모가 없다.

1. **숫자를 지어내지 마라.** 건수·비율·거리·시간은 반드시 도구가 돌려준 값만 쓴다.
   도구를 부르지 않고 통계를 말하지 않는다.
2. **시정률을 말할 때는 판정 불가율을 반드시 함께 적는다.** 판정 불가는 추적이
   끊겨 시정 여부를 판정할 수 없었던 건이며 시정률 분모에서 빠져 있다.
   분모가 0이면 비율은 `null` 이고, 그때는 「0%」가 아니라 「판정 가능한 건이 없다」다.
3. **규정 조항을 지어내지 마라.** `regulations` 도구로 확인한 것만 인용한다.
4. **도구가 실패했으면 그 사실을 적는다.** 없는 값을 추측으로 메우지 않는다.
5. 작업자 개인을 특정하거나 책임을 묻지 않는다. **추적번호는 신원이 아니다.**
6. 용어는 제조현장 용어를 쓴다 — 「지게차」·「지게차 통행로」·「지게차 근접」이며
   「굴착기」·「중장비」가 아니다. 위반 유형은 넷뿐이다:
   안전모 미착용 · 금지구역 침입 · 지게차 근접 · 쓰러짐.
7. 이상 탐지는 **위반이 아니다.** 조명·날씨로도 점수가 오르며 경고 방송을 발동하지
   않는다. 「주의해서 한 번 볼 것」으로만 말한다.
8. 클립·이미지 URL 을 문장에 적지 마라. 화면이 자동으로 첨부한다.
9. 한국어로, 관리자가 바로 읽을 수 있게 답한다. 개선안을 물으면 도구로 확인한
   사실에 근거해 제안한다 — 근거 없는 일반론은 적지 않는다.
10. **짧게 쓴다.** 기본 3~6문장이고, 표가 필요하면 짧은 목록으로 대신한다. 길어질수록
   응답이 느려져 관제 화면에서 기다리는 시간이 된다 — 실측으로 1,200자 답변은
   생성에만 15초가 걸린다. 물어본 것에만 답하고 배경 설명을 덧붙이지 않는다.
"""


@dataclass(slots=True)
class AgentResult:
    """에이전트 한 판의 결과."""

    answer: str
    used: list[str] = field(default_factory=list)
    """부른 도구들. 그대로 답변의 근거(`sources[]`)가 된다."""
    steps: int = 0
    truncated: bool = False
    """상한에 걸려 멈췄는가. **조용히 감추지 않는다**(절대규칙 9)."""


async def run_agent(
    llm: Llm,
    question: str,
    tools: Sequence[BaseTool],
    specs: Sequence[ToolSpec],
    *,
    history: str = "",
    max_steps: int = MAX_STEPS,
    site_context: str = "",
) -> AgentResult:
    """질문 하나를 도구 호출 루프로 답한다.

    `history` 는 **앞 대화**다(§4.4). 이력이 없으면 「각각은?」 같은 후속 질문이
    독립 질의로 처리되어 무엇을 가리키는지 알 수 없다.
    """
    by_name = {item.name: item for item in tools}
    # 현장 맥락을 **규칙보다 먼저** 놓는다. 무엇을 보고 있는지 모른 채 규칙만 읽으면
    # 모델이 스스로 전제를 세우고, 그 전제가 틀리면 규칙을 다 지켜도 답이 뒤집힌다.
    prompt = f"{site_context}{SYSTEM_PROMPT}\n{history}\n관리자 질문: {question}\n"

    exchanges: list[ToolExchange] = []
    last = ""
    for step in range(max_steps):
        turn: LlmTurn = await llm.converse(prompt, tools=specs, history=exchanges)
        if turn.text:
            last = turn.text
        if not turn.wants_tools:
            return AgentResult(answer=turn.text, steps=step + 1)

        results: list[ToolResult] = []
        for call in turn.calls:
            results.append(ToolResult(name=call.name, content=await _run(by_name, call)))
        exchanges.append(ToolExchange(calls=turn.calls, results=tuple(results), raw=turn.raw))

    # 상한까지 갔다. 마지막 문장이라도 있으면 그것을 쓰고, 없으면 사실대로 적는다 —
    # 빈 답변을 돌려주면 화면에는 「대답하지 않았다」로만 보인다.
    log.warning("도구 왕복 상한 %d 에 걸렸다 — 마지막 응답으로 끝낸다", max_steps)
    return AgentResult(
        answer=last or "확인에 시간이 너무 걸려 답을 마치지 못했다. 질문을 나눠서 물어봐라.",
        steps=max_steps,
        truncated=True,
    )


async def _run(by_name: dict[str, BaseTool], call: object) -> str:
    """도구 하나를 실행한다. **실패해도 예외로 끊지 않는다.**

    예외를 올리면 답변 전체가 사라진다. 「그 도구는 실패했다」를 모델에게 알려주면
    남은 도구 결과로 답을 만든다.
    """
    name = getattr(call, "name", "")
    args = dict(getattr(call, "args", {}) or {})
    found = by_name.get(name)
    if found is None:
        # 등록하지 않은 도구를 모델이 지어냈다. 조용히 넘기지 않는다.
        log.warning("모델이 없는 도구를 불렀다 — %s", name)
        return f'{{"error": "등록되지 않은 도구다: {name}"}}'
    try:
        return str(await found.ainvoke(args))
    except CloudError as exc:
        log.warning("도구 %s 가 클라우드 실패로 끝났다: %s", name, exc)
        return f'{{"error": "클라우드 실패: {exc}"}}'
    except Exception as exc:
        log.exception("도구 %s 실행이 실패했다", name)
        return f'{{"error": "도구 실행 실패: {exc}"}}'
