"""쓰러짐 3조건 — 기하와 시간. FN-DET-10 (API명세서 §6.4)

**합성 마스크로 검증한다.** 실제 세그멘테이션 결과가 없어도 세 게이지는 순수 기하라
좌표만 있으면 재현된다. 여기서는 **수학**을 잠그고, 다섯 가지 실제 자세(서 있음 ·
쭈그림 · 허리 굽힘 · 쓰러짐 · 일어남)의 판정표는 `sim/tests/test_masks.py` 가 잠근다.
"""

from __future__ import annotations

import math

import pytest

from aegis_vision import (
    FallThresholds,
    Homography,
    PointPx,
    ReferenceHeight,
    axis_angle_deg,
    expected_height_px,
    height_ratio,
    mask_shape,
    perspective_scale,
    posture_of,
)
from aegis_vision.posture import StillnessTracker

#: 개발용 카메라(`scripts/seed_cameras.py`)의 지면 격자 4점을 그대로 옮긴 것이다.
#:
#: **아무 4점이나 쓰면 안 된다.** 화면 안에서 작은 사다리꼴만 찍으면 거의 아핀에 가까운
#: 행렬이 나오고(소실선이 화면 밖 v ≈ 22 로 밀린다), 그런 기하에서는 원근 자체가 없어
#: 「가까울수록 크다」를 잴 수 없다. 그것은 구현이 아니라 캘리브레이션이 나쁜 경우다.
CALIBRATION = [
    ((0.1297, 0.8159), (3.0, 7.0)),
    ((0.8696, 0.8159), (9.0, 7.0)),
    ((0.7185, 0.6197), (9.0, 12.0)),
    ((0.2811, 0.6197), (3.0, 12.0)),
]
HOMOGRAPHY = Homography.from_correspondences(CALIBRATION)

#: 3조건 임계값. `policies` 기본값과 같다(§4.5).
THRESHOLDS = FallThresholds(height_ratio_max=0.5, axis_angle_min_deg=55.0, stillness_s=5.0)


def _bar(
    *,
    center: PointPx,
    length: float,
    thickness: float,
    angle_deg: float,
    count: int = 61,
) -> list[PointPx]:
    """길이 `length`, 두께 `thickness` 의 막대를 `angle_deg` 만큼 눕힌 합성 마스크.

    각도는 **화면 수직축 기준**이다 — 0 이면 서 있는 형상, 90 이면 누운 형상.
    정규화 좌표의 x 는 y 보다 16/9 배 길므로, 눕힐 때 그 몫을 되돌려 실제 화면에서
    의도한 각도가 나오게 한다.
    """
    aspect = 16.0 / 9.0
    radians = math.radians(angle_deg)
    ux, uy = math.sin(radians) / aspect, -math.cos(radians)
    nx, ny = math.cos(radians) / aspect, math.sin(radians)
    pixels: list[PointPx] = []
    for i in range(count):
        t = (i / (count - 1) - 0.5) * length
        for j in (-0.5, -0.25, 0.0, 0.25, 0.5):
            s = j * thickness
            pixels.append((center[0] + ux * t + nx * s, center[1] + uy * t + ny * s))
    return pixels


# --- ② 주축 각도 -----------------------------------------------------------


@pytest.mark.parametrize("angle", [0.0, 20.0, 45.0, 70.0, 90.0])
def test_axis_angle_recovers_the_angle_it_was_drawn_at(angle: float) -> None:
    """PCA 주축이 그린 각도를 되찾는다 — 0 은 수직, 90 은 수평."""
    pixels = _bar(center=(0.5, 0.6), length=0.3, thickness=0.02, angle_deg=angle)
    assert axis_angle_deg(pixels) == pytest.approx(angle, abs=1.5)


def test_axis_angle_never_exceeds_90() -> None:
    """90 을 넘겨 돌려주면 `≥ 임계` 비교가 서 있는 사람에게도 참이 되는 구간이 생긴다."""
    for angle in range(0, 360, 7):
        pixels = _bar(center=(0.5, 0.6), length=0.3, thickness=0.02, angle_deg=float(angle))
        assert 0.0 <= axis_angle_deg(pixels) <= 90.0


