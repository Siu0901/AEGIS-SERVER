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
    track_miss_timeout_ms: float = 1500.0
    """`frame` 에서 이 시간 이상 해당 `track_id` 가 관측되지 않으면 **소실로 간주**한다.

    엣지가 `track_lost` 를 보내지 못하고 끊긴 경우의 대비책이다(§4.5).
    **표시용 키인 `overlay_stale_ms` 와 혼용하지 않는다** — 그쪽은 "박스를 흐리게
    그릴 시점"이고 이쪽은 "이벤트를 `lost` 로 보낼 시점"이라 튜닝 이유가 다르다.
    """

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

    clip_extract_margin_s: float = 2.0
    """**세그먼트가 닫힌 뒤** 클립 추출까지의 여유(초). 기본 2.

    예약 실행 시각은 다음과 같다(기능명세서 §4.4).

    ```
    confirmed_at + clip_post_roll_s + rec_segment_seconds + clip_extract_margin_s
    ```

    **세그먼트 길이는 이 값에 포함되지 않는다.** REC 은 벽시계 격자로 세그먼트를 닫으므로
    (`-segment_atclocktime`) `confirmed_at + post_roll` 시점을 담은 파일은 그때 아직
    기록 중이고, 닫히기까지 최대 세그먼트 길이가 더 걸린다. 그 항은 **REC 의
    `GET /status`(§4.7)가 보고하는 값**을 서버가 읽어 더한다 — 양쪽에 상수로 두면 REC
    설정을 바꿨을 때 서버가 모른 채 잘못된 시각에 추출한다.
    """

    # --- 경고 (FN-ALM-02 · 05) ---
    alert_duration_s: int = 5
    """경광등·부저 지속 시간(초). §3 `AlertCommand.duration_s` 로 그대로 나간다.

    **정책값 중 두 번째 `int` 다**(다른 하나는 `cls_min_crop_px`). §3 이 `duration_s` 를
    `int` 로 못박았으므로 여기서 `float` 로 두면 장치로 나가는 순간 반올림되고, 화면에서
    조정한 값과 실제 동작이 갈린다. 서버 설정(`ALERT_DURATION_S`)에 있던 것을 명세서가
    정책 키로 올렸다 — 현장에서 조정하는 값이라 배포가 아니라 설정이어야 한다.
    """

    mute_default_duration_s: float = 900.0
    """경고 일시중지 기본 지속시간(초). `POST /alerts/mute` 가 `minutes` 를 생략했을 때 쓴다.

    **기한 없는 일시중지는 없다.** 요청이 길이를 주지 않아도 이 값이 붙는다 —
    꺼둔 것을 잊는 순간 감시가 조용히 멎는 상태를 만들지 않기 위해서다.
    """

    # --- 차량 탑승자 판별 (FN-DET-13) ---
    occupancy_overlap_min: float = 0.35
    """사람 마스크가 차량 마스크와 겹치는 최소 비율(API명세서 §4.5).

    분모는 **사람 넓이**다. 차량이 훨씬 크므로 합집합으로 나누면 탑승 중이어도 값이
    0 에 가깝다.
    """

    occupancy_confirm_s: float = 1.5
    """탑승 확정까지의 지속 시간."""

    occupancy_release_s: float = 3.0
    """하차 확정까지의 지속 시간. **확정보다 길다** — 히스테리시스가 없으면 운전자가
    몸을 기울일 때마다 탑승·하차가 반복되고 그때마다 근접 위반이 생겼다 사라진다.
    """

    # --- 진단 표시 ---
    overlay_mask: bool = False
    """마스크 윤곽(`contour`)을 `frame`·`overlay` 에 싣는다(API명세서 §2.1 · §4.5).

    ★ **기본은 꺼짐이다.** 켜면 객체마다 좌표 24쌍이 매 프레임 더 나간다 — 카메라 2대에
      객체 5개면 초당 수천 개다. 감지가 형태를 제대로 잡는지 눈으로 볼 때만 켠다.

    ★ **판정에는 쓰이지 않는다.** 이 값이 켜지든 꺼지든 확정·해소·거리 판정은 동일하다.
      엣지가 정책을 주기적으로 읽으므로 **엣지를 재시작하지 않고** 토글된다.
    """

    # --- 오버레이 시간 정합 (FN-UI-02) ---
    # 버퍼는 **재생 경로별로 나뉜다.** 라이브 영상 지연이 경로에 따라 한 자릿수 배
    # 차이가 나므로(M1 실측: WebRTC 0.27~0.34초 · LL-HLS 약 2.5초) 단일 값으로는
    # ±100ms 정합 목표를 맞출 수 없다. 클라이언트는 현재 재생 경로를 알고 있으므로
    # 그에 맞는 값을 골라 쓰고, 어느 경로로 재생 중인지 화면에 표시한다.
    overlay_buffer_webrtc_ms: float = 300.0
    """WebRTC(WHEP) 재생 시 오버레이 지연 버퍼. **영상 지연 실측 중앙값(약 305ms)에 맞춘다.**

    값이 크면 박스가 뒤처지고 작으면 앞선다(§4.5). 400 이던 것을 실측에 맞춰 내렸다.
    """

    overlay_buffer_hls_ms: float = 2800.0
    """LL-HLS 폴백 재생 시 오버레이 지연 버퍼. 실측 지연 약 2.5초 기준."""

    overlay_stale_ms: float = 1000.0
    """이 시간 이상 좌표 갱신이 없으면 박스를 흐리게 표시.

    **표시 전용이다.** 소실 판정에는 `track_miss_timeout_ms` 를 쓴다(§4.5).
    """

    # --- 쓰러짐 판정 3조건 (FN-DET-10) ---
    fall_height_ratio_max: float = 0.5
    """높이 비율이 이 값 이하이면 쓰러짐 조건 ① 충족."""

    fall_axis_angle_min_deg: float = 55.0
    """주축 각도가 이 값 이상이면 조건 ② 충족."""

    fall_stillness_s: float = 5.0
    """정지 지속이 이 값 이상이면 조건 ③ 충족. 오탐 억제의 핵심이라 미세 조정이 잦다."""

    stillness_move_px: float = 0.008
    """**무엇을 정지로 볼 것인가** — 이 값(정규화 픽셀) 이하 이동이면 정지다(§4.5).

    ★ 명세서가 `edge/config.yaml` 에서 정책 테이블로 **승격**한 키다. 정지 판정 임계는
    오탐 억제의 핵심 조건이고 현장 튜닝이 잦은데, 장비 설정 파일에 있으면 조정할 때마다
    엣지에 접속해 파일을 고치고 프로세스를 다시 띄워야 한다 — 그건 배포이지 설정이 아니다.
    """

    stillness_window_s: float = 1.0
    """정지 여부를 평가하는 **이동 평균 창**(초).

    프레임 간 차이만 보면 8fps 에서 한 프레임의 흔들림이 곧 「움직였다」가 되어 정지
    시간이 계속 0으로 되돌아간다. 창을 두면 그 잡음이 평균에 묻힌다 — 대신 창보다
    짧은 움직임은 보이지 않으므로, `stillness_move_px` 와 **함께** 조정해야 한다.
    """

    stillness_shape_change_max: float = 0.15
    """마스크 **형태** 변화가 이 값 이하일 때만 정지로 본다(§4.5).

    ★ `edge/config.yaml` 에서 정책 테이블로 **승격**된 키다. 위치 이동만 보면 제자리에서
    몸을 크게 움직이는 사람이 「정지」로 잡혀 쓰러짐 조건 ③이 성립한다 — 형태 변화를
    함께 봐야 그 오탐이 걸러진다. 나머지 두 정지 임계와 **함께** 조정해야 하므로 같은
    자리에 둔다.
    """

    # --- 이상 탐지 (FN-AI-04) ---
    anomaly_sample_interval_min: float = 5.0
    """정상 풀 샘플링 주기(분)."""

    anomaly_threshold: float = 0.35
    """이상 점수가 이 값을 넘으면 플래그(§6.8).

    ★ 조명·현장 특성에 좌우되는 **현장 조정 대상**이라 코드 상수로 두지 않는다.
    낮추면 조명 변화가 곧 이상이 되고, 올리면 진짜 이상이 묻힌다.
    """

    anomaly_knn_k: int = 5
    """k-최근접 개수. 풀에서 가장 가까운 이 개수의 평균 거리로 점수를 낸다."""

    anomaly_min_pool: int = 12
    """이 개수 미만이면 **판정하지 않는다.**

    풀이 얇을 때의 큰 거리는 「이상」이 아니라 「모른다」다. `anomaly_knn_k` 보다 넉넉해야
    한 장의 이상치가 평균을 끌고 다니지 않는다.
    """

    anomaly_time_bucket_h: int = 3
    """시간대 버킷 크기(시간). 주야 조명 차이를 흡수한다.

    잘게 나눌수록 조명이 균질해지지만 풀이 `anomaly_min_pool` 에 도달하지 못한다.
    """

    # --- 시각 동기화 (FN-SYS-02) ---
    clock_offset_warn_ms: float = 100.0
    """엣지 시계 오차가 이 값을 넘으면 경고(§4.6).

    ★ 시각이 어긋난 상태에서 잘라낸 클립은 **정상적으로 생성되고 재생되지만 다른
    구간을 담는다.** 사람이 열어보기 전까지 드러나지 않으므로 화면에 상시 노출한다.
    """

    # --- 챗봇 (FN-AI-08) ---
    assistant_history_turns: int = 8
    """세션 하나가 기억하는 최근 턴 수(§4.4).

    이력이 없으면 후속 질문이 독립 질의로 처리되어 「이번 주 위반 몇 건」 다음의
    「각각 무슨 위반이야?」가 장면 검색으로 샌다. 넉넉히 두면 프롬프트가 길어지고
    오래된 화제가 답변을 끌고 간다.
    """


