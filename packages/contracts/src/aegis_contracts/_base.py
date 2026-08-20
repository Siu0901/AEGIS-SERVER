"""명세서 대응 모델의 공통 설정과 좌표 타입 별칭.

출처: API명세서 §1.2 (좌표계와 단위)
"""

from pydantic import BaseModel, ConfigDict

__all__ = ["Bbox", "Contour", "Homography", "PointM", "PointPx", "SpecModel"]


class SpecModel(BaseModel):
    """모든 계약 모델의 베이스.

    `extra="forbid"` 는 의도적이다. 스키마는 `packages/contracts` 에만 정의하므로
    명세서에 없는 필드가 실려 오면 그것은 계약 위반이며 조용히 통과시키면 안 된다.

    `populate_by_name` 은 켜지 않는다. 켜면 `class` 별칭을 가진 필드가 명세서에 없는
    `class_` 라는 키로도 들어올 수 있어, 위 원칙에 구멍이 생긴다. 파이썬 코드에서
    이런 모델을 만들 때는 `model_validate({"class": ...})` 를 쓴다.
    """

    model_config = ConfigDict(extra="forbid")


#: 정규화 경계상자 `[x1, y1, x2, y2]` (좌상단, 우하단). 값 0.0~1.0.
Bbox = tuple[float, float, float, float]

#: 정규화 픽셀 좌표. 접미사 없음, 값 0.0~1.0. 프레임 좌상단 원점.
PointPx = tuple[float, float]

#: 진단용 마스크 윤곽 — 정규화 픽셀 좌표의 점 목록 (API명세서 §2.1).
#:
#: ★ **판정에 쓰지 않는다.** 감지 결과를 눈으로 확인하기 위한 값이고, 거리·자세·접지점은
#:   전부 엣지가 원본 마스크로 계산해 결과값만 싣는다. 서버는 이 값을 읽지 않고 통과시킨다.
#:
#: ★ **기본은 아예 싣지 않는다.** 정책 `overlay_mask` 가 켜졌을 때만 채운다 — 점 하나가
#:   좌표 두 개이므로 켜두면 오버레이 메시지가 몇 배로 커진다.
Contour = list[PointPx]

#: 지면 실좌표. 접미사 `_m`, 단위 미터. 캘리브레이션 기준점이 원점.
PointM = tuple[float, float]

#: 픽셀 좌표를 지면 좌표로 변환하는 3×3 호모그래피 행렬.
Homography = list[list[float]]
