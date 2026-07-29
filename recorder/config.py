"""REC 설정 — 전부 환경변수에서 읽는다.

CLAUDE.md 절대규칙 6 — 경로·임계값·튜닝 파라미터를 코드에 하드코딩하지 않는다.
값의 출처는 `.env`(견본 `.env.example`) 하나이며 docker-compose 도 같은 파일을 본다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = ["RecSettings", "get_rec_settings"]


class RecSettings(BaseSettings):
    """`.env` 또는 환경변수에서 읽는 REC 설정.

    접두사를 쓰지 않는다 — API명세서 §4.7 이 `RECORDER_BASE` · `REC_RETENTION_DAYS` 를
    그 이름 그대로 환경변수로 지정하고 있어서다.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    rtsp_base: str = "rtsp://127.0.0.1:8554"
    """카메라 RTSP 루트. `{rtsp_base}/cam{N}/main` 을 구독한다. **서브는 녹화하지 않는다** —
    서브는 추론 전용이다(API명세서 §4.7 녹화 규격)."""

    rec_bind_host: str = "127.0.0.1"
    rec_bind_port: int = 9100

    rec_media_root: Path = Path("./media/rec")
    """세그먼트 저장 루트. 운용 시 엣지 NVMe SSD 마운트 지점.

    **절대경로로 정규화한다**(아래 validator). `.env` 에는 `./media/rec` 처럼 상대경로를
    적는 것이 자연스러운데, 그대로 두면 구간 추출이 깨진다 — concat 목록 파일은 임시
    디렉토리에 만들어지고 ffmpeg 의 concat demuxer 는 목록 안의 상대경로를 **목록 파일이
    있는 위치 기준**으로 푼다. 그러면 `%TEMP%/aegis-rec-xxxx/media/rec/...` 를 찾다가
    실패한다.
    """

    rec_cam_ids: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [1, 2])
    """녹화 대상 카메라. `.env` 에는 `REC_CAM_IDS=1,2` 로 적는다.

    `NoDecode` 가 필요한 이유: pydantic-settings 는 `list[int]` 필드를 소스 단계에서
    JSON 으로 먼저 파싱하려 하고, 그 시점에 `1,2` 가 깨져 아래 validator 까지 오지도
    못한다. 설정 파일에 JSON 배열을 적게 하는 것보다 이쪽이 낫다.
    """

    rec_segment_seconds: int = 10
    """세그먼트 길이. API명세서 §4.7 녹화 규격 = 10초."""

    rec_retention_days: float = 7.0
    """보존 기간(일). 기능명세서 §4.4 링버퍼 = 7일.

    `float` 인 이유는 보존 정책이 실제로 지우는지 확인할 때 분 단위로 줄여봐야 하기
    때문이다. 운용값은 정수 7 이다.
    """

    rec_max_disk_gb: float = 50.0
    """용량 상한(GB). 초과하면 보존 기간 이내라도 오래된 것부터 지운다(FN-REC-05)."""

    rec_sweep_seconds: float = 30.0
    """보존 정책 점검 주기(초)."""

    @field_validator("rec_cam_ids", mode="before")
    @classmethod
    def _split_cam_ids(cls, value: object) -> object:
        """`REC_CAM_IDS=1,2` 처럼 쉼표로 온 값을 받는다."""
        if isinstance(value, str):
            return [int(part) for part in value.split(",") if part.strip()]
        return value

    @field_validator("rec_media_root", mode="after")
    @classmethod
    def _absolute_root(cls, value: Path) -> Path:
        """상대경로를 절대경로로 굳힌다. 이유는 필드 docstring 참고."""
        return value.expanduser().resolve()

    @property
    def retention_seconds(self) -> float:
        return self.rec_retention_days * 86400.0

    @property
    def max_disk_bytes(self) -> int:
        return int(self.rec_max_disk_gb * 1024**3)

    def main_stream_url(self, cam_id: int) -> str:
        return f"{self.rtsp_base}/cam{cam_id}/main"


@lru_cache(maxsize=1)
def get_rec_settings() -> RecSettings:
    return RecSettings()
