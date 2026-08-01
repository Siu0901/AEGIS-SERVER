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
from dataclasses import dataclass
from typing import Any

from server.ai.ports import CloudError

__all__ = ["GeminiCloud", "create_cloud"]

log = logging.getLogger("server.ai.gemini")

#: 기능명세서 §4.5 — 키프레임 임베딩은 3,072차원이며 `halfvec(3072)` 과 짝이다.
EMBEDDING_DIM = 3072

#: 기본 모델. 배포마다 바꿀 수 있게 설정으로 뺀다(절대규칙 6 — 코드에 박지 않는다).
_DEFAULT_EMBED_MODEL = "gemini-embedding-001"
_DEFAULT_TEXT_MODEL = "gemini-flash-latest"

#: `embed_image` 의 앞 단계 — 장면을 **검색용 문장**으로 옮긴다.
#:
#: ★ **판정을 요구하지 않는다.** 「위험해 보인다」 같은 문장이 나오면 그 판단이 벡터에
#: 실려 검색 결과의 근거가 된다 — 규정 조항을 LLM 이 만들지 못하게 한 것(FN-AI-06)과
#: 같은 이유다. 여기서 묻는 것은 「무엇이 어디에 있는가」뿐이다.
_CAPTION_PROMPT = (
    "이 제조현장 CCTV 프레임에 보이는 것을 한국어 2~3문장으로 묘사해라.\n"
    "- 사람과 지게차의 수·위치·자세, 주변 설비와 자재, 조명 상태를 적는다.\n"
    "- 위험한지 안전한지 **판단하지 마라**. 보이는 것만 적는다.\n"
    "- 안 보이는 것을 추측하지 마라.\n"
    "- 작업자 개인을 특정하지 마라."
)


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

        ★ **장면을 먼저 문장으로 옮긴 뒤 임베딩한다.** `gemini-embedding-001` 은 텍스트
        전용이라 이미지를 넣으면 `400 The text content is empty` 로 거절한다(실측).
        멀티모달 임베딩(`multimodalembedding@001`)은 Vertex AI 쪽이라 AI Studio 키로는
        닿지 않는다.

        그래서 두 단계로 나눈다 — Flash 가 장면을 묘사하고(읽기), 그 문장을 임베딩한다
        (찾고 비교하기). 「임베딩은 찾고 비교, LLM 은 읽고 쓰기」라는 역할 분리
        (기능명세서 §4.5)는 그대로다.

        **부수 효과로 검색이 더 정확해진다.** 질의도 문장이므로 양쪽이 같은 공간에
        놓인다 — 이미지 벡터와 텍스트 질의를 억지로 비교하던 것보다 낫다.

        **대가**: 키프레임 한 장에 호출이 두 번(묘사 + 임베딩)이고, 묘사가 같으면
        서로 다른 장면이 같은 벡터가 된다. 이상 탐지(FN-AI-04)의 민감도가 그만큼
        낮아진다 — 조명 변화 오탐이 줄어드는 방향이기도 하다.
        """
        caption = await self.describe(image, mime_type=mime_type)
        return await self._embed([caption])

    async def describe(self, image: bytes, *, mime_type: str = "image/jpeg") -> str:
        """장면을 검색용 한 문단으로 옮긴다. `embed_image` 의 앞 단계다.

        프롬프트가 **검색을 위한 묘사**를 요구한다 — 판단이나 위반 여부가 아니라
        「무엇이 어디에 있는가」다. 모델이 "안전해 보인다" 같은 판정을 쓰기 시작하면
        그 판정이 벡터에 실려 검색 결과의 근거가 되고, 그건 FN-AI-06 이 규정 조항에
        대해 막은 것과 같은 종류의 오염이다.
        """
        from google.genai import types  # 어댑터 안에서만 import 한다

        parts = [
            types.Part.from_text(text=_CAPTION_PROMPT),
            types.Part.from_bytes(data=image, mime_type=mime_type),
        ]

        def call() -> str:
            response = self.client.models.generate_content(
                model=self.text_model,
                contents=[types.Content(role="user", parts=parts)],
            )
            text = getattr(response, "text", None)
            if not text or not str(text).strip():
                # 빈 문자열을 임베딩에 넘기면 같은 400 이 난다. 여기서 먼저 막아야
                # 원인이 「묘사가 비었다」로 남는다.
                msg = "장면 묘사가 비어 있다"
                raise CloudError(msg)
            return str(text).strip()

        return await self._guarded(call)

    async def embed_text(self, text: str) -> list[float]:
        """질의 문장 → 벡터. FN-AI-02"""
        if not text.strip():
            # 빈 문자열은 API 가 400 으로 거절한다. 호출을 낭비하지 않고 여기서 막는다.
            msg = "빈 문자열은 임베딩할 수 없다"
            raise CloudError(msg)
        return await self._embed([text])

    async def _embed(self, contents: list[Any]) -> list[float]:
        def call() -> list[float]:
            response = self.client.models.embed_content(
                model=self.embed_model,
                contents=contents,
            )
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
