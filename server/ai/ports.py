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

from typing import Protocol, runtime_checkable

__all__ = ["CloudError", "Embedder", "Llm"]


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


@runtime_checkable
class Llm(Protocol):
    """맥락을 읽고 문장을 쓴다. FN-AI-05 · 08 · 09 · 10"""

    async def generate(self, prompt: str, *, images: list[bytes] | None = None) -> str:
        """구조화 맥락(+ 키프레임) → 분석문. 멀티모달 질의도 같은 통로를 쓴다."""
        ...
