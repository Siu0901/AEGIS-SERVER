"""명세서 대응 모델의 공통 설정과 좌표 타입 별칭.

출처: API명세서 §1.2 (좌표계와 단위)
"""

from pydantic import BaseModel, ConfigDict

__all__ = ["Bbox", "Homography", "PointM", "PointPx", "SpecModel"]


class SpecModel(BaseModel):
    """모든 계약 모델의 베이스.

    `extra="forbid"` 는 의도적이다. 스키마는 `packages/contracts` 에만 정의하므로
    명세서에 없는 필드가 실려 오면 그것은 계약 위반이며 조용히 통과시키면 안 된다.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


#: 정규화 경계상자 `[x1, y1, x2, y2]` (좌상단, 우하단). 값 0.0~1.0.
Bbox = tuple[float, float, float, float]

#: 정규화 픽셀 좌표. 접미사 없음, 값 0.0~1.0. 프레임 좌상단 원점.
PointPx = tuple[float, float]

#: 지면 실좌표. 접미사 `_m`, 단위 미터. 캘리브레이션 기준점이 원점.
PointM = tuple[float, float]

#: 픽셀 좌표를 지면 좌표로 변환하는 3×3 호모그래피 행렬.
Homography = list[list[float]]
