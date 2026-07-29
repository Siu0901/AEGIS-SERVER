"""클라우드(Gemini) 가용성 — 순수 상태 보관소. FN-SYS-03

기능명세서 §4.8 · API명세서 §4.6 `cloud`

**클라우드가 죽어도 안전 기능은 무영향이어야 한다.** 그 격리를 코드로 보장하는 방법은
두 가지다.

1. **호출 경로를 섞지 않는다.** 감지 → 확정 → 경고 → 시정 판정 어디에도 클라우드
   클라이언트가 없다. `server/domain` 은 I/O 를 아예 하지 않고(절대규칙 2),
   `server/app/alert_service.py` 와 `server/infra/clip/` 도 REC·MQTT·스피커만 만진다.
2. **실패를 상태로 바꿔 표시만 한다.** 클라우드 호출이 실패하면 여기에 기록되고,
   그 결과는 `GET /system/status` 의 `cloud` 절과 §5.3 `system` 메시지로만 나간다.

이 모듈에는 아직 호출자가 없다 — 실제 어댑터는 M7(`server/ai/`)이다. 그래도 지금
두는 이유는, 라우트가 `available: false` 를 **상수로 박아두고 있으면** M7 에서 클라우드가
붙어도 화면이 계속 "중단"으로 남기 때문이다. 상태를 읽는 자리를 먼저 비워 둔다.

**`quota_used` 는 도달하지 못하면 `null` 이다**(§4.6). `0.0` 은 "한도를 안 썼다"는
다른 주장이라 실제 장애와 구분되지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aegis_contracts import CloudStatus, ComponentSystemMsg
from aegis_contracts.enums import ComponentState

__all__ = ["CloudRuntime"]

#: 이 사용률을 넘으면 `degraded` 로 본다. 아직 쓸 수 있으나 곧 끊긴다는 뜻이다.
_QUOTA_WARN = 0.8


@dataclass(slots=True)
class CloudRuntime:
    """클라우드 API 의 마지막 관측 결과.

    기동 직후에는 **`available: false` · `quota_used: null`** 이다. "아직 불러본 적이
    없다"를 "쓸 수 있다"로 낙관하지 않는다 — 분석 결과가 비어 있는 이유가 화면에
    드러나야 하기 때문이다. 이 값은 안전 루프의 어떤 판정에도 쓰이지 않는다.
    """

    available: bool = False
    quota_used: float | None = None
    last_error: str | None = None

    def mark_ok(
        self, at: datetime, *, quota_used: float | None = None
    ) -> ComponentSystemMsg | None:
        """호출이 성공했다. 상태가 **변한 때만** `system` 을 돌려준다(§5.3)."""
        was = self.state()
        self.available = True
        self.quota_used = quota_used
        self.last_error = None
        now = self.state()
        if now == was:
            return None
        detail = "클라우드 정상" if quota_used is None else f"쿼터 {quota_used:.0%}"
        return ComponentSystemMsg(component="cloud_api", state=now, detail=detail, at=at)

    def mark_failed(self, at: datetime, reason: str) -> ComponentSystemMsg | None:
        """호출이 실패했다. **분석 기능만 멈춘다** — 경고·클립·시정 판정은 무관하다."""
        was = self.state()
        self.available = False
        # 도달하지 못했으면 사용률을 알 수 없다. 마지막 값을 남기면 화면이 그것을
        # 현재로 읽는다(§4.6 null 규약).
        self.quota_used = None
        self.last_error = reason
        now = self.state()
        if now == was:
            return None
        return ComponentSystemMsg(
            component="cloud_api",
            state=now,
            detail=f"분석 기능 중단 — {reason} (안전 기능은 계속 동작한다)",
            at=at,
        )

    def state(self) -> ComponentState:
        if not self.available:
            return "down"
        if self.quota_used is not None and self.quota_used >= _QUOTA_WARN:
            return "degraded"
        return "ok"

    def status(self) -> CloudStatus:
        """`GET /system/status` 의 `cloud` 절. API명세서 §4.6"""
        return CloudStatus(available=self.available, quota_used=self.quota_used)
