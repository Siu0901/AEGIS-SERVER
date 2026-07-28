"""`/ws/edge` — 엣지 → 서버 WebSocket (API명세서 §2).

엣지가 올리는 것은 네 가지다 — `frame`(§2.1) · `candidate`(§2.2) ·
`track_lost`(§2.3) · `heartbeat`(§2.4). 여기서 하는 일:

| 메시지 | 처리 |
|---|---|
| `frame` | 이벤트 상태를 합쳐 `overlay` 로 대시보드에 흘린다(§5.1) |
| `candidate` | FN-EVT-01 중복 병합 → 이벤트 생성·갱신 → DB(FN-REC-04) |
| `track_lost` | 오버레이에서 그 트랙을 내린다 |
| `heartbeat` | 엣지·서브 스트림 상태 갱신(FN-SYS-01) |

**후보를 조용히 버리지 않는다 (FN-SYS-06).** 스키마 검증에 실패해도 로그 없이
폐기하지 않는다 — 감지된 위반이 검증 단계에서 소리 없이 사라지는 것은 오탐보다
위험하다. 원본 페이로드와 오류를 남기고, `edge_msg_rejected_total{type, reason}` 을
올리고, `GET /system/status` 와 대시보드에 노출한다.

**재전송을 요청하지 않는다** (§2.2). NACK 없이 일방적으로 폐기하고 집계만 한다.
스키마 불일치는 일시적 장애가 아니라 엣지 코드의 결함이라 재전송해도 같은 결과가
반복되고, 실시간 안전 루프에 재시도 대기를 넣으면 지연만 늘어난다.

**M2 에는 상태머신이 없다.** 확정(FN-EVT-02) · 해소(FN-EVT-03) · 쿨다운(FN-EVT-04) ·
소실 유예와 재결합(FN-EVT-07)은 M3 다. 그래서 여기서 만든 이벤트는 `candidate` 에
머물고, §5.2 `event_created`(신규 **확정** 이벤트)는 아직 발행하지 않는다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from aegis_contracts import (
    CandidateMsg,
    EdgeMessage,
    EventDetail,
    EventStatus,
    EventSummary,
    FrameMsg,
    HeartbeatMsg,
    SpecModel,
    TrackLostMsg,
    ViolationType,
)
from aegis_vision.clock import Clock
from server.domain.edge_state import EdgeRuntime
from server.domain.event_machine import build_candidate_event, merge_changes, plan_candidate
from server.domain.overlay import LiveTracks, compose_overlay

__all__ = ["MAX_LOGGED_PAYLOAD", "EdgeGateway", "EventStore"]

log = logging.getLogger("server.ws.edge")

_ADAPTER: TypeAdapter[Any] = TypeAdapter(EdgeMessage)

#: 거부 로그에 남기는 원본 페이로드의 최대 길이.
#:
#: 자르지 않으면 프레임 하나가 수 KB 라 로그가 금방 덮인다. 그렇다고 안 남기면
#: "무엇이 거부됐는지"를 영영 알 수 없다 — 그게 FN-SYS-06 이 막으려는 상황이다.
MAX_LOGGED_PAYLOAD = 2000


class EventStore(Protocol):
    """`/ws/edge` 가 요구하는 이벤트 저장소. 구현은 `server/infra/db/repository.py`."""

    async def find_open_events(
        self, cam_id: int, track_id: int
    ) -> dict[ViolationType, EventSummary]: ...

    async def next_event_id(self, at: Any) -> str: ...

    async def create(self, event: EventDetail) -> None: ...

    async def update(self, event_id: str, changes: dict[str, Any]) -> None: ...


class Publisher(Protocol):
    """대시보드로 계약 모델 하나를 밀어 넣는 통로. 구현은 `DashboardHub.broadcast`."""

    async def __call__(self, message: SpecModel) -> None: ...


class EdgeGateway:
    """`/ws/edge` 한 소켓의 수명을 담당한다.

    상태(`EdgeRuntime` · `LiveTracks`)는 소켓보다 오래 살아야 하므로 밖에서 주입받는다 —
    엣지가 잠깐 끊겼다 붙을 때마다 거부 집계가 0으로 돌아가면 FN-SYS-06 이 무의미해진다.
    """

    def __init__(
        self,
        *,
        edge: EdgeRuntime,
        tracks: LiveTracks,
        publish: Publisher,
        clock: Clock,
        events: EventStore | None = None,
    ) -> None:
        self._edge = edge
        self._tracks = tracks
        self._publish = publish
        self._clock = clock
        self._events = events

    async def serve(self, websocket: WebSocket) -> None:
        await websocket.accept()
        await self._publish(self._edge.connect(self._clock.now()))
        log.info("엣지 접속")
        try:
            while True:
                await self.handle(await websocket.receive_text())
        except WebSocketDisconnect:
            pass
        finally:
            self._tracks.clear()
            for message in self._edge.disconnect(self._clock.now()):
                await self._publish(message)
            log.info("엣지 연결 종료")

    async def handle(self, raw: str) -> None:
        """메시지 한 건. 검증에 실패하면 집계하고 버린다(§2.2 · FN-SYS-06)."""
        message = await self._parse(raw)
        if message is None:
            return
        if isinstance(message, FrameMsg):
            await self._publish(compose_overlay(message, self._tracks))
        elif isinstance(message, CandidateMsg):
            await self._on_candidate(message)
        elif isinstance(message, TrackLostMsg):
            self._on_track_lost(message)
        elif isinstance(message, HeartbeatMsg):
            for change in self._edge.apply_heartbeat(message, self._clock.now()):
                await self._publish(change)

    # ------------------------------------------------------------------
    # 검증
    # ------------------------------------------------------------------

    async def _parse(self, raw: str) -> Any | None:
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            await self._reject(raw, "unknown", "invalid_json", str(exc))
            return None

        kind = payload.get("type") if isinstance(payload, dict) else None
        kind = kind if isinstance(kind, str) else "unknown"
        try:
            return _ADAPTER.validate_python(payload)
        except ValidationError as exc:
            await self._reject(raw, kind, _reason(exc), _detail(exc))
            return None

    async def _reject(self, raw: str, kind: str, reason: str, detail: str) -> None:
        """거부 한 건 — 로그 · 카운터 · 대시보드. 세 가지를 모두 한다.

        하나라도 빠지면 "엣지 구현이 바뀌어 필드가 누락되기 시작하면 즉시 드러나야
        한다"는 요구(§2.2)가 성립하지 않는다.
        """
        log.warning(
            "엣지 메시지 거부 — type=%s reason=%s: %s\n  원본: %s",
            kind,
            reason,
            detail,
            raw[:MAX_LOGGED_PAYLOAD],
        )
        await self._publish(self._edge.reject(kind, reason, self._clock.now()))

    # ------------------------------------------------------------------
    # 메시지별 처리
    # ------------------------------------------------------------------

    async def _on_candidate(self, candidate: CandidateMsg) -> None:
        """FN-EVT-01 — 동일 `cam_id` + `track_id` + 위반 유형이면 새로 만들지 않는다."""
        if self._events is None:
            log.error(
                "이벤트 저장소가 없어 후보를 기록하지 못했다 — cam=%s track=%s",
                candidate.cam_id,
                candidate.track_id,
            )
            return

        open_events = await self._events.find_open_events(candidate.cam_id, candidate.track_id)
        plan = plan_candidate(
            candidate, {violation: item.event_id for violation, item in open_events.items()}
        )

        merged: dict[ViolationType, tuple[str, EventStatus]] = {
            violation: (item.event_id, item.status) for violation, item in open_events.items()
        }

        for violation, event_id in plan.updates:
            changes = merge_changes(open_events[violation], candidate)
            if changes:
                await self._events.update(event_id, changes)

        for violation in plan.creates:
            event_id = await self._events.next_event_id(candidate.ts)
            event = build_candidate_event(candidate, violation, event_id)
            await self._events.create(event)
            merged[violation] = (event_id, event.status)
            log.info(
                "이벤트 생성 %s — cam=%s track=%s type=%s",
                event_id,
                candidate.cam_id,
                candidate.track_id,
                violation.value,
            )

        self._tracks.record_candidate(candidate, merged)

    def _on_track_lost(self, message: TrackLostMsg) -> None:
        """오버레이에서 그 트랙을 내린다.

        **이벤트를 `lost` 로 전이시키지 않는다** — 소실 유예(FN-EVT-07 ①)는 상태머신과
        함께 M3 에 붙는다. 지금 전이만 흉내 내면 유예 만료가 없어 `expired` 로 끝나는
        길이 막히고, 그 이벤트들이 영원히 `lost` 로 남아 판정 불가율을 왜곡한다.
        """
        self._tracks.forget(message.cam_id, message.track_id)
        log.info(
            "트랙 소실 — cam=%s track=%s reason=%s",
            message.cam_id,
            message.track_id,
            message.reason,
        )


def _reason(exc: ValidationError) -> str:
    """카운터 라벨로 쓸 사유. `edge_msg_rejected_total{type, reason}` (§2.2).

    pydantic 의 오류 종류를 그대로 쓴다(`missing` · `float_parsing` ·
    `union_tag_invalid` …). 자유 문자열을 쓰면 라벨 카디널리티가 폭발한다.
    """
    errors = exc.errors()
    return str(errors[0]["type"]) if errors else "invalid"


def _detail(exc: ValidationError) -> str:
    """사람이 읽을 오류 요약. 어느 필드가 왜 걸렸는지까지 남긴다."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()[:5]
    )
