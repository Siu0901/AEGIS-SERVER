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

    # --- 경고 (FN-ALM-01 · 02) ---
    audio_dir: Path = Path("./assets/audio")
    """사전 녹음 wav 가 사는 곳. 파일명 매핑은 코드가 아니라 DB(`alert_sounds`)에 있다."""

    audio_backend: str = "auto"
    """`auto` · `winsound` · `ffplay`/`aplay`/`paplay` · `none`.

    `none` 은 **명시적으로만** 고른다. 사운드 장치가 없는 기계에서 서버가 조용해지는 것은
    설정으로 선언해야 하는 사실이지 서버가 알아서 판단할 일이 아니다(절대규칙 9).
    """

    mqtt_host: str = "127.0.0.1"
    """MQTT 브로커. **`localhost` 를 쓰지 않는다** — Windows 에서 `::1` 로 먼저 풀려
    연결마다 IPv6 타임아웃을 먹는다(M2 에서 좌표 지연 2.8초의 원인이었다)."""

    mqtt_port: int = 1883

    mcu_stale_after_s: float = 30.0
    """장치 상태 보고가 이 시간 이상 끊기면 오프라인으로 본다(`sim/mcu_sim` 주기 10초 × 3)."""

    # --- 클라우드 (Tier 2 · FN-AI · FN-SYS-03) ---
    #
    # ★ **`os.environ` 을 직접 읽지 않는다.** pydantic-settings 는 `.env` 를 이 클래스에만
    #   싣고 프로세스 환경에는 넣지 않는다. 어댑터가 `os.environ` 을 보면 `.env` 에 키를
    #   적어도 조용히 「키가 없다」로 떨어지고, 사람은 키가 잘못된 줄 안다.
    #   설정의 원천은 하나여야 한다 — 여기서 읽어 `create_cloud()` 에 넘긴다.
    gemini_api_key: str = ""
    """Gemini API 키. **비어 있으면 지능 기능만 꺼진 채로 기동한다**(FN-SYS-03).

    감지 → 확정 → 경고 → 시정 루프는 클라우드를 부르지 않으므로, 인터넷 없는 현장이
    정상 운용 조건이다. 여기서 예외를 던지면 그 현장에서 서버가 아예 뜨지 않는다.
    """

    gemini_embed_model: str = "gemini-embedding-2"
    """FN-AI-01 — 키프레임·질의 임베딩. 출력 차원이 `halfvec(3072)` 과 맞아야 한다.

    ★ **멀티모달 모델이어야 한다.** 키프레임을 픽셀 그대로 임베딩하므로 텍스트 전용
    모델(`gemini-embedding-001`)을 넣으면 `400 The text content is empty` 로 떨어진다.

    ★ **바꾸면 `normal_pool` 을 비운다.** 벡터는 모델마다 다른 공간에 살아서, 옛 벡터가
    남아 있으면 새 모델의 첫 샘플들이 전부 「평소와 다르다」로 잡힌다(FN-AI-04).
    """

    gemini_text_model: str = "gemini-flash-latest"
    """FN-AI-05 · 08 · 09 · 10 — 심층 분석·챗봇·브리핑·보고서."""

    gemini_embeddings_enabled: bool = True
    """임베딩을 부를 것인가. **끄면 배경 호출이 사라지고 챗봇만 남는다.**

    임베딩과 생성은 호출 성격이 다르다. 생성(챗봇·브리핑)은 **사람이 물을 때만**
    나가지만, 임베딩은 확정 이벤트마다(FN-AI-01) 그리고 `anomaly_sample_interval_min`
    주기로 카메라 수만큼(FN-AI-04) **묻지 않아도 계속** 나간다. 그래서 할당량을 아끼려
    할 때 잘라야 하는 쪽은 항상 이쪽이다.

    끄면 이렇게 된다.

    | 기능 | 결과 |
    |---|---|
    | FN-AI-01 키프레임 임베딩 | 안 만든다 (`events.embedding` 이 비어 있다) |
    | FN-AI-04 정상 풀·이상 탐지 | **돌지 않는다.** 이상 목록이 계속 빈다 |
    | FN-AI-07 유사 사고사례 | 빈 목록 — 재지 않은 유사도를 지어내지 않는다 |
    | FN-AI-02 장면 검색 | 벡터 랭킹 없이 SQL 조건 검색으로 내려간다(`mode: "sql"`) |
    | FN-AI-08 챗봇 | **그대로 동작한다** — `vector` 경로도 SQL 검색으로 답한다 |
    | FN-AI-05 · 09 · 10 심층분석·브리핑·보고서 | 그대로 동작한다 |

    ★ **이상 탐지가 꺼진 것은 화면에서 「이상 0건」과 구분되지 않는다.** 그래서 기동
    로그에 반드시 남긴다(절대규칙 9). 끄기로 했다면 그 사실을 아는 사람이 있어야 한다.
    """

    gemini_timeout_s: float = 10.0
    """클라우드 호출 한 번을 기다리는 상한(초). **API 하한이 10초다.**

    ★ 같은 요청의 응답 시간이 크게 갈린다 — 도구 선택은 정상 1.4~7.0초, 최종 답변은
    정상 14~23초인데 네 번에 한 번쯤 마감까지 응답이 없다(최악 225초). 지연이 페이로드
    크기·thinking 토큰과 무관하고 동기 직접 호출에서도 재현되므로 API 쪽 변동이다.
    걸어 두지 않으면 챗봇이 1분 넘게 아무 말도 하지 않는다.

    **10초는 API 하한이자, 답변을 짧게 쓰게 한 뒤의 정상 최대(8.3초)를 넘는 값이다.**
    긴 답변을 허용하면 정상 생성이 23초까지 가서 마감을 30초로 올려야 하고, 그러면
    재시도 한 번이 60초가 된다 — 짧게 쓰는 규칙과 이 값은 함께 정해졌다.
    """

    # `alert_duration_s`(경광등·부저 지속)와 `clip_extract_margin_s`(추출 여유)는 여기
    # 있었지만 §4.5 정책 키가 되면서 DB 로 옮겼다. 현장에서 조정하는 값은 배포가 아니라
    # 설정이어야 하고, 임계값의 원천은 하나여야 한다(CLAUDE.md 절대규칙 6).

    @field_validator("cam_ids", mode="before")
    @classmethod
    def _split_cam_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.split(",") if part.strip()]
        return value


@lru_cache(maxsize=1)
def get_server_settings() -> ServerSettings:
    return ServerSettings()
