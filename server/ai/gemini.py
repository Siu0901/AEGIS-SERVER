"""Gemini 어댑터 — `google-genai` 를 아는 **유일한** 파일. FN-AI-01 · 05

기능명세서 §4.5 — 임베딩은 Gemini Embedding, 심층 분석은 Gemini Flash.

**여기 말고 어디서도 `google.genai` 를 import 하지 않는다**(`ports.py`). 공급자를
바꾸면 이 파일 하나가 교체되고, 그 사실을 테스트가 잠근다.

---

**키가 없으면 만들지 않는다.** `GEMINI_API_KEY` 가 비어 있으면 `create_cloud()` 가
`None` 을 돌려주고, 서버는 클라우드 없이 기동한다 — 감지 → 확정 → 경고 → 시정 루프는
클라우드를 부르지 않으므로 아무것도 달라지지 않는다(FN-SYS-03). 화면에는
`GET /system/status` 의 `cloud.available = false` 로 드러난다.

**동기 SDK 를 스레드로 넘긴다.** `google-genai` 의 호출은 블로킹이라 이벤트 루프에서
그대로 부르면 그동안 `/ws/edge` 수신과 상태머신 틱이 멈춘다 — 그게 곧 클라우드 지연이
안전 루프를 건드리는 경로다. `asyncio.to_thread` 로 밀어낸다.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from server.ai.ports import CloudError, LlmTurn, ToolCall, ToolExchange, ToolSpec

__all__ = ["GeminiCloud", "create_cloud"]

log = logging.getLogger("server.ai.gemini")

#: 기능명세서 §4.5 — 키프레임 임베딩은 3,072차원이며 `halfvec(3072)` 과 짝이다.
#: `gemini-embedding-2` 는 이미지와 텍스트 어느 쪽을 넣어도 이 차원으로 나온다(실측).
EMBEDDING_DIM = 3072

#: 기본 모델. 배포마다 바꿀 수 있게 설정으로 뺀다(절대규칙 6 — 코드에 박지 않는다).
#:
#: ★ **멀티모달 임베딩 모델이어야 한다.** `gemini-embedding-001` 은 텍스트 전용이라
#: 키프레임을 넣으면 `400 The text content is empty` 로 거절한다.
_DEFAULT_EMBED_MODEL = "gemini-embedding-2"
_DEFAULT_TEXT_MODEL = "gemini-flash-latest"


@dataclass(slots=True)
class GeminiCloud:
    """`Embedder` 와 `Llm` 을 함께 구현한다. 둘 다 같은 클라이언트를 쓴다."""

    client: Any
    embed_model: str = _DEFAULT_EMBED_MODEL
    text_model: str = _DEFAULT_TEXT_MODEL

    @property
    def dimensions(self) -> int:
        return EMBEDDING_DIM

    async def embed_image(self, image: bytes, *, mime_type: str = "image/jpeg") -> list[float]:
        """키프레임 한 장 → 벡터. FN-AI-01

        ★ **픽셀을 그대로 임베딩한다.** `gemini-embedding-2` 는 멀티모달이라 이미지와
        문장이 같은 공간에 놓인다 — 그래서 저장된 키프레임 벡터를 텍스트 질의로 바로
        검색할 수 있고(FN-AI-02), 이상 탐지(FN-AI-04)는 화면 자체의 변화를 본다.

        한때 Flash 로 장면을 묘사한 뒤 그 문장을 임베딩했다. `gemini-embedding-001` 이
        텍스트 전용이라 우회한 것이었는데, 대가가 두 가지였다 — 키프레임 한 장에 호출이
        두 번이고, **묘사가 같으면 서로 다른 장면이 같은 벡터가 됐다**. 문장은 픽셀보다
        훨씬 거친 요약이라 이상 탐지가 볼 수 있는 차이가 그만큼 사라진다.

        묘사 단계가 사라지면서 「임베딩은 찾고 비교, LLM 은 읽고 쓰기」(기능명세서 §4.5)가
        원래 모양으로 돌아온다 — 벡터를 만드는 데 생성 모델이 끼지 않는다.
        """
        from google.genai import types  # 어댑터 안에서만 import 한다

        return await self._embed([types.Part.from_bytes(data=image, mime_type=mime_type)])

    async def embed_text(self, text: str) -> list[float]:
        """질의 문장 → 벡터. FN-AI-02

        **키프레임 벡터와 같은 공간이다** — 같은 모델이 양쪽을 만든다. 그래서 문장으로
        그림을 찾을 수 있다.
        """
        if not text.strip():
            # 빈 문자열은 API 가 400 으로 거절한다. 호출을 낭비하지 않고 여기서 막는다.
            msg = "빈 문자열은 임베딩할 수 없다"
            raise CloudError(msg)
        return await self._embed([text])

    async def _embed(self, contents: list[Any]) -> list[float]:
        def call() -> list[float]:
            try:
                response = self.client.models.embed_content(
                    model=self.embed_model,
                    contents=contents,
                )
            except Exception as exc:
                # 텍스트 전용 모델에 이미지를 넣으면 「본문이 비었다」로 돌아온다. 그대로
                # 올리면 원인이 프레임 쪽에 있는 것처럼 읽히므로 여기서 바꿔 적는다.
                if "text content is empty" in str(exc):
                    msg = (
                        f"임베딩 모델 {self.embed_model!r} 이 이미지를 받지 못했다 — "
                        "텍스트 전용 모델이다. GEMINI_EMBED_MODEL 을 멀티모달 모델"
                        f"({_DEFAULT_EMBED_MODEL})로 바꿔라"
                    )
                    raise CloudError(msg) from exc
                raise
            embeddings = getattr(response, "embeddings", None)
            if not embeddings:
                msg = "임베딩 응답이 비어 있다"
                raise CloudError(msg)
            values = list(embeddings[0].values or [])
            if len(values) != EMBEDDING_DIM:
                # 차원이 다르면 pgvector 가 저장을 거부한다. 여기서 먼저 막아야
                # "왜 임베딩이 하나도 없지"가 아니라 원인이 로그에 남는다.
                msg = f"임베딩 차원이 {len(values)} 다 — {EMBEDDING_DIM} 이어야 한다"
                raise CloudError(msg)
            return values

        return await self._guarded(call)

    async def generate(self, prompt: str, *, images: list[bytes] | None = None) -> str:
        """맥락 → 분석문. FN-AI-05 · 08 · 09 · 10"""
        from google.genai import types

        parts: list[Any] = [types.Part.from_text(text=prompt)]
        for image in images or []:
            parts.append(types.Part.from_bytes(data=image, mime_type="image/jpeg"))

        def call() -> str:
            response = self.client.models.generate_content(
                model=self.text_model,
                contents=[types.Content(role="user", parts=parts)],
            )
            text = getattr(response, "text", None)
            if not text:
                msg = "생성 응답이 비어 있다"
                raise CloudError(msg)
            return str(text).strip()

        return await self._guarded(call)

    async def converse(
        self,
        prompt: str,
        *,
        tools: Sequence[ToolSpec],
        history: Sequence[ToolExchange] = (),
        images: Sequence[bytes] = (),
    ) -> LlmTurn:
        """도구 목록을 주고 모델이 무엇을 부를지 고르게 한다. FN-AI-08

        ★ **여기가 유일하게 `FunctionDeclaration` 을 아는 곳이다.** 도구는 포트의
        `ToolSpec`(JSON Schema)으로 들어오고, 공급자 형식으로 바꾸는 일은 이 파일이
        한다 — 그래야 도구 정의가 Gemini 를 모르는 채로 남는다(§7 어댑터 계층).

        `history` 는 **이번 질문 안에서의 도구 왕복**이다. 매 요청에 통째로 다시
        싣는다 — 모델이 이미 부른 도구를 또 부르지 않으려면 무엇을 받았는지 보여야 한다.
        """
        from google.genai import types

        declarations = [
            types.FunctionDeclaration(
                name=spec.name,
                description=spec.description,
                parameters_json_schema=dict(spec.parameters),
            )
            for spec in tools
        ]

        parts: list[Any] = [types.Part.from_text(text=prompt)]
        for image in images:
            parts.append(types.Part.from_bytes(data=image, mime_type="image/jpeg"))
        contents: list[Any] = [types.Content(role="user", parts=parts)]

        for exchange in history:
            # ★ **모델 턴은 원본을 그대로 되싣는다.** 우리가 `ToolCall` 로 다시
            #   조립하면 Gemini 가 붙인 `thought_signature` 가 사라지고
            #   `400 ... missing a thought_signature` 로 거절당한다(실측).
            contents.append(
                exchange.raw
                if exchange.raw is not None
                else types.Content(
                    role="model",
                    parts=[
                        types.Part.from_function_call(name=call.name, args=dict(call.args))
                        for call in exchange.calls
                    ],
                )
            )
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=result.name, response={"result": result.content}
                        )
                        for result in exchange.results
                    ],
                )
            )

        config = types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=declarations)] if declarations else None
        )

        def call() -> LlmTurn:
            response = self.client.models.generate_content(
                model=self.text_model, contents=contents, config=config
            )
            candidates = getattr(response, "candidates", None)
            if not candidates:
                msg = "응답에 후보가 없다"
                raise CloudError(msg)
            turn = candidates[0].content
            said: list[str] = []
            wanted: list[ToolCall] = []
            for part in turn.parts or []:
                if getattr(part, "function_call", None) is not None:
                    wanted.append(
                        ToolCall(
                            name=part.function_call.name,
                            args=dict(part.function_call.args or {}),
                        )
                    )
                elif getattr(part, "text", None):
                    said.append(str(part.text))
            # 문장도 도구 호출도 없으면 루프가 조용히 빈손으로 끝난다. 여기서 막아야
            # 원인이 「모델이 아무것도 돌려주지 않았다」로 남는다(절대규칙 9).
            if not said and not wanted:
                msg = "모델이 문장도 도구 호출도 돌려주지 않았다"
                raise CloudError(msg)
            return LlmTurn(text="\n".join(said).strip(), calls=tuple(wanted), raw=turn)

        return await self._guarded(call)

    @staticmethod
    async def _guarded[T](call: Any) -> T:
        """블로킹 SDK 를 스레드로 넘기고, 어떤 실패든 `CloudError` 로 좁힌다.

        SDK 예외 종류를 그대로 올리면 호출자가 공급자별 예외를 알아야 하고, 그러면
        어댑터 계층이 이름만 남는다.
        """
        try:
            return await asyncio.to_thread(call)
        except CloudError:
            raise
        except Exception as exc:  # SDK 예외 계층을 바깥으로 새게 두지 않는다
            raise CloudError(str(exc)) from exc


def create_cloud(
    api_key: str | None = None,
    *,
    embed_model: str | None = None,
    text_model: str | None = None,
) -> GeminiCloud | None:
    """설정이 갖춰졌을 때만 어댑터를 만든다. 아니면 `None`.

    ★ **키가 없다고 기동을 막지 않는다.** 클라우드는 지능 기능 전용이고, 안전 루프는
    클라우드 없이 완결된다(기능명세서 §4.8 · 아키텍처 Tier 2). 여기서 예외를 던지면
    인터넷 없는 현장에서 서버가 아예 뜨지 않는다 — 그건 격리의 반대다.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY") or ""
    if not key.strip():
        log.info("GEMINI_API_KEY 가 없다 — 지능 기능은 꺼진 채로 기동한다 (안전 기능은 무관)")
        return None
    try:
        from google import genai
    except ImportError:  # pragma: no cover - 설치되어 있다
        log.warning("google-genai 를 불러오지 못했다 — 지능 기능을 끈다")
        return None
    return GeminiCloud(
        client=genai.Client(api_key=key),
        embed_model=embed_model or os.environ.get("GEMINI_EMBED_MODEL") or _DEFAULT_EMBED_MODEL,
        text_model=text_model or os.environ.get("GEMINI_TEXT_MODEL") or _DEFAULT_TEXT_MODEL,
    )
