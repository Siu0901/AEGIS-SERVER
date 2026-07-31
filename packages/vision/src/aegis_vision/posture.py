"""자세 판정 — 쓰러졌는가. FN-DET-10 (API명세서 §6.4)

출처: 기능명세서 §4.1 FN-DET-10 · API명세서 §6.4 (`posture`) · §2.1 (`height_ratio` ·
`axis_angle_deg` · `stillness_s`)

**학습 없이 기하 정보와 시간 조건으로 판정한다.** 세 조건을 **모두** 충족해야
`fallen` 이다.

| 조건 | 산출 | 무엇을 거르는가 |
|---|---|---|
| ① `height_ratio` ≤ 임계 | 마스크 화면 높이 ÷ 그 거리에서의 기대 높이 | 서 있는 사람 |
| ② `axis_angle_deg` ≥ 임계 | 마스크 PCA 주축과 화면 수직축의 각도 | 세로로 선 형상 |
| ③ `stillness_s` ≥ 임계 | 중심 이동량·형태 변화량이 임계 이하인 지속 시간 | **쭈그림·허리 굽힘** |

★ **세 번째가 오탐 억제의 핵심이다.** 쭈그려 앉기와 허리 굽혀 작업은 ①②를 통과할 수
있다 — 실제로 낮고, 실제로 기울어져 있다. 다르게 만드는 것은 **계속 움직인다**는
사실뿐이다. 상체·팔이 멈추지 않으므로 ③에서 걸러진다(§6.4 「오탐 억제」).

---

**★ 호모그래피 오용 주의**(§6.4 · CLAUDE.md 절대규칙 4).

사람 마스크 **전체를 지면으로 투영해 크기를 재지 않는다.** 호모그래피는 지면 평면
대 평면 변환이라, 지면에서 떨어진 점(서 있는 사람의 머리·상반신)은 **광선이 지면과
만나는 훨씬 먼 지점**으로 날아간다. 그 결과 서 있는 사람이 누운 사람보다 길게
나오는 **역전 현상**이 생긴다 — 쓰러짐 판정이 정확히 거꾸로 돈다.

그래서 ①은 **화면 픽셀 높이**로 재고, 원근 정규화는 접지점 한 점의 원근 배율로만 한다.
②도 마스크의 **픽셀 좌표**에 PCA 를 적용한다.

`test_ground_projecting_the_whole_mask_inverts_the_result` 가 이 역전을 재현해서
잠근다 — 잘못된 방식과 구현이 쓰는 방식을 같은 마스크로 나란히 재는 테스트다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from aegis_vision.homography import Homography, PointM, PointPx

__all__ = [
    "FallThresholds",
    "MaskShape",
    "PostureReading",
    "ReferenceHeight",
    "StillnessTracker",
    "axis_angle_deg",
    "expected_height_px",
    "height_ratio",
    "mask_shape",
    "perspective_scale",
    "posture_of",
]


@dataclass(frozen=True, slots=True)
class MaskShape:
    """마스크 하나의 기하 요약. **픽셀 좌표계에서 잰 값들이다.**

    마스크 픽셀 전체를 들고 다니지 않는 이유는 프레임마다 수천 점이 오가기 때문이다.
    자세 판정에 필요한 것은 높이 · 주축 각도 · 중심 · 면적 넷뿐이다.
    """

    height: float
    """화면상 높이(정규화 픽셀). **지면 투영 높이가 아니다** — 모듈 docstring 참고."""
    width: float
    angle_deg: float
    """PCA 주축과 화면 수직축의 각도(도). 0 이면 수직, 90 이면 수평."""
    center: PointPx
    area: float
    """마스크 픽셀 수를 정규화 면적으로 옮긴 값. 형태 변화량의 분모다."""


@dataclass(frozen=True, slots=True)
class FallThresholds:
    """쓰러짐 3조건의 임계값. 전부 `policies` 에서 온다(절대규칙 6).

    **기본값을 두지 않는다.** 여기 숫자를 적으면 정책 조회에 실패한 경로가 코드 상수로
    판정하게 되고, 설정 화면이 보여주는 값과 실제 기준이 갈린다.
    """

    height_ratio_max: float
    """`fall_height_ratio_max`(기본 0.5). 이하이면 조건 ① 충족."""
    axis_angle_min_deg: float
    """`fall_axis_angle_min_deg`(기본 55). 이상이면 조건 ② 충족."""
    stillness_s: float
    """`fall_stillness_s`(기본 5.0). 이상이면 조건 ③ 충족."""


@dataclass(frozen=True, slots=True)
class PostureReading:
    """한 프레임의 자세 관측. 세 게이지가 `frame.objects[]`(§2.1)로 그대로 나간다."""

    posture: str
    """`standing` / `fallen` / `unknown`(§2.1)."""
    height_ratio: float
    axis_angle_deg: float
    stillness_s: float

    @property
    def is_fall_candidate(self) -> bool:
        """뎁스 트리거 D 이자 `fall` 후보 여부(§6.6). 세 조건을 모두 통과했다는 뜻이다."""
        return self.posture == "fallen"


def mask_shape(pixels: Sequence[PointPx]) -> MaskShape:
    """마스크 픽셀에서 기하 요약을 만든다.

    `pixels` 는 **정규화 픽셀 좌표**의 마스크 점들이다. 높이·너비는 축 정렬 범위이고,
    각도는 2차 모멘트의 주축(PCA)이다.
    """
    if not pixels:
        msg = "마스크 픽셀이 비어 있다 — 자세를 잴 수 없다"
        raise ValueError(msg)
    xs = [float(point[0]) for point in pixels]
    ys = [float(point[1]) for point in pixels]
    count = float(len(pixels))
    center = (sum(xs) / count, sum(ys) / count)
    return MaskShape(
        height=max(ys) - min(ys),
        width=max(xs) - min(xs),
        angle_deg=axis_angle_deg(pixels),
        center=center,
        # 정규화 좌표계에서 픽셀 하나의 면적을 알 수 없으므로 **점 개수**를 면적 대용으로
        # 쓴다. 형태 변화량은 비율로만 보므로 단위가 무엇이든 상관없다.
        area=count,
    )


def axis_angle_deg(pixels: Sequence[PointPx]) -> float:
    """마스크 주축과 화면 **수직축**의 각도(도). API명세서 §6.4 `axis_angle_deg`

    공분산 행렬의 최대 고유벡터가 주축이다. 2×2 대칭 행렬이라 닫힌 해가 있어서
    반복법이 필요 없다 — 고유값 문제를 푸는 코드는 `homography` 한 곳으로 족하다.

    돌려주는 값은 **0~90**이다. 주축의 부호(위/아래)는 자세와 무관하고, 90을 넘겨
    돌려주면 `≥ 임계` 비교가 서 있는 사람에게도 참이 되는 구간이 생긴다.

    **정규화 좌표의 x 와 y 는 같은 척도가 아니다**(16:9 이므로 x 1.0 이 y 1.0 보다
    16/9 배 길다). 각도를 재기 전에 x 를 화면비로 되돌려 실제 화면 비율에서 계산한다 —
    그러지 않으면 누운 사람의 주축이 실제보다 수직에 가깝게 나온다.
    """
    if len(pixels) < 2:
        # 점 하나로는 방향이 없다. 「수직에 가깝다」로 답하면 서 있다고 주장하는 셈이라
        # 판정을 만들어내지 않도록 0 이 아니라 예외다.
        msg = f"주축을 구하려면 점이 2개 이상이어야 한다: {len(pixels)}"
        raise ValueError(msg)

    xs = [float(point[0]) * _ASPECT for point in pixels]
    ys = [float(point[1]) for point in pixels]
    count = float(len(pixels))
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    dxs = [x - mean_x for x in xs]
    dys = [y - mean_y for y in ys]
    cxx = sum(dx * dx for dx in dxs) / count
    cyy = sum(dy * dy for dy in dys) / count
    cxy = sum(dx * dy for dx, dy in zip(dxs, dys, strict=True)) / count

    # 최대 고유벡터의 방향. `atan2(2·cxy, cxx − cyy) / 2` 가 x축 기준 주축 각도다.
    axis_from_x = 0.5 * math.atan2(2.0 * cxy, cxx - cyy)
    # 수직축 기준으로 옮기고 0~90 으로 접는다.
    from_vertical = abs(math.degrees(axis_from_x)) - 90.0
    return round(abs(from_vertical), 4)


#: 정규화 좌표의 가로세로 척도 차이. 카메라 메인·서브가 모두 16:9 다(CLAUDE.md 핵심 수치).
#:
#: 튜닝값이 아니라 **좌표계의 성질**이므로 여기 둔다. 화면비가 바뀌면 정규화 좌표가
#: 메인·서브 사이에서 대응하지 않게 되므로, 그때는 이 상수가 아니라 카메라 설정이 틀린 것이다.
_ASPECT = 16.0 / 9.0


@dataclass(frozen=True, slots=True)
class ReferenceHeight:
    """기준 인물 1회 입력. `cameras.ref_height_px_at_m`(§4.5 `reference_person`).

    ★ **모형 시연에서도 실제 작업자 신장(약 1.7m)에 해당한다고 보고 입력한다**
    (기능명세서 §4.7 FN-CFG-01). 모형 축척으로 넣으면 기대 높이 곡선이 통째로 어긋나
    `fall_height_ratio_max` 를 다시 정해야 한다.
    """

    px_height: float
    """그 사람의 화면상 높이(정규화 픽셀)."""
    at_m: PointM
    """그 사람이 서 있던 지면 좌표(m)."""


def perspective_scale(homography: Homography, point: PointPx) -> float:
    """그 화면 위치의 **원근 배율** — 호모그래피 동차좌표의 `W`.

    `W = h20·u + h21·v + h22` 이고, `W = 0` 인 선이 지면 무한원점의 상(소실선)이다.
    지면 점까지의 거리는 `1/W` 에 비례하므로 **화면상 크기는 `W` 에 비례**한다.

    소실선까지의 세로 거리 `(v − v_소실선)` 을 쓰는 고전적 방식과 같은 값이다 —
    `W = h21·(v − v_소실선)` 이므로 비율을 볼 때 `h21` 이 소거된다. `W` 를 직접 쓰면
    `h21 = 0` 인 기하(정면에서 본 지면)에서 나눗셈이 터지는 일이 없고, 소실선이 화면
    위에 있든 아래에 있든 부호를 따질 필요도 없다.

    `Homography` 가 지면 좌표를 거부하는 기준(`W ≈ 0`)과 같은 값이므로, 여기서 통과한
    점은 `to_ground` 도 통과한다.
    """
    h20, h21, h22 = homography.to_rows()[2]
    return abs(h20 * float(point[0]) + h21 * float(point[1]) + h22)


def expected_height_px(
    foot_point: PointPx,
    *,
    homography: Homography,
    reference: ReferenceHeight,
) -> float:
    """그 위치에 **서 있는** 사람이 화면에 차지할 기대 높이(정규화 픽셀). API명세서 §6.4

    지면 위에 선 같은 실제 높이의 물체는 화면상 높이가 **원근 배율에 비례**한다. 기준
    인물 한 명만 입력하면 비례상수가 정해져 곡선 전체가 결정된다.

    **거리를 직접 쓰지 않는 이유**: 「거리에 반비례」로 계산하려면 카메라의 지면 위치가
    필요한데 `cameras` 테이블에 그런 칸이 없다(기능명세서 §6). 원근 배율은 이미 저장된
    호모그래피 하나에서 나오므로 새 입력을 요구하지 않는다.
    """
    if reference.px_height <= 0.0:
        msg = f"기준 인물 높이는 0보다 커야 한다: {reference.px_height!r}"
        raise ValueError(msg)

    at_reference = perspective_scale(homography, homography.to_pixel(reference.at_m))
    at_target = perspective_scale(homography, foot_point)
    if at_reference <= _SCALE_EPSILON or at_target <= _SCALE_EPSILON:
        # 소실선 위(또는 그 근처)의 점이다 — 대응하는 지면 점이 없다.
        msg = f"접지점이 소실선 위에 있다 — 지면 위의 점이 아니다: {foot_point!r}"
        raise ValueError(msg)
    return reference.px_height * (at_target / at_reference)


#: 원근 배율이 이보다 작으면 소실선 위로 본다. `Homography._W_EPSILON` 과 같은 뜻이다.
_SCALE_EPSILON = 1e-9


def height_ratio(
    shape: MaskShape,
    *,
    foot_point: PointPx,
    homography: Homography,
    reference: ReferenceHeight,
) -> float:
    """조건 ① — 마스크 **화면** 높이 ÷ 그 위치에서의 기대 높이. API명세서 §6.4

    분자도 분모도 화면 픽셀이다. 마스크를 지면으로 투영해 재지 않는 이유는 모듈
    docstring 에 있다 — 그렇게 하면 결과가 역전된다.

    돌려주는 값이 1.0 근처면 서 있는 것이고, 임계값(기본 0.5) 이하면 조건 ① 충족이다.
    """
    expected = expected_height_px(foot_point, homography=homography, reference=reference)
    return round(shape.height / expected, 4)


class StillnessTracker:
    """조건 ③ — 중심 이동량과 형태 변화량이 모두 임계 이하인 지속 시간. API명세서 §6.4

    ★ **오탐 억제의 핵심이다.** 쭈그려 앉기·허리 굽힘은 ①②를 통과할 수 있으나
    상체·팔이 계속 움직이므로 여기서 걸러진다.

    **형태 변화량을 함께 보는 이유**: 중심만 보면 제자리에서 팔을 휘두르는 사람이
    정지로 잡힌다. 반대로 형태만 보면 자세를 유지한 채 미끄러지듯 이동하는 것을 놓친다.
    §6.4 가 둘을 **모두** 요구한다.

    시간은 부르는 쪽이 `Clock` 에서 얻어 넘긴다(CLAUDE.md 절대규칙 1) — 이 패키지는
    시계를 읽지 않는다.
    """

    def __init__(self, *, move_max: float, shape_change_max: float) -> None:
        """
        Args:
            move_max: 중심 이동 허용치(정규화 픽셀 / 초).
            shape_change_max: 형태 변화 허용 비율(면적·종횡비 변화 / 초).

        **기본값을 두지 않는다.** 카메라 화각과 설치 높이에 따라 달라지는 튜닝값이라
        `edge/config.yaml` 소관이다(절대규칙 6).
        """
        if move_max <= 0.0 or shape_change_max <= 0.0:
            msg = f"임계는 0보다 커야 한다: move={move_max!r} shape={shape_change_max!r}"
            raise ValueError(msg)
        self._move_max = move_max
        self._shape_change_max = shape_change_max
        self._previous: tuple[float, MaskShape] | None = None
        self._still_s = 0.0

    @property
    def stillness_s(self) -> float:
        """지금까지 이어진 정지 시간(초). `frame.objects[].stillness_s`(§2.1)."""
        return round(self._still_s, 3)

    def observe(self, at_s: float, shape: MaskShape) -> float:
        """관측 한 프레임. 갱신된 `stillness_s` 를 돌려준다.

        `at_s` 는 단조 증가하는 초 단위 시각(`Clock.monotonic`)이다.

        **움직이면 0으로 되돌린다.** 여기서 동결(값 유지)하지 않는 이유는, 게이팅
        보류(§6.3)와 달리 「움직였다」는 것이 관측된 사실이기 때문이다 — 관측하지 못한
        것과 움직인 것은 다르다.
        """
        previous = self._previous
        self._previous = (at_s, shape)
        if previous is None:
            self._still_s = 0.0
            return self.stillness_s

        last_at, last_shape = previous
        elapsed = at_s - last_at
        if elapsed <= 0.0:
            # 같은 시각이 두 번 오면 시간을 더하지 않는다. 재생 배속이나 중복 프레임에서
            # 정지 시간이 공짜로 늘어나면 쓰러짐이 만들어진다.
            return self.stillness_s

        moved = math.hypot(
            shape.center[0] - last_shape.center[0],
            shape.center[1] - last_shape.center[1],
        )
        changed = _shape_change(last_shape, shape)
        if moved / elapsed <= self._move_max and changed / elapsed <= self._shape_change_max:
            self._still_s += elapsed
        else:
            self._still_s = 0.0
        return self.stillness_s

    def reset(self) -> None:
        """트랙이 끊겼다 — 지금까지의 정지 시간은 이 사람의 것이 아니다."""
        self._previous = None
        self._still_s = 0.0


def _shape_change(before: MaskShape, after: MaskShape) -> float:
    """형태 변화량 — 면적 변화율과 종횡비 변화율 중 큰 쪽.

    두 지표를 더하지 않고 **최댓값**을 쓴다. 하나만 크게 변해도 형태가 변한 것이며,
    평균을 내면 팔만 움직이는 동작이 절반으로 희석된다.
    """
    area_change = abs(after.area - before.area) / max(before.area, 1e-9)
    ratio_before = before.width / max(before.height, 1e-9)
    ratio_after = after.width / max(after.height, 1e-9)
    ratio_change = abs(ratio_after - ratio_before) / max(ratio_before, 1e-9)
    return max(area_change, ratio_change)


def posture_of(
    *,
    height_ratio: float,
    axis_angle_deg: float,
    stillness_s: float,
    thresholds: FallThresholds,
) -> PostureReading:
    """세 게이지 → `posture`. FN-DET-10 · API명세서 §6.4

    **세 조건을 모두 충족해야** `fallen` 이다. 하나라도 빠지면 `standing` 이다 —
    「거의 쓰러짐」이라는 중간 상태를 만들지 않는다. 만들면 그 값이 곧 화면에 나가고,
    그것을 보고 대응할지 말지를 사람이 매번 판단해야 한다.

    `unknown`(§2.1)은 여기서 나오지 않는다. 마스크가 없어 게이지를 잴 수 없는
    상황이며, 부르는 쪽이 이 함수를 부르지 못하는 경우다.
    """
    fallen = (
        height_ratio <= thresholds.height_ratio_max
        and axis_angle_deg >= thresholds.axis_angle_min_deg
        and stillness_s >= thresholds.stillness_s
    )
    return PostureReading(
        posture="fallen" if fallen else "standing",
        height_ratio=round(height_ratio, 4),
        axis_angle_deg=round(axis_angle_deg, 4),
        stillness_s=round(stillness_s, 3),
    )
