"""데이터 모델 — SQLModel 테이블 정의.

출처: `docs/AEGIS_기능명세서.md` §6 (데이터 모델)

**§6에 적힌 컬럼만 정의한다.** 명세서에 없는 컬럼을 여기서 만들지 않으며,
필요해 보이면 `docs/INDEX.md` 의 「명세서 확인 필요」 절에 남기고 사람의 판단을
기다린다(CLAUDE.md 절대규칙 8).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import REAL, Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

__all__ = [
    "EMBEDDING_DIM",
    "AlertSound",
    "Anomaly",
    "Camera",
    "Event",
    "NormalPoolSample",
    "Policy",
    "VehicleClassRow",
    "Zone",
]

#: Gemini Embedding 2 차원 수. FN-AI-01 — pgvector `halfvec(3072)`.
EMBEDDING_DIM = 3072


def _timestamptz(*, nullable: bool = True) -> Column[Any]:
    """`timestamptz` 컬럼. 저장은 UTC, 표시는 KST (API명세서 §1.2)."""
    return Column(DateTime(timezone=True), nullable=nullable)


class Event(SQLModel, table=True):
    """확정된 위반 사건. 기능명세서 §6 `events`

    상태 전이는 §4.2 상태 전이표를 따른다. `expired` 는 판정 불가이며
    **시정률 분모·분자 모두에서 제외**된다(§4.8). `dropped`(확정 전 소멸)도 지표에서
    빠지지만 **레코드는 남는다** — `dropped / (dropped + 확정)` 이 `confirm_duration_s`
    튜닝의 근거이기 때문이다.
    """

    __tablename__ = "events"

    event_id: str = Field(primary_key=True, description="EV-YYYYMMDD-NNNN")
    cam_id: int = Field(index=True)
    track_id: int = Field(index=True)
    violation_type: str = Field(index=True)
    zone_id: str | None = Field(default=None, index=True)
    status: str = Field(index=True)

    detected_at: datetime | None = Field(default=None, sa_column=_timestamptz())
    confirmed_at: datetime | None = Field(default=None, sa_column=_timestamptz())
    alerted_at: datetime | None = Field(default=None, sa_column=_timestamptz())
    last_alerted_at: datetime | None = Field(
        default=None,
        sa_column=_timestamptz(),
        description="최근 경고 시각. alerted_at(최초)은 변경하지 않는다",
    )
    resolved_at: datetime | None = Field(default=None, sa_column=_timestamptz())

    resolution_sec: int | None = Field(default=None, description="경고→시정 소요")
    alert_count: int = Field(default=0, description="재경고 포함 횟수")

    lost_at: datetime | None = Field(default=None, sa_column=_timestamptz())
    expired_at: datetime | None = Field(default=None, sa_column=_timestamptz())
    dropped_at: datetime | None = Field(
        default=None,
        sa_column=_timestamptz(),
        description="확정 전 소멸 시각. 종결 시각 셋(resolved·expired·dropped) 중 하나",
    )

    reassoc_count: int = Field(default=0, description="재결합 횟수")
    prev_track_ids: list[int] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
        description="재결합 이전 트랙 번호 이력",
    )

    min_distance_m: float | None = Field(default=None)
    depth_verified: bool | None = Field(default=None)
    posture: str | None = Field(default=None)
    stillness_s: float | None = Field(default=None, description="쓰러짐 판정 근거 ③")
    height_ratio: float | None = Field(
        default=None,
        # §6이 이 컬럼만 `real` 로 명시한다. SQLModel 기본 매핑(double precision)을
        # 쓰면 마이그레이션과 타입이 어긋나므로 명시적으로 REAL 을 준다.
        sa_column=Column(REAL, nullable=True),
        description="쓰러짐 판정 근거 ① (확정 시점 값)",
    )
    helmet_conf: float | None = Field(default=None, description="2단계 분류 신뢰도")

    nearby_snapshot: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
        description="확정 시점 주변 차량 목록 [{track_id, dist_m, moving}]",
    )
    similar_incidents: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
        description="유사 사고사례. 확정 시 1회 계산해 저장한다",
    )

    clip_path: str | None = Field(default=None)
    keyframe_paths: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
        description="키프레임 저장 경로 배열 (2~3장)",
    )
    clip_status: str | None = Field(
        default=None,
        description="pending / ready / failed — 예약 추출 상태",
    )
    clip_error: str | None = Field(
        default=None,
        description="클립 추출 실패 사유. REC 의 reason 을 그대로 담고 note 에 섞지 않는다",
    )
    alert_suppressed: bool = Field(
        default=False,
        description=(
            "경고 일시중지 중 확정되어 방송이 나가지 않은 이벤트. 시정률에서 전량 제외된다"
        ),
    )

    embedding: Any | None = Field(
        default=None,
        sa_column=Column(HALFVEC(EMBEDDING_DIM), nullable=True),
        description="키프레임 임베딩",
    )

    llm_analysis: str | None = Field(default=None, description="심층 분석문")
    regulation_refs: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
        description="매핑 조항",
    )
    is_false_positive: bool = Field(default=False, description="수동 정정")
    note: str | None = Field(
        default=None,
        description="관리자 메모. 수동 정정(is_false_positive) 사유 등",
    )


class Zone(SQLModel, table=True):
    """금지구역. 기능명세서 §6 `zones`

    `polygon_m` 은 **지면 실좌표(m)** 꼭짓점 배열이다. 화면에서 그린 픽셀 좌표는
    서버가 호모그래피로 변환해 저장한다(API명세서 §4.5).
    """

    __tablename__ = "zones"

    zone_id: str = Field(primary_key=True)
    cam_id: int = Field(index=True)
    name: str = Field(description="표시 이름. 예: 지게차 통행로")
    polygon_m: list[list[float]] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    polygon: list[list[float]] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
        description=(
            "사용자가 화면에서 그린 정규화 픽셀 폴리곤. **이쪽이 원본이다** — "
            "캘리브레이션이 갱신되면 서버가 이 값으로 polygon_m 을 다시 계산한다(§4.5)"
        ),
    )
    buffer_m: float = Field(default=0.0, description="경계 여유 — 호모그래피 오차 흡수")
    active: bool = Field(default=True)


class Camera(SQLModel, table=True):
    """카메라와 캘리브레이션 결과. 기능명세서 §6 `cameras`

    카메라를 물리적으로 움직이면 재캘리브레이션이 필요하다(API명세서 §6.2).
    """

    __tablename__ = "cameras"

    cam_id: int = Field(primary_key=True)
    name: str
    rtsp_main: str = Field(description="1080p 메인 — 서버(라이브 · 녹화 · 클립 원본)")
    rtsp_sub: str = Field(description="640p 서브 — 엣지(추론)")
    homography: list[list[float]] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
        description="3×3 픽셀→지면 변환 행렬",
    )
    ref_height: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
        description=(
            "높이 비율 기준 — {height_px, at_m}. **스칼라가 아니다**(기능명세서 §6). "
            "기준 높이를 어느 지면 위치에서 쟀는지가 없으면 다른 거리의 기대 높이를 "
            "구할 수 없다 — 같은 사람도 멀수록 화면상 높이가 줄어들기 때문이다"
        ),
    )
    calib_points: list[dict[str, Any]] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
        description=(
            "캘리브레이션에 쓴 대응점 원본(API명세서 §4.5 `calib_points`). "
            "행렬만으로는 어느 점을 찍었는지 복원할 수 없어 화면에서 고칠 수 없다"
        ),
    )
    reproj_error_m: float | None = Field(
        default=None,
        description="재투영 오차 RMS(m). 4점이면 0이고 5점 이상부터 의미를 갖는다",
    )
    calibrated_at: datetime | None = Field(default=None, sa_column=_timestamptz())


class VehicleClassRow(SQLModel, table=True):
    """클래스별 위험 반경. 기능명세서 §6 `vehicle_classes`

    위험 반경은 장비를 따라다니는 **동적 영역**이고, 근접 임계값
    (`proximity_threshold_m`)은 **즉시 경고 기준**이다. 둘은 2단계로 동작한다.
    """

    __tablename__ = "vehicle_classes"

    class_name: str = Field(primary_key=True)
    danger_radius_m: float = Field(default=3.0, description="지게차 기본 3.0m")
    active: bool = Field(default=True)


class AlertSound(SQLModel, table=True):
    """위반 유형 → 경고 음원 매핑. 기능명세서 §6 `alert_sounds` · FN-ALM-01 · FN-CFG-03

    파일명을 코드에 박으면 절대규칙 6(하드코딩 금지)과 FN-CFG-03(화면에서 지정) 둘 다
    깨진다. 관리자가 설정 화면에서 유형별 음원과 등급을 바꿀 수 있어야 하므로 §6 이
    이 테이블을 정의했다.

    `violation_type` 은 두 가지로 쓰인다.

    | 값 | 쓰임 |
    |---|---|
    | `no_helmet` · `zone_intrusion` · `proximity` · `fall` | 자동 경고(FN-ALM-01) |
    | 그 밖의 이름 (`custom_notice` 등) | 수동 방송(FN-ALM-04 · §4.5 `sound`) |

    한 테이블로 둔 이유: 수동 방송의 `sound` 도 결국 "이름 → 파일" 조회다. 나누면 같은
    파일이 두 곳에 등록될 수 있고, 어느 쪽이 재생되는지가 호출 경로에 따라 갈린다.
    §4.5 도 `sound` 를 "`alert_sounds` 테이블의 키"라고 적어 이 쓰임을 전제한다.
    """

    __tablename__ = "alert_sounds"

    violation_type: str = Field(primary_key=True, description="위반 유형 또는 수동 방송 음원 이름")
    file_path: str = Field(description="assets/audio/ 기준 상대 경로. 루트를 벗어날 수 없다")
    level: int = Field(default=2, description="1 | 2 | 3 — §3 AlertCommand.level 과 같은 척도")
    label: str | None = Field(default=None, description="설정 화면 표시 이름. 미지정이면 null")
    active: bool = Field(default=True, description="꺼두면 그 유형은 방송하지 않는다")


class Policy(SQLModel, table=True):
    """정책값 key-value. 기능명세서 §6 `policies`

    임계값·타이머는 코드가 아니라 **여기서 읽는다**(CLAUDE.md 절대규칙 6).
    기본값의 원천은 `aegis_contracts.Policies` 이며 `scripts/seed_policies.py` 로 시드한다.
    """

    __tablename__ = "policies"

    key: str = Field(primary_key=True)
    value: Any = Field(sa_column=Column(JSONB, nullable=False))


class NormalPoolSample(SQLModel, table=True):
    """정상 풀 샘플. 기능명세서 §6 `normal_pool` · FN-AI-04

    서버가 자체 1080p 스트림에서 캡처하므로 **엣지 추론 예산과 무관**하다.
    """

    __tablename__ = "normal_pool"

    id: int | None = Field(default=None, primary_key=True)
    cam_id: int = Field(index=True)
    time_bucket: str = Field(index=True, description="시간대별 분리 축적")
    embedding: Any | None = Field(
        default=None,
        sa_column=Column(HALFVEC(EMBEDDING_DIM), nullable=True),
    )
    sampled_at: datetime | None = Field(default=None, sa_column=_timestamptz())


class Anomaly(SQLModel, table=True):
    """이상 탐지 플래그. 기능명세서 §6 `anomalies` · FN-AI-04

    **경고 방송·경광등을 발동하지 않는다.** 대시보드 '주의' 알림으로만 표시한다.
    """

    __tablename__ = "anomalies"

    id: int | None = Field(default=None, primary_key=True)
    cam_id: int = Field(index=True)
    score: float
    keyframe_path: str | None = Field(default=None)
    llm_note: str | None = Field(default=None)
    detected_at: datetime | None = Field(default=None, sa_column=_timestamptz())
