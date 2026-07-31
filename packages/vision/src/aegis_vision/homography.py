"""호모그래피 — 실측 4점으로 픽셀 ↔ 지면 좌표를 잇는다. FN-DET-06 · FN-CFG-01

출처: API명세서 §6.2 (`foot_point_m` 산출법) · §4.5 (`POST /cameras/{cam_id}/calibration`)

```
[X', Y', W] = H · [u, v, 1]ᵀ
실좌표 = (X'/W, Y'/W)   ← 단위 m
```

**입력은 정규화 픽셀 좌표(0.0~1.0)다.** 해상도로 나눈 비율이므로 640p 서브에서 산출한
좌표와 1080p 메인 화면의 좌표가 같은 값이고(§1.2), 그래서 이 행렬 하나가 두 스트림에
모두 쓰인다. 픽셀 단위(640·1920)를 넣으면 스케일이 통째로 어긋난다.

**의존성이 없다.** `numpy` 도 쓰지 않는다 — 이 패키지는 젯슨·서버·시뮬레이터가 함께
쓰는 순수 계산이고, 4~8개 대응점의 최소제곱과 프레임당 수십 회의 점 변환에 배열
라이브러리가 필요하지 않다. 대신 수치 안정성은 직접 챙긴다(아래 `_normalize`).

**호모그래피를 오용하지 않는다.** 지면 평면 위의 점(접지점·지게차 접점)만 변환한다.
서 있는 사람의 머리나 마스크 전체를 투영하면 지면 가정이 깨져 상반신이 먼 지점으로
날아간다(기능명세서 FN-DET-10).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

__all__ = [
    "MIN_CORRESPONDENCES",
    "Bbox",
    "CalibrationError",
    "Correspondence",
    "Homography",
    "Matrix3",
    "PointM",
    "PointPx",
]

#: 정규화 픽셀 좌표(0.0~1.0). 접미사 없는 좌표는 전부 이것이다(API명세서 §1.2).
PointPx = tuple[float, float]

#: 지면 실좌표(m). 접미사 `_m` 이 붙은 좌표는 전부 이것이다.
PointM = tuple[float, float]

#: 정규화 경계상자 `[x1, y1, x2, y2]`(API명세서 §2.1). 좌상단·우하단 코너다.
Bbox = tuple[float, float, float, float]

#: 3×3 행렬. 계약(`aegis_contracts.Homography`)은 `list[list[float]]` 로 주고받는다.
Matrix3 = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]

#: 대응점 한 쌍 — (화면에서 클릭한 정규화 좌표, 줄자로 잰 지면 좌표).
Correspondence = tuple[PointPx, PointM]

#: 호모그래피 자유도는 8이므로 대응점이 최소 4쌍 필요하다(쌍마다 식 2개).
MIN_CORRESPONDENCES = 4

#: 동차좌표의 W 가 이보다 작으면 그 점은 지평선 위(또는 뒤)라 지면 좌표가 없다.
_W_EPSILON = 1e-9

#: 야코비 회전의 수렴 기준과 상한. 9×9 대칭 행렬이라 보통 10회 안쪽에서 끝난다.
_JACOBI_TOLERANCE = 1e-14
_JACOBI_MAX_SWEEPS = 100


class CalibrationError(ValueError):
    """대응점으로 행렬을 만들 수 없다 — 점이 모자라거나 한 직선 위에 있다.

    **조용히 단위행렬을 돌려주지 않는다.** 잘못된 캘리브레이션은 모든 거리와 구역
    판정을 조용히 틀리게 만들고, 그 오류는 화면 어디에도 드러나지 않는다.
    """


@dataclass(frozen=True, slots=True)
class Homography:
    """픽셀 → 지면 변환 행렬 하나. 카메라 한 대에 하나씩 있다.

    **불변이다.** 카메라를 물리적으로 움직이면 새로 만든다(§6.2) — 기존 객체를 고쳐
    쓰면 그 순간 진행 중인 판정이 서로 다른 좌표계에서 계산된다.
    """

    matrix: Matrix3

    # -- 생성 --------------------------------------------------------------

    @classmethod
    def from_matrix(cls, rows: Sequence[Sequence[float]]) -> Self:
        """저장된 3×3 행렬(DB `cameras.homography`)에서 되살린다."""
        if len(rows) != 3 or any(len(row) != 3 for row in rows):
            msg = f"호모그래피는 3×3 이어야 한다: {rows!r}"
            raise CalibrationError(msg)
        matrix = tuple(tuple(float(value) for value in row) for row in rows)
        if _determinant(matrix) == 0.0:  # type: ignore[arg-type]
            msg = "행렬식이 0인 호모그래피는 역변환이 없다"
            raise CalibrationError(msg)
        return cls(matrix=matrix)  # type: ignore[arg-type]

    @classmethod
    def from_correspondences(cls, correspondences: Sequence[Correspondence]) -> Self:
        """실측 대응점들로 행렬을 구한다(DLT · 최소제곱). FN-CFG-01

        4쌍이면 정확해, 5쌍 이상이면 재투영 오차를 최소화하는 해다. 현장에서는 줄자
        오차가 섞이므로 점을 더 찍을수록 좋아진다.

        **좌표를 정규화하고 푼다(Hartley).** 정규화 픽셀(0~1)과 미터(0~15)는 스케일이
        한 자릿수 이상 차이나서, 그대로 풀면 계수 행렬의 조건수가 나빠져 해가 흔들린다.
        실제로 정규화 없이 풀었을 때 같은 데이터에서 잔차가 0.1m 대에서 1.6m 대로
        커지는 것을 확인했다. 중심을 원점으로 옮기고 평균 거리를 √2 로 맞춘 뒤 풀고,
        얻은 행렬을 원래 좌표계로 되돌린다.
        """
        pairs = [
            ((float(px[0]), float(px[1])), (float(m[0]), float(m[1]))) for px, m in correspondences
        ]
        if len(pairs) < MIN_CORRESPONDENCES:
            msg = (
                f"대응점이 {len(pairs)}쌍이다 — 호모그래피에는 최소 "
                f"{MIN_CORRESPONDENCES}쌍이 필요하다(자유도 8)"
            )
            raise CalibrationError(msg)

        source = [pair[0] for pair in pairs]
        target = [pair[1] for pair in pairs]
        _reject_collinear(source, "화면에서 찍은 4점")
        _reject_collinear(target, "실측 지면 4점")

        to_source, _ = _normalize(source)
        to_target, from_target = _normalize(target)
        normalized = [(_apply(to_source, px), _apply(to_target, m)) for px, m in pairs]
        solved = _solve_dlt(normalized)
        matrix = _multiply(from_target, _multiply(solved, to_source))
        return cls(matrix=_rescale(matrix))

    def to_rows(self) -> list[list[float]]:
        """DB·API 가 주고받는 형태(`aegis_contracts.Homography`)."""
        return [list(row) for row in self.matrix]

    # -- 변환 --------------------------------------------------------------

    def to_ground(self, point: PointPx) -> PointM:
        """정규화 픽셀 → 지면 실좌표(m). API명세서 §6.2"""
        return _apply(self.matrix, point)

    def to_pixel(self, point: PointM) -> PointPx:
        """지면 실좌표(m) → 정규화 픽셀. 구역을 화면에 그릴 때 쓴다(FN-UI-07)."""
        return _apply(self.inverse_matrix(), point)

    def inverse_matrix(self) -> Matrix3:
        """역행렬. `to_pixel` 과 왕복 오차 검증이 쓴다."""
        return _invert(self.matrix)

    def polygon_to_ground(self, polygon: Sequence[PointPx]) -> list[PointM]:
        """화면에서 그린 폴리곤을 지면 폴리곤으로. FN-CFG-02 (`zones.polygon_m`)"""
        return [self.to_ground(point) for point in polygon]

    def polygon_to_pixel(self, polygon: Sequence[PointM]) -> list[PointPx]:
        """지면 폴리곤을 화면 폴리곤으로. 설정 화면이 저장된 구역을 다시 그릴 때 쓴다."""
        return [self.to_pixel(point) for point in polygon]

    # -- 품질 --------------------------------------------------------------

    def reprojection_error_m(self, correspondences: Sequence[Correspondence]) -> float:
        """실측점을 다시 투영했을 때의 RMS 오차(m). API명세서 §4.5 `reprojection_error_m`

        **이 값을 화면에 보여준다.** 4점을 잘못 찍었는지 알 수 있는 유일한 수단이고,
        그것을 모르면 이후의 모든 거리·구역 판정이 조용히 틀어진다(FN-CFG-01).
        """
        if not correspondences:
            msg = "재투영 오차를 잴 대응점이 없다"
            raise CalibrationError(msg)
        total = 0.0
        for px, expected in correspondences:
            got = self.to_ground((float(px[0]), float(px[1])))
            total += (got[0] - expected[0]) ** 2 + (got[1] - expected[1]) ** 2
        return math.sqrt(total / len(correspondences))

    def round_trip_error_px(self, point: PointPx) -> float:
        """`픽셀 → 미터 → 픽셀` 왕복 오차(정규화 픽셀 단위).

        행렬 자체의 수치 건전성을 보는 값이다. 재투영 오차가 **캘리브레이션 품질**을
        재는 것과 달리 이쪽은 **연산 정확도**를 재므로, 둘을 같은 숫자로 보지 않는다.
        """
        back = self.to_pixel(self.to_ground(point))
        return math.hypot(back[0] - point[0], back[1] - point[1])


# --------------------------------------------------------------------------
# 내부 — 선형대수 (의존성 없이)
# --------------------------------------------------------------------------


def _apply(matrix: Matrix3, point: tuple[float, float]) -> tuple[float, float]:
    """동차좌표 변환 한 번.

    W 가 0에 가까우면 그 픽셀은 지평선 위이거나 카메라 뒤쪽이라 대응하는 지면 점이
    없다. 큰 수를 돌려주면 그 좌표가 거리 계산과 구역 판정에 그대로 흘러들어가므로
    여기서 막는다.
    """
    u, v = point
    w = matrix[2][0] * u + matrix[2][1] * v + matrix[2][2]
    if abs(w) < _W_EPSILON:
        msg = f"지면에 대응하지 않는 점이다 (지평선 위 또는 카메라 뒤): {point!r}"
        raise CalibrationError(msg)
    x = (matrix[0][0] * u + matrix[0][1] * v + matrix[0][2]) / w
    y = (matrix[1][0] * u + matrix[1][1] * v + matrix[1][2]) / w
    return (x, y)


def _multiply(left: Matrix3, right: Matrix3) -> Matrix3:
    return tuple(  # type: ignore[return-value]
        tuple(sum(left[i][k] * right[k][j] for k in range(3)) for j in range(3)) for i in range(3)
    )


def _determinant(matrix: Matrix3) -> float:
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _invert(matrix: Matrix3) -> Matrix3:
    det = _determinant(matrix)
    if abs(det) < 1e-15:
        msg = "역행렬이 없는 호모그래피다 — 캘리브레이션 점이 퇴화했다"
        raise CalibrationError(msg)
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    adjugate = (
        (e * i - f * h, c * h - b * i, b * f - c * e),
        (f * g - d * i, a * i - c * g, c * d - a * f),
        (d * h - e * g, b * g - a * h, a * e - b * d),
    )
    return tuple(tuple(value / det for value in row) for row in adjugate)  # type: ignore[return-value]


def _rescale(matrix: Matrix3) -> Matrix3:
    """`matrix[2][2]` 를 1로 맞춘다. 호모그래피는 스케일 자유도가 있어 표기를 고정한다."""
    scale = matrix[2][2]
    if abs(scale) < 1e-15:
        return matrix
    return tuple(tuple(value / scale for value in row) for row in matrix)  # type: ignore[return-value]


def _normalize(points: Sequence[tuple[float, float]]) -> tuple[Matrix3, Matrix3]:
    """Hartley 정규화 — 중심을 원점으로, 평균 거리를 √2 로.

    돌려주는 것은 (정규화 변환, 그 역변환)이다.
    """
    count = len(points)
    mean_x = sum(point[0] for point in points) / count
    mean_y = sum(point[1] for point in points) / count
    spread = sum(math.hypot(p[0] - mean_x, p[1] - mean_y) for p in points) / count
    if spread < 1e-12:
        msg = "대응점이 한 지점에 겹쳐 있다"
        raise CalibrationError(msg)
    scale = math.sqrt(2.0) / spread
    forward: Matrix3 = (
        (scale, 0.0, -scale * mean_x),
        (0.0, scale, -scale * mean_y),
        (0.0, 0.0, 1.0),
    )
    backward: Matrix3 = (
        (1.0 / scale, 0.0, mean_x),
        (0.0, 1.0 / scale, mean_y),
        (0.0, 0.0, 1.0),
    )
    return forward, backward


def _solve_dlt(pairs: Sequence[tuple[tuple[float, float], tuple[float, float]]]) -> Matrix3:
    """DLT — `A·h = 0` 의 최소제곱해. `AᵀA` 의 최소 고유벡터를 쓴다."""
    rows: list[list[float]] = []
    for (u, v), (x, y) in pairs:
        rows.append([-u, -v, -1.0, 0.0, 0.0, 0.0, u * x, v * x, x])
        rows.append([0.0, 0.0, 0.0, -u, -v, -1.0, u * y, v * y, y])

    size = 9
    gram = [[sum(row[i] * row[j] for row in rows) for j in range(size)] for i in range(size)]
    values, vectors = _jacobi_eigen(gram)
    smallest = min(range(size), key=lambda index: values[index])
    h = [vectors[row][smallest] for row in range(size)]
    return ((h[0], h[1], h[2]), (h[3], h[4], h[5]), (h[6], h[7], h[8]))


def _jacobi_eigen(matrix: list[list[float]]) -> tuple[list[float], list[list[float]]]:
    """대칭 행렬의 고유값·고유벡터(야코비 회전).

    `AᵀA` 는 항상 대칭이므로 이 방법이면 충분하고, 외부 라이브러리 없이 수치적으로
    안정적이다. 돌려주는 고유벡터는 열 벡터다 — `vectors[row][column]`.
    """
    size = len(matrix)
    a = [row[:] for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]

    for _ in range(_JACOBI_MAX_SWEEPS):
        off = math.sqrt(sum(a[i][j] ** 2 for i in range(size) for j in range(size) if i != j))
        if off < _JACOBI_TOLERANCE:
            break
        for p in range(size - 1):
            for q in range(p + 1, size):
                if abs(a[p][q]) < _JACOBI_TOLERANCE:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                sign = 1.0 if theta >= 0.0 else -1.0
                t = sign / (abs(theta) + math.sqrt(theta * theta + 1.0))
                cos = 1.0 / math.sqrt(t * t + 1.0)
                sin = t * cos
                for k in range(size):
                    akp = a[k][p]
                    akq = a[k][q]
                    a[k][p] = cos * akp - sin * akq
                    a[k][q] = sin * akp + cos * akq
                for k in range(size):
                    apk = a[p][k]
                    aqk = a[q][k]
                    a[p][k] = cos * apk - sin * aqk
                    a[q][k] = sin * apk + cos * aqk
                for k in range(size):
                    vkp = vectors[k][p]
                    vkq = vectors[k][q]
                    vectors[k][p] = cos * vkp - sin * vkq
                    vectors[k][q] = sin * vkp + cos * vkq
    return [a[i][i] for i in range(size)], vectors


def _reject_collinear(points: Sequence[tuple[float, float]], label: str) -> None:
    """네 점이 한 직선 위에 있으면 평면 대응이 성립하지 않는다.

    현장에서 실제로 일어나는 실수다 — 통로 한쪽 선을 따라 네 점을 찍으면 행렬이
    풀리기는 하지만 그 결과는 아무 의미가 없다. **풀린 것을 성공으로 넘기지 않는다.**
    """
    best = 0.0
    count = len(points)
    for i in range(count):
        for j in range(i + 1, count):
            for k in range(j + 1, count):
                ax, ay = points[i]
                bx, by = points[j]
                cx, cy = points[k]
                area = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) / 2.0
                best = max(best, area)
    if best < 1e-9:
        msg = f"{label} 이 한 직선 위에 있다 — 지면 평면이 정해지지 않는다"
        raise CalibrationError(msg)
