"""DB 접속 설정과 엔진 팩토리.

M0 에서는 접속 경로만 잡는다. 리포지토리 구현은 M1 이다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine
from sqlmodel import create_engine

__all__ = ["DbSettings", "create_db_engine", "get_db_settings"]


class DbSettings(BaseSettings):
    """`.env` 또는 환경변수에서 읽는 DB 설정."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # 아래 필드가 `validation_alias` 로 두 이름을 받으므로 필드명으로도 넣을 수 있게
        # 열어둔다. 그러지 않으면 `DbSettings(database_url=...)` 이 통하지 않아 테스트가
        # 환경변수를 거쳐야만 설정을 바꿀 수 있다.
        populate_by_name=True,
    )

    database_url: str = Field(
        default="postgresql+psycopg://aegis:aegis@127.0.0.1:5432/aegis",
        validation_alias=AliasChoices("DATABASE_URL", "AEGIS_DATABASE_URL"),
    )
    """`docker-compose.yml` 의 postgres 서비스와 같은 자격증명을 가리켜야 한다.

    **`DATABASE_URL` 과 `AEGIS_DATABASE_URL` 을 모두 받는다.** M0 은 `AEGIS_` 접두사를
    썼지만 `.env.example` 은 접두사 없는 이름으로 정리했다(API명세서 §4.7 이
    `RECORDER_BASE` 같은 이름을 그대로 지정하고 있어서다). 접두사만 보게 두면
    `.env` 에 적은 값이 조용히 무시되고 아래 기본값으로 붙는데, 그 실패는 "왜
    비밀번호가 틀리지"로만 보여서 원인을 찾는 데 한참 걸린다.
    """

    echo_sql: bool = Field(
        default=False,
        validation_alias=AliasChoices("ECHO_SQL", "AEGIS_ECHO_SQL"),
    )


@lru_cache(maxsize=1)
def get_db_settings() -> DbSettings:
    return DbSettings()


def create_db_engine(settings: DbSettings | None = None) -> Engine:
    resolved = settings or get_db_settings()
    return create_engine(resolved.database_url, echo=resolved.echo_sql, pool_pre_ping=True)
