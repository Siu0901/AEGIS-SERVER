"""DB 접속 설정과 엔진 팩토리.

M0 에서는 접속 경로만 잡는다. 리포지토리 구현은 M1 이다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine
from sqlmodel import create_engine

__all__ = ["DbSettings", "create_db_engine", "get_db_settings"]


class DbSettings(BaseSettings):
    """`.env` 또는 환경변수에서 읽는 DB 설정."""

    model_config = SettingsConfigDict(
        env_prefix="AEGIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://aegis:aegis@localhost:5432/aegis"
    """`docker-compose.yml` 의 postgres 서비스 기본값과 맞춰 둔다."""

    echo_sql: bool = False


@lru_cache(maxsize=1)
def get_db_settings() -> DbSettings:
    return DbSettings()


def create_db_engine(settings: DbSettings | None = None) -> Engine:
    resolved = settings or get_db_settings()
    return create_engine(resolved.database_url, echo=resolved.echo_sql, pool_pre_ping=True)
