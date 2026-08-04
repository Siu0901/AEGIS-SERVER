"""레터박스 기하 — 모델 입력 좌표 ↔ 정규화 프레임 좌표.

프레임은 640×360(16:9)이고 모델 입력은 640×384 rect 다. 화면비가 달라서 위아래에
패딩이 12px씩 붙는데, **모델이 내놓는 좌표는 패딩이 포함된 좌표계의 것**이다. 그대로
정규화하면 모든 박스가 세로로 눌리고 위로 밀린다.

여기서 하는 일은 그 두 좌표계를 잇는 것뿐이며, 실제 이미지 변환(`cv2.resize` ·
`copyMakeBorder`)은 `detect.py` 가 한다 — 이 모듈은 순수 계산이라 따로 검증할 수 있다.

```
     원본 640×360                모델 입력 640×384
    ┌───────────────┐          ┌───────────────┐  ← 패딩 12
    │               │   →      ├───────────────┤
    │               │          │               │
    └───────────────┘          ├───────────────┤
                               └───────────────┘  ← 패딩 12
```

**정규화 좌표는 항상 원본 프레임 기준이다**(API명세서 §1.2). 640p 서브에서 산출한
좌표가 1080p 메인 화면에 그대로 대응해야 하므로, 모델 입력 크기는 여기서 사라진다.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Letterbox"]


@dataclass(frozen=True, slots=True)
class Letterbox:
    """한 (프레임 크기 → 모델 입력) 조합의 변환. 카메라마다 하나 만들어 재사용한다."""

    source_width: int
    source_height: int
    model_width: int
    model_height: int

    @property
    def scale(self) -> float:
        """원본 → 모델 축소 배율. 가로세로 중 **작은 쪽**을 써서 화각을 자르지 않는다."""
        return min(
            self.model_width / self.source_width,
            self.model_height / self.source_height,
        )

    @property
    def resized_width(self) -> int:
        return round(self.source_width * self.scale)

    @property
    def resized_height(self) -> int:
        return round(self.source_height * self.scale)

    @property
    def pad_x(self) -> float:
        """좌우 패딩(모델 픽셀). 양쪽에 같은 값이 붙는다."""
        return (self.model_width - self.resized_width) / 2.0

    @property
    def pad_y(self) -> float:
        """상하 패딩(모델 픽셀)."""
        return (self.model_height - self.resized_height) / 2.0

    def to_normalized(self, x: float, y: float) -> tuple[float, float]:
        """모델 입력 픽셀 → 정규화 프레임 좌표(0.0~1.0).

        **자르지 않는다.** 박스가 프레임 경계에 걸리면 모델이 살짝 밖을 가리킬 수
        있는데, 여기서 0~1 로 접으면 접지점이 프레임 가장자리에 눌려 붙어 거리가
        조용히 틀어진다. 자를지 말지는 쓰는 쪽이 정한다.
        """
        return (
            (x - self.pad_x) / self.scale / self.source_width,
            (y - self.pad_y) / self.scale / self.source_height,
        )

    def to_model(self, nx: float, ny: float) -> tuple[float, float]:
        """정규화 프레임 좌표 → 모델 입력 픽셀. `to_normalized` 의 역이다."""
        return (
            nx * self.source_width * self.scale + self.pad_x,
            ny * self.source_height * self.scale + self.pad_y,
        )