class PolicyPatch(SpecModel):
    """`PATCH /policies` 요청. 지정한 키만 갱신한다. API명세서 §4.5"""

    confirm_duration_s: float | None = None
    resolve_duration_s: float | None = None
    cooldown_s: float | None = None
    resolve_window_s: float | None = None
    track_miss_timeout_ms: float | None = None
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
    clip_extract_margin_s: float | None = None
    alert_duration_s: int | None = None
    mute_default_duration_s: float | None = None
    occupancy_overlap_min: float | None = None
    occupancy_confirm_s: float | None = None
    occupancy_release_s: float | None = None
    overlay_mask: bool | None = None
    overlay_buffer_webrtc_ms: float | None = None
    overlay_buffer_hls_ms: float | None = None
    overlay_stale_ms: float | None = None
    fall_height_ratio_max: float | None = None
    fall_axis_angle_min_deg: float | None = None
    fall_stillness_s: float | None = None
    stillness_move_px: float | None = None
    stillness_window_s: float | None = None
    stillness_shape_change_max: float | None = None
    anomaly_sample_interval_min: float | None = None
    anomaly_threshold: float | None = None
    anomaly_knn_k: int | None = None
    anomaly_min_pool: int | None = None
    anomaly_time_bucket_h: int | None = None
    clock_offset_warn_ms: float | None = None
    assistant_history_turns: int | None = None
