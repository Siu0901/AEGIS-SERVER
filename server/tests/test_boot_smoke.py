"""서버 부팅 스모크 — `uv run tasks.py verify` 가 이 테스트로 앱 기동을 확인한다.

DB 없이 통과해야 한다. 앱 import 단계에서 DB에 붙으려 하면 여기서 걸린다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app.main import API_PREFIX, app


def test_app_boots_without_database() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_prefix_matches_spec() -> None:
    """API명세서 §1.1 Base URL."""
    assert API_PREFIX == "/api/v1"
