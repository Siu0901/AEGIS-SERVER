"""서버 설정 — 전부 환경변수에서 읽는다.

CLAUDE.md 절대규칙 6. 값의 출처는 `.env`(견본 `.env.example`) 하나이며
docker-compose · REC 도 같은 파일을 본다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = ["ServerSettings", "get_server_settings"]


class ServerSettings(BaseSettings):
    """`.env` 또는 환경변수에서 읽는 서버 설정."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    media_root: Path = Path("./media")
    """**서버 노트북**의 영구 보관소 — 이벤트 클립·키프레임.
    7일 원본은 여기가 아니라 REC 쪽에 있다(기능명세서 §4.4)."""

    mediamtx_api: str = "http://127.0.0.1:9997"
    """mediamtx 제어 API. 메인 스트림 연결 상태를 여기서 관측한다(FN-SYS-01)."""

    recorder_base: str = "http://127.0.0.1:9100"
    """REC 주소. **녹화 파일에 파일 경로로 접근하지 않는다** — 항상 이 주소로만(§4.7)."""

    cam_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: [1, 2], validation_alias="REC_CAM_IDS"
    )
    """관제 대상 카메라. 녹화 대상과 같은 집합이므로 `REC_CAM_IDS` 를 함께 쓴다."""

    stream_poll_seconds: float = 1.0
    """mediamtx 폴링 주기. 카메라가 끊긴 것을 3초 안에 알아채야 한다."""

    stream_down_after_seconds: float = 5.0
    """이 시간만큼 스트림이 돌아오지 않으면 `reconnecting` 에서 `down` 으로 내린다."""

    ntp_server: str = "pool.ntp.org"
    ntp_warn_offset_ms: float = 100.0

    @field_validator("cam_ids", mode="before")
    @classmethod
    def _split_cam_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.split(",") if part.strip()]
        return value


@lru_cache(maxsize=1)
def get_server_settings() -> ServerSettings:
    return ServerSettings()