def test_a_single_point_has_no_direction() -> None:
    """점 하나로 「수직에 가깝다」고 답하면 서 있다고 주장하는 셈이다."""
    with pytest.raises(ValueError, match="2개 이상"):
        axis_angle_deg([(0.5, 0.5)])


# --- ① 높이 비율 -----------------------------------------------------------


def test_expected_height_grows_towards_the_camera() -> None:
    """원근 — 가까울수록(화면 아래일수록) 기대 높이가 크다."""
    reference = ReferenceHeight(px_height=0.42, at_m=(6.0, 9.0))
    near = expected_height_px((0.5, 0.92), homography=HOMOGRAPHY, reference=reference)
    far = expected_height_px((0.5, 0.66), homography=HOMOGRAPHY, reference=reference)
    assert near > far > 0.0


def test_a_standing_person_scores_near_one_at_any_distance() -> None:
    """★ 거리로 정규화하므로 원근에 무관하게 일관된 기준이 된다(FN-DET-10 ①).

    가까이 선 사람과 멀리 선 사람은 화면 높이가 크게 다르지만 `height_ratio` 는 둘 다
    1 근처여야 한다. 그러지 않으면 임계값 하나로 두 사람을 판정할 수 없다.
    """
    reference = ReferenceHeight(px_height=0.42, at_m=(6.0, 9.0))
    for foot_v in (0.92, 0.80, 0.68):
        expected = expected_height_px((0.5, foot_v), homography=HOMOGRAPHY, reference=reference)
        standing = _bar(
            center=(0.5, foot_v - expected / 2),
            length=expected,
            thickness=0.03,
            angle_deg=0.0,
        )
        ratio = height_ratio(
            mask_shape(standing),
            foot_point=(0.5, foot_v),
            homography=HOMOGRAPHY,
            reference=reference,
        )
        assert ratio == pytest.approx(1.0, abs=0.05)


def test_a_point_on_the_vanishing_line_is_refused() -> None:
    """소실선 위에는 대응하는 지면 점이 없다 — 큰 수를 돌려주면 그 값이 판정으로 흘러간다."""
    reference = ReferenceHeight(px_height=0.42, at_m=(6.0, 9.0))
    h20, h21, h22 = HOMOGRAPHY.to_rows()[2]
    on_the_line = -(h20 * 0.5 + h22) / h21
    assert perspective_scale(HOMOGRAPHY, (0.5, on_the_line)) < 1e-12
    with pytest.raises(ValueError, match="소실선"):
        expected_height_px((0.5, on_the_line), homography=HOMOGRAPHY, reference=reference)


def test_ground_projecting_the_whole_mask_inverts_the_result() -> None:
    """★ §6.4 「호모그래피 오용 주의」를 수치로 못박는다.

    마스크 **전체**를 지면에 투영해 길이를 재면 서 있는 사람이 누운 사람보다 길게
    나온다 — 상반신이 지면 평면 가정에 걸려 먼 지점으로 날아가기 때문이다. 쓰러짐
    판정이 정확히 거꾸로 돈다. 이 테스트는 그 역전을 **재현해서** 보여주고, 구현이
    화면 픽셀 높이를 쓰고 있다는 사실과 대조한다.
    """
    foot = (0.5, 0.86)
    standing = _bar(center=(0.5, 0.75), length=0.22, thickness=0.03, angle_deg=0.0)
    lying = _bar(center=(0.5, 0.855), length=0.22, thickness=0.03, angle_deg=90.0)

    def ground_length(pixels: list[tuple[float, float]]) -> float:
        points = [HOMOGRAPHY.to_ground(point) for point in pixels]
        ys = [point[1] for point in points]
        xs = [point[0] for point in points]
        return math.hypot(max(xs) - min(xs), max(ys) - min(ys))

    # 잘못된 방식 — 서 있는 쪽이 더 길게 나온다(역전).
    assert ground_length(standing) > ground_length(lying)

    # 구현이 쓰는 방식 — 화면 높이. 누운 쪽이 확실히 낮다.
    reference = ReferenceHeight(px_height=0.42, at_m=(6.0, 9.0))
    standing_ratio = height_ratio(
        mask_shape(standing), foot_point=foot, homography=HOMOGRAPHY, reference=reference
    )
    lying_ratio = height_ratio(
        mask_shape(lying), foot_point=foot, homography=HOMOGRAPHY, reference=reference
    )
    assert lying_ratio < standing_ratio


