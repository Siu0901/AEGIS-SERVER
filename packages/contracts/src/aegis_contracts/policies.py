"""정책값(임계값·타이머) 전체.

출처: API명세서 §4.5 `GET /policies` / `PATCH /policies`

여기 있는 기본값은 **DB `policies` 테이블 시드의 원천**이다.
런타임에는 항상 DB 값을 읽고, 코드에 임계값을 하드코딩하지 않는다(CLAUDE.md 절대규칙 6).

**타입 방침**: 지속시간과 임계값은 전부 `float` 다. 튜닝은 정수 경계에서 멈추지 않기
때문이다 — 쓰러짐 정지 지속을 2.5초로, 주축 각도를 57.5도로 조일 수 있어야 한다.
비교 대상인 `stillness_s` · `axis_angle_deg`(§2.1) 자체가 `float` 이기도 하다.
`int` 로 남는 것은 셀 수 있는 값(`cls_min_crop_px` — 픽셀 수)뿐이다.
"""

from ._base import SpecModel

__all__ = ["Policies", "PolicyPatch"]


class Policies(SpecModel):
    """정책값 전량. API명세서 §4.5"""

    # --- 이벤트 상태머신 타이머 (기능명세서 §4.2) ---
    confirm_duration_s: float = 3.0
    """후보 → 확정 지속 조건."""

    resolve_duration_s: float = 10.0
    """위반 소멸 → 해소 판정 지속 조건."""

    cooldown_s: float = 30.0
    """재경고 최소 간격."""

    resolve_window_s: float = 300.0
    """이 시간 내 해소된 건만 시정률 분자에 포함."""

    # --- 트랙 소실 · 재결합 (FN-EVT-07) ---
    track_lost_grace_s: float = 15.0
    """트랙 소실 후 `expired` 종결까지의 유예."""

    reassoc_window_s: float = 10.0
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

    depth_cache_ms: float = 500.0
    """동일 객체 쌍 뎁스 결과 재사용 시간."""

    screening_radius_m: float = 5.0
    """`nearby` 에 포함할 최대 거리."""

    min_confidence: float = 0.55
    """1단계 감지 최소 신뢰도."""

    # --- 2단계 분류 게이팅 (FN-DET-04 · 05) ---
    cls_cache_ms: float = 1000.0
    """분류 결과 캐시 유효기간. 클수록 GPU 부담 감소, 반응 지연 증가."""

    cls_min_crop_px: int = 64
    """최소 크롭 높이(픽셀 수). 미달 시 분류 결과를 채택하지 않는다.

    **여기만 `int` 다** — 픽셀은 셀 수 있는 값이라 소수가 의미 없다.
    서브 스트림이 640×360 이므로 이 값을 넘으려면 사람이 프레임 높이의 약 18%
    이상을 차지해야 한다(기능명세서 FN-DET-04 카메라 설치 지침).
    """

    cls_min_conf: float = 0.60
    """최소 분류 신뢰도. 미달 시 결과를 채택하지 않는다."""

    # --- 클립 (FN-REC-03) ---
    clip_pre_roll_s: float = 10.0
    """이벤트 클립의 사전 구간(초)."""

    clip_post_roll_s: float = 10.0
    """이벤트 클립의 사후 구간(초)."""

    # --- 오버레이 시간 정합 (FN-UI-02) ---
    # 버퍼는 **재생 경로별로 나뉜다.** 라이브 영상 지연이 경로에 따라 한 자릿수 배
    # 차이가 나므로(M1 실측: WebRTC 0.27~0.34초 · LL-HLS 약 2.5초) 단일 값으로는
    # ±100ms 정합 목표를 맞출 수 없다. 클라이언트는 현재 재생 경로를 알고 있으므로
    # 그에 맞는 값을 골라 쓰고, 어느 경로로 재생 중인지 화면에 표시한다.
    overlay_buffer_webrtc_ms: float = 400.0
    """WebRTC(WHEP) 재생 시 오버레이 지연 버퍼. 실측 지연 0.27~0.34초 기준."""

    overlay_buffer_hls_ms: float = 2800.0
    """LL-HLS 폴백 재생 시 오버레이 지연 버퍼. 실측 지연 약 2.5초 기준."""

    overlay_stale_ms: float = 1000.0
    """이 시간 이상 좌표 갱신이 없으면 박스를 흐리게 표시."""

    # --- 쓰러짐 판정 3조건 (FN-DET-10) ---
    fall_height_ratio_max: float = 0.5
    """높이 비율이 이 값 이하이면 쓰러짐 조건 ① 충족."""

    fall_axis_angle_min_deg: float = 55.0
    """주축 각도가 이 값 이상이면 조건 ② 충족."""

    fall_stillness_s: float = 5.0
    """정지 지속이 이 값 이상이면 조건 ③ 충족. 오탐 억제의 핵심이라 미세 조정이 잦다."""

    # --- 이상 탐지 (FN-AI-04) ---
    anomaly_sample_interval_min: float = 5.0
    """정상 풀 샘플링 주기(분)."""


class PolicyPatch(SpecModel):
    """`PATCH /policies` 요청. 지정한 키만 갱신한다. API명세서 §4.5"""

    confirm_duration_s: float | None = None
    resolve_duration_s: float | None = None
    cooldown_s: float | None = None
    resolve_window_s: float | None = None
    track_lost_grace_s: float | None = None
    reassoc_window_s: float | None = None
    reassoc_max_speed_ms: float | None = None
    reassoc_radius_cap_m: float | None = None
    proximity_threshold_m: float | None = None
    vehicle_danger_radius_m: float | None = None
    depth_band_m: tuple[float, float] | None = None
    depth_cache_ms: float | None = None
    screening_radius_m: float | None = None
    min_confidence: float | None = None
    cls_cache_ms: float | None = None
    cls_min_crop_px: int | None = None
    cls_min_conf: float | None = None
    clip_pre_roll_s: float | None = None
    clip_post_roll_s: float | None = None
    overlay_buffer_webrtc_ms: float | None = None
    overlay_buffer_hls_ms: float | None = None
    overlay_stale_ms: float | None = None
    fall_height_ratio_max: float | None = None
    fall_axis_angle_min_deg: float | None = None
    fall_stillness_s: float | None = None
    anomaly_sample_interval_min: float | None = None
