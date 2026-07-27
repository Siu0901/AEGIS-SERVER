"""FastAPI 진입점.

M0 에서는 앱 객체와 `/health` 만 있다. REST(`/api/v1/...`)와 WebSocket
(`/ws/edge` · `/ws/dashboard`)은 M1 부터 붙인다.

    uv run uvicorn server.app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI

__all__ = ["API_PREFIX", "app"]

#: API명세서 §1.1 — Base URL `http://<server-host>:8000/api/v1`
API_PREFIX = "/api/v1"

app = FastAPI(
    title="AEGIS",
    version="0.1.0",
    summary="자율 현장 대응형 AI 안전관제 시스템",
)


@app.get("/health")
def health() -> dict[str, str]:
    """부팅 스모크용. 구성요소 상태는 `GET /api/v1/system/status`(FN-SYS-01) 소관이다."""
    return {"status": "ok"}