# --- ③ 정지 지속 -----------------------------------------------------------


def _tracker() -> StillnessTracker:
    return StillnessTracker(move_max=0.01, shape_change_max=0.05)


def test_stillness_accumulates_while_the_mask_holds_still() -> None:
    tracker = _tracker()
    shape = mask_shape(_bar(center=(0.5, 0.8), length=0.1, thickness=0.06, angle_deg=90.0))
    for step in range(1, 9):
        tracker.observe(step * 0.5, shape)
    assert tracker.stillness_s == pytest.approx(3.5)


def test_movement_resets_stillness_to_zero() -> None:
    """★ 움직였다는 것은 **관측된 사실**이다 — 게이팅 보류와 달리 동결이 아니라 초기화다."""
    tracker = _tracker()
    still = mask_shape(_bar(center=(0.5, 0.8), length=0.1, thickness=0.06, angle_deg=90.0))
    tracker.observe(0.0, still)
    tracker.observe(1.0, still)
    assert tracker.stillness_s == pytest.approx(1.0)
    moved = mask_shape(_bar(center=(0.6, 0.8), length=0.1, thickness=0.06, angle_deg=90.0))
    tracker.observe(2.0, moved)
    assert tracker.stillness_s == 0.0


def test_shape_change_alone_resets_even_when_the_centre_holds() -> None:
    """★ 제자리에서 팔을 휘두르는 사람 — 중심만 보면 정지로 잡힌다.

    §6.4 가 중심 이동량과 **형태 변화량**을 모두 요구하는 이유가 이것이다.
    """
    tracker = _tracker()
    narrow = mask_shape(_bar(center=(0.5, 0.8), length=0.2, thickness=0.02, angle_deg=0.0))
    wide = mask_shape(_bar(center=(0.5, 0.8), length=0.2, thickness=0.12, angle_deg=0.0))
    tracker.observe(0.0, narrow)
    tracker.observe(1.0, narrow)
    assert tracker.stillness_s > 0.0
    tracker.observe(2.0, wide)
    assert tracker.stillness_s == 0.0


def test_repeated_timestamps_do_not_grant_free_time() -> None:
    """중복 프레임으로 정지 시간이 공짜로 늘면 쓰러짐이 만들어진다."""
    tracker = _tracker()
    shape = mask_shape(_bar(center=(0.5, 0.8), length=0.1, thickness=0.06, angle_deg=90.0))
    tracker.observe(0.0, shape)
    tracker.observe(1.0, shape)
    tracker.observe(1.0, shape)
    tracker.observe(1.0, shape)
    assert tracker.stillness_s == pytest.approx(1.0)


def test_reset_drops_the_previous_persons_stillness() -> None:
    tracker = _tracker()
    shape = mask_shape(_bar(center=(0.5, 0.8), length=0.1, thickness=0.06, angle_deg=90.0))
    tracker.observe(0.0, shape)
    tracker.observe(6.0, shape)
    assert tracker.stillness_s == pytest.approx(6.0)
    tracker.reset()
    assert tracker.stillness_s == 0.0


# --- 세 조건의 결합 --------------------------------------------------------


def test_all_three_are_required() -> None:
    """하나라도 빠지면 `standing` 이다 — 「거의 쓰러짐」이라는 중간 상태를 만들지 않는다."""
    full = {"height_ratio": 0.3, "axis_angle_deg": 80.0, "stillness_s": 7.0}
    assert posture_of(**full, thresholds=THRESHOLDS).posture == "fallen"
    for key, value in [("height_ratio", 0.8), ("axis_angle_deg", 20.0), ("stillness_s", 1.0)]:
        assert posture_of(**{**full, key: value}, thresholds=THRESHOLDS).posture == "standing"


def test_boundary_values_count_as_met() -> None:
    """임계값 자체는 충족이다 — 정확히 5.0초를 미충족으로 보면 임계가 실제로는 5초 초과다."""
    reading = posture_of(
        height_ratio=0.5, axis_angle_deg=55.0, stillness_s=5.0, thresholds=THRESHOLDS
    )
    assert reading.posture == "fallen"
    assert reading.is_fall_candidate is True
