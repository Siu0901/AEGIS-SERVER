"""정책값(임계값·타이머) 전체.

출처: API명세서 §4.5 `GET /policies` / `PATCH /policies`

여기 있는 기본값은 **DB `policies` 테이블 시드의 원천**이다.
런타임에는 항상 DB 값을 읽고, 코드에 임계값을 하드코딩하지 않는다(CLAUDE.md 절대규칙 6).
"""

from ._base import SpecModel

__all__ = ["Policies", "PolicyPatch"]


class Policies(SpecModel):
    """정책값 전량. API명세서 §4.5"""

    # --- 이벤트 상태머신 타이머 (기능명세서 §4.2) ---
    confirm_duration_s: int = 3
    """후보 → 확정 지속 조건."""

    resolve_duration_s: int = 10
    """위반 소멸 → 해소 판정 지속 조건."""

    cooldown_s: int = 30
    """재경고 최소 간격."""

    resolve_window_s: int = 300
    """이 시간 내 해소된 건만 시정률 분자에 포함."""

    # --- 트랙 소실 · 재결합 (FN-EVT-07) ---
    track_lost_grace_s: int = 15
    """트랙 소실 후 `expired` 종결까지의 유예."""

    reassoc_window_s: int = 10
    """재결합을 시도하는 최대 경과 시간."""

    reassoc_max_speed_ms: float = 1.5
    """재결합 반경 산출용 최대 보행속도(m/s). **반경 = 이 값 × Δt**."""

    reassoc_radius_cap_m: float = 5.0
    """재결합 반경 상한."""

    # --- 거리 · 뎁스 (FN-DET-08 · 09 · 11) ---
    proximity_threshold_m: float = 2.0
    """근접 위반 판정 거리(즉시 경고 기준)."""

    vehicle_danger_radius_m: float = 3.0
    """지게차를 중심으로 따라다니는 동적 위험 영역 반경."""

    depth_band_m: tuple[float, float] = (2.0, 3.5)
    """뎁스 검증 회색지대."""

    depth_cache_ms: int = 500
    """동일 객체 쌍 뎁스 결과 재사용 시간."""

    screening_radius_m: float = 5.0
    """`nearby` 에 포함할 최대 거리."""

    min_confidence: float = 0.55
    """1단계 감지 최소 신뢰도."""

    # --- 2단계 분류 게이팅 (FN-DET-04 · 05) ---
    cls_cache_ms: int = 1000
    """분류 결과 캐시 유효기간. 클수록 GPU 부담 감소, 반응 지연 증가."""

    cls_min_crop_px: int = 64
    """최소 크롭 높이. 미달 시 분류 결과를 채택하지 않는다."""

    cls_min_conf: float = 0.60
    """최소 분류 신뢰도. 미달 시 결과를 채택하지 않는다."""

    # --- 클립 (FN-REC-03) ---
    clip_pre_roll_s: int = 10
    """이벤트 클립의 사전 구간(초)."""

    clip_post_roll_s: int = 10
    """이벤트 클립의 사후 구간(초)."""

    # --- 오버레이 시간 정합 (FN-UI-02) ---
    overlay_buffer_ms: int = 300
    """대시보드 오버레이 지연 버퍼. 영상–좌표 시간 정합용."""

    overlay_stale_ms: int = 1000
    """이 시간 이상 좌표 갱신이 없으면 박스를 흐리게 표시."""

    # --- 쓰러짐 판정 3조건 (FN-DET-10) ---
    fall_height_ratio_max: float = 0.5
    """높이 비율이 이 값 이하이면 쓰러짐 조건 ① 충족."""

    fall_axis_angle_min_deg: int = 55
    """주축 각도가 이 값 이상이면 조건 ② 충족."""

    fall_stillness_s: int = 5
    """정지 지속이 이 값 이상이면 조건 ③ 충족."""

    # --- 이상 탐지 (FN-AI-04) ---
    anomaly_sample_interval_min: int = 5
    """정상 풀 샘플링 주기(분)."""


class PolicyPatch(SpecModel):
    """`PATCH /policies` 요청. 지정한 키만 갱신한다. API명세서 §4.5"""

    confirm_duration_s: int | None = None
    resolve_duration_s: int | None = None
    cooldown_s: int | None = None
    resolve_window_s: int | None = None
    track_lost_grace_s: int | None = None
    reassoc_window_s: int | None = None
    reassoc_max_speed_ms: float | None = None
    reassoc_radius_cap_m: float | None = None
    proximity_threshold_m: float | None = None
    vehicle_danger_radius_m: float | None = None
    depth_band_m: tuple[float, float] | None = None
    depth_cache_ms: int | None = None
    screening_radius_m: float | None = None
    min_confidence: float | None = None
    cls_cache_ms: int | None = None
    cls_min_crop_px: int | None = None
    cls_min_conf: float | None = None
    clip_pre_roll_s: int | None = None
    clip_post_roll_s: int | None = None
    overlay_buffer_ms: int | None = None
    overlay_stale_ms: int | None = None
    fall_height_ratio_max: float | None = None
    fall_axis_angle_min_deg: int | None = None
    fall_stillness_s: int | None = None
    anomaly_sample_interval_min: int | None = None
