"""클라우드 어댑터 경계 — **여기가 유일한 통로다.** FN-SYS-03 · 비기능 §7(확장성)

`server/ai` 안의 어떤 모듈도 `google.genai` 를 직접 import 하지 않는다. 전부 이
프로토콜 뒤에 있고, 구현은 `gemini.py`(실물)와 테스트의 대역이다. 그래야
「LLM·임베딩 공급자 교체 가능한 어댑터 계층」(§7)이 선언이 아니라 구조가 된다.

---

**역할 분리 — 임베딩은 찾고 비교, LLM 은 읽고 쓰기**(기능명세서 §4.5).

| 포트 | 하는 일 | 하지 않는 일 |
|---|---|---|
| `Embedder` | 장면을 벡터로 바꾼다 | 설명하지 않는다 |
| `Llm` | 주어진 맥락을 읽고 문장을 쓴다 | 조항을 지어내지 않는다(FN-AI-06) |

**규정 조항은 LLM 이 만들지 않는다.** 사전 매핑 테이블(`regulations.py`)이 결정적으로
연결하고, LLM 에는 그 결과를 **입력으로** 넣는다. 반대로 하면 존재하지 않는 조항 번호가
관리자에게 근거처럼 제시된다.

---

**실패는 예외로 올린다.** 조용히 `None` 을 돌려주면 호출자가 「분석이 없다」와
「클라우드가 죽었다」를 구분하지 못하고, `GET /system/status` 의 `cloud` 절이 영영
`ok` 로 남는다(절대규칙 9). 격리는 호출자(`CloudGuard`)가 맡는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "CloudError",
    "Embedder",
    "Llm",
    "LlmTurn",
    "ToolCall",
    "ToolExchange",
    "ToolResult",
    "ToolSpec",
]


class CloudError(RuntimeError):
    """클라우드 호출이 실패했다. **안전 루프와 무관한 실패다**(FN-SYS-03).

    한도 초과·인증 실패·네트워크 단절을 구분하지 않는다 — 호출자가 하는 일은
    어느 경우에나 같기 때문이다: 상태를 `down` 으로 바꾸고 분석을 비워 둔다.
    """


@runtime_checkable
class Embedder(Protocol):
    """장면·문장을 벡터로. FN-AI-01

    **벡터는 로컬에만 보관한다**(기능명세서 §4.5 · §7 보안). 클라우드로 나가는 것은
    키프레임과 질의 문장이고, 돌아온 벡터는 pgvector 컬럼에 남는다.
    """

    @property
    def dimensions(self) -> int:
        """벡터 차원. `halfvec(3072)` 과 반드시 같아야 한다."""
        ...

    async def embed_image(self, image: bytes, *, mime_type: str = "image/jpeg") -> list[float]:
        """키프레임 한 장 → 벡터."""
        ...

    async def embed_text(self, text: str) -> list[float]:
        """질의 문장 → 벡터. 같은 공간에 놓여야 이미지와 비교된다."""
        ...


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """모델에게 알려줄 도구 하나. **공급자 형식이 아니다.**

    `parameters` 는 JSON Schema 다 — `@tool` 이 만든 `args_schema` 를 그대로 넣는다.
    Gemini 의 `FunctionDeclaration` 으로 바꾸는 일은 어댑터가 한다.
    """

    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """모델이 부르기로 한 도구 하나."""

    name: str
    args: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """도구 실행 결과. 모델에게 되돌려 준다."""

    name: str
    content: str


@dataclass(frozen=True, slots=True)
class ToolExchange:
    """도구 왕복 한 번 — 모델이 부른 것들과 그 결과.

    대화 이력이 아니라 **이번 질문 안에서의 추론 흔적**이다. 에이전트 루프가 한 바퀴
    돌 때마다 하나씩 쌓이고, 다음 요청에 통째로 다시 실린다.
    """

    calls: tuple[ToolCall, ...]
    results: tuple[ToolResult, ...]
    raw: Any = None
    """공급자가 돌려준 **원본 모델 턴**. 어댑터만 만들고 어댑터만 읽는다.

    ★ **재구성하지 않고 그대로 되싣기 위해서다.** Gemini 는 함수 호출 파트에
    `thought_signature` 를 붙여 보내고, 그것 없이 같은 호출을 되돌려주면
    `400 ... missing a thought_signature` 로 거절한다(실측). 우리가 만든
    `ToolCall` 로 다시 조립하면 그 서명이 사라진다.

    에이전트는 이 값을 **들여다보지 않는다** — 공급자 교체 시 이 칸의 내용만 바뀐다.
    """


@dataclass(frozen=True, slots=True)
class LlmTurn:
    """모델의 한 번 응답. **문장이거나 도구 호출이거나 둘 다일 수 있다.**"""

    text: str = ""
    calls: tuple[ToolCall, ...] = ()
    raw: Any = None
    """`ToolExchange.raw` 로 그대로 넘길 원본 턴. 에이전트는 내용을 보지 않는다."""

    @property
    def wants_tools(self) -> bool:
        return bool(self.calls)


@runtime_checkable
class Llm(Protocol):
    """맥락을 읽고 문장을 쓴다. FN-AI-05 · 08 · 09 · 10"""

    async def generate(self, prompt: str, *, images: list[bytes] | None = None) -> str:
        """구조화 맥락(+ 키프레임) → 분석문. 멀티모달 질의도 같은 통로를 쓴다."""
        ...

    async def converse(
        self,
        prompt: str,
        *,
        tools: Sequence[ToolSpec],
        history: Sequence[ToolExchange] = (),
        images: Sequence[bytes] = (),
    ) -> LlmTurn:
        """도구 목록을 함께 주고 **모델이 무엇을 부를지 고르게 한다**. FN-AI-08

        ★ **경로를 키워드로 가르지 않는다.** 「이번 주 위반 분석해주고 어떻게 해결할지」
        같은 복합 질문은 경로를 하나만 고르는 구조로는 원리적으로 답할 수 없다 —
        집계와 반복 순위를 **함께** 봐야 하기 때문이다. 모델이 필요한 도구를 필요한
        만큼 부르고, 그 결과를 종합한다.

        **숫자는 여전히 도구가 만든다.** 모델은 무엇을 부를지 고르고 결과를 읽을 뿐이다
        (§4.4 「통계 답변의 숫자는 SQL 이 만든다」).
        """
        ...
