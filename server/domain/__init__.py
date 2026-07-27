"""도메인 — 이벤트 상태머신과 지표 산출.

**I/O가 없다.** DB · 네트워크 · 파일 · 시간 전부 금지이며 순수 함수와 순수 상태 전이만
둔다(CLAUDE.md 절대규칙 2). 시간이 필요하면 `aegis_vision.clock.Clock` 을 주입받는다.

M0 에서는 저장소 프로토콜만 있다. 상태머신은 M2, 지표는 M4 다.
"""

from .repository import (
    AnomalyRepository,
    CameraRepository,
    EventRepository,
    PolicyRepository,
    Repository,
    VehicleClassRepository,
    ZoneRepository,
)

__all__ = [
    "AnomalyRepository",
    "CameraRepository",
    "EventRepository",
    "PolicyRepository",
    "Repository",
    "VehicleClassRepository",
    "ZoneRepository",
]
