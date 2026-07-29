"""상태머신과 바깥세상을 잇는 층 — 저장 · 발행 · 로깅.

`server/domain/event_machine.py` 는 판단만 하고 I/O 를 모른다(CLAUDE.md 절대규칙 2).
여기서 그 판단(`Effect`)을 실제로 집행한다.

| 하는 일 | 근거 |
|---|---|
| `Effect` 를 저장소에 적용 (생성 · 갱신 · 폐기) | FN-REC-04 |
| §5.2 `event_created` · `event_updated` 발행 | API명세서 §5.2 |
| 전이 후 오버레이 트랙 상태 동기화 | §5.1 `alert_state` |
| 종결 전이마다 §5.3 `metric` 재발행 | FN-SYS-04 |
| 기동 시 열려 있던 이벤트 복구 | 재시작이 지표를 왜곡하지 않게 |
| 수동 정정 (FN-EVT-05) | API명세서 §4.1 `PATCH` |

**경고 발동(wav · MQTT)은 여기 없다.** M4(FN-ALM-01·02)이며, M3 은 "경고를 발동했다"는
사실(`alerted_at` · `alert_count`)만 기록한다 — 시정률의 기준점이 그 기록이기 때문이다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from aegis_contracts import (
    CandidateMsg,
    EventDetail,
    EventPatchRequest,
    EventStatus,
    EventSummary,
    EventUpdatedMsg,
    FrameMsg,
    MetricMsg,
    MetricsSummary,
    Policies,
    SpecModel,
    TrackLostMsg,
)
from aegis_vision.clock import Clock
from server.domain.event_machine import Effect, EventMachine
from server.domain.metrics import MetricsRow, summarize
from server.domain.overlay import LiveTracks

__all__ = [
    "POLICY_REFRESH_SECONDS",
    "TICK_SECONDS",
    "EventService",
    "EventStore",
    "PolicyReader",
    "Publisher",
    "today_window",
]

log = logging.getLogger("server.events")

#: 종결 상태. 여기에 닿으면 지표가 바뀌므로 `metric` 을 다시 내보낸다(§5.3).
_TERMINAL: frozenset[EventStatus] = frozenset({EventStatus.RESOLVED, EventStatus.EXPIRED})


class EventStore(Protocol):
    """상태머신이 요구하는 저장소. 구현은 `server/infra/db/repository.py`."""

    async def find_open_all(self) -> list[EventSummary]: ...

    async def next_event_id(self, at: datetime) -> str: ...

    async def create(self, event: EventDetail) -> None: ...

    async def update(self, event_id: str, changes: Mapping[str, Any]) -> None: ...

    async def delete(self, event_id: str) -> None: ...

    async def get(self, event_id: str) -> EventDetail | None: ...

    async def metrics_rows(
        self, from_: datetime | None, to: datetime | None
    ) -> list[MetricsRow]: ...


class PolicyReader(Protocol):
    """정책값 조회. 임계값은 코드가 아니라 DB 에서 온다(절대규칙 6)."""

    async def load(self) -> Policies: ...


class Publisher(Protocol):
    """대시보드로 계약 모델 하나를 밀어 넣는 통로. 구현은 `DashboardHub.broadcast`."""

    async def __call__(self, message: SpecModel) -> None: ...


def today_window(now: datetime) -> tuple[datetime, datetime]:
    """`period = "today"` 의 구간. 저장이 UTC 이므로 **UTC 자정**으로 끊는다(§1.2).

    화면 표시는 KST 지만, 집계 경계까지 로컬로 옮기면 같은 이벤트가 어느 날에
    속하는지가 서버의 시간대 설정에 따라 달라진다.
    """
    return now.replace(hour=0, minute=0, second=0, microsecond=0), now


class EventService:
    """이벤트 한 건의 수명 전체를 담당한다."""

    def __init__(
        self,
        *,
        machine: EventMachine,
        tracks: LiveTracks,
        publish: Publisher,
        clock: Clock,
        store: EventStore | None = None,
        policies: PolicyReader | None = None,
    ) -> None:
        self._machine = machine
        self._tracks = tracks
        self._publish = publish
        self._clock = clock
        self._store = store
        self._policies = policies

    @property
    def machine(self) -> EventMachine:
        return self._machine

    # -- 기동 -----------------------------------------------------------

    async def start(self) -> None:
        """정책값을 읽고, 열려 있던 이벤트를 상태머신에 되살린다."""
        await self.refresh_policies()
        if self._store is None:
            log.error("이벤트 저장소가 없다 — 상태머신이 아무것도 기록하지 못한다")
            return
        try:
            open_events = await self._store.find_open_all()
        except Exception:
            # 저장소 종류를 가리지 않고 잡는다 — DB 가 꺼져 있어도 서버는 떠야 하고
            # (라이브·오버레이는 DB 없이 돈다), 그 사실은 조용히 넘어가지 않고
            # ERROR 로 드러난다(CLAUDE.md 절대규칙 9).
            log.exception("진행 중 이벤트를 복구하지 못했다 — 그 이벤트들은 종결되지 않는다")
            return
        self._machine.restore(open_events, self._clock.now())
        if open_events:
            log.info("진행 중 이벤트 %d건 복구 — 타이머는 0부터 다시 센다", len(open_events))

    async def refresh_policies(self) -> None:
        """DB 정책값을 상태머신에 반영한다. 실패하면 계약 기본값으로 돈다."""
        if self._policies is None:
            return
        try:
            self._machine.set_policies(await self._policies.load())
        except Exception:
            log.exception("정책값을 읽지 못했다 — 계약 기본값(packages/contracts)으로 돈다")

    # -- 엣지 메시지 -----------------------------------------------------

    async def on_candidate(self, candidate: CandidateMsg) -> None:
        """FN-EVT-01 · FN-EVT-02 — 후보 한 건."""
        if self._store is None:
            log.error(
                "이벤트 저장소가 없어 후보를 기록하지 못했다 — cam=%s track=%s",
                candidate.cam_id,
                candidate.track_id,
            )
            return
        event_id = (
            await self._store.next_event_id(candidate.ts)
            if self._machine.needs_event_id(candidate)
            else None
        )
        effects = self._machine.on_candidate(candidate, event_id)
        await self._apply(effects)
        # `nearby` 는 후보만 나른다(§2.2). 거리선의 원천이므로 여기서 갱신한다.
        self._tracks.record_candidate(
            candidate, self._machine.open_events(candidate.cam_id, candidate.track_id)
        )

    async def on_frame(self, frame: FrameMsg) -> None:
        """FN-EVT-03 — 프레임으로 위반 지속·소멸을 판정한다."""
        await self._apply(self._machine.on_frame(frame))

    async def on_track_lost(self, message: TrackLostMsg) -> None:
        """FN-EVT-07 ① — 소실 유예로 넘긴다. 오버레이에서는 즉시 내린다."""
        await self._apply(self._machine.on_track_lost(message))
        self._tracks.forget(message.cam_id, message.track_id)

    async def tick(self, now: datetime | None = None) -> None:
        """관측이 없어도 흘러야 하는 것들 — 소실 감지 · 유예 만료 · 쿨다운."""
        await self._apply(self._machine.tick(now))

    def clear_tracks(self) -> None:
        """엣지가 끊겼다. 오버레이 표시만 내린다.

        **이벤트는 건드리지 않는다.** 관측 주체가 사라졌을 뿐이고, 진행 중 이벤트는
        `tick` 이 미관측으로 보아 `lost` → `expired`(판정 불가)로 정직하게 종결한다.
        """
        self._tracks.clear()

    # -- 수동 정정 (FN-EVT-05) -------------------------------------------

    async def patch(self, event_id: str, request: EventPatchRequest) -> EventDetail | None:
        """오탐 표시 또는 강제 종결. API명세서 §4.1 · 기능명세서 §4.2

        **`fall` 은 관리자 확인으로 종결하는 것이 기본 절차다**(§4.1).
        """
        if self._store is None:
            return None
        event = await self._store.get(event_id)
        if event is None:
            return None

        now = self._clock.now()
        changes: dict[str, Any] = {}
        message = EventUpdatedMsg(event_id=event_id, status=event.status)

        if request.is_false_positive is not None:
            changes["is_false_positive"] = request.is_false_positive
            message = message.model_copy(
                update={"is_false_positive": request.is_false_positive, "note": request.note}
            )
            if request.is_false_positive:
                # 지표에서 전량 제외되는 건이다. 상태머신에서도 내린다 — 더 전이시켜
                # 봐야 집계에 들어가지 않고, 남겨두면 병합 키만 붙잡는다.
                self._machine.forget(event_id)

        if request.force_resolve:
            resolution_sec = (
                round((now - event.alerted_at).total_seconds())
                if event.alerted_at is not None
                else None
            )
            changes.update(
                {
                    "status": EventStatus.RESOLVED.value,
                    "resolved_at": now,
                    "resolution_sec": resolution_sec,
                }
            )
            message = message.model_copy(
                update={
                    "status": EventStatus.RESOLVED,
                    "resolved_at": now,
                    "resolution_sec": resolution_sec,
                }
            )
            self._machine.forget(event_id)

        if not changes:
            return event

        # `note` 는 저장하지 않는다 — `events` 테이블(기능명세서 §6)에 컬럼이 없다.
        # 명세서에 없는 컬럼을 코드가 먼저 만들지 않는다(절대규칙 8). 대시보드에는
        # 실어 보내고 로그에 남긴다. docs/INDEX.md 「명세서 확인 필요」 참조.
        if request.note:
            log.info("수동 정정 메모 %s — %s", event_id, request.note)

        await self._store.update(event_id, changes)
        await self._publish(message)
        self._tracks.set_events(
            event.cam_id, event.track_id, self._machine.open_events(event.cam_id, event.track_id)
        )
        await self._publish_metric()
        log.info("수동 정정 %s — %s", event_id, changes)
        return await self._store.get(event_id)

    # -- 지표 (FN-SYS-04 · FN-SYS-05) -------------------------------------

    async def summary(
        self,
        *,
        from_: datetime | None = None,
        to: datetime | None = None,
    ) -> MetricsSummary:
        """`GET /metrics/summary` 본문. 구간을 주지 않으면 오늘(UTC)이다."""
        if self._store is None:
            msg = "이벤트 저장소가 연결되지 않았다"
            raise RuntimeError(msg)
        start: datetime | None = from_
        end: datetime | None = to
        period = "custom"
        if from_ is None and to is None:
            start, end = today_window(self._clock.now())
            period = "today"
        rows = await self._store.metrics_rows(start, end)
        return summarize(
            rows,
            period=period,
            resolve_window_s=self._machine.policies.resolve_window_s,
            # 이상 탐지(FN-AI-04)는 M8 이다. 0 은 "아직 세지 않는다"가 아니라
            # "이상 플래그를 만드는 기능이 없다"는 뜻이며, 화면에도 그렇게 나온다.
            anomaly_flags=0,
        )

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    async def _apply(self, effects: list[Effect]) -> None:
        if not effects:
            return
        touched: set[tuple[int, int]] = set()
        terminal = False
        for effect in effects:
            if effect.note:
                log.info("%s", effect.note)
            await self._persist(effect)
            if effect.message is not None:
                await self._publish(effect.message)
            touched.add((effect.cam_id, effect.track_id))
            status = effect.changes.get("status")
            terminal = terminal or status in {state.value for state in _TERMINAL}
        for cam_id, track_id in touched:
            self._tracks.set_events(cam_id, track_id, self._machine.open_events(cam_id, track_id))
        if terminal:
            await self._publish_metric()

    async def _persist(self, effect: Effect) -> None:
        if self._store is None:
            log.error("이벤트 저장소가 없어 %s 를 기록하지 못했다", effect.event_id)
            return
        match effect.action:
            case "create":
                if effect.event is not None:
                    await self._store.create(effect.event)
            case "update":
                await self._store.update(effect.event_id, effect.changes)
            case "delete":
                await self._store.delete(effect.event_id)

    async def _publish_metric(self) -> None:
        """§5.3 `metric` — 종결이 일어났으니 시정률이 바뀌었다.

        실패해도 상태 전이를 되돌리지 않는다. 지표 표시가 한 박자 늦는 것보다
        전이가 반쯤 적용되는 쪽이 훨씬 위험하다.
        """
        try:
            summary = await self.summary()
        except (OSError, RuntimeError, ValueError) as exc:
            log.warning("지표를 다시 계산하지 못했다: %s", exc)
            return
        await self._publish(
            MetricMsg(
                period=summary.period,
                correction_rate=summary.correction_rate,
                undetermined_rate=summary.undetermined_rate,
                total_violations=summary.total_violations,
                resolved=summary.resolved,
                unresolved=summary.unresolved,
                undetermined=summary.undetermined,
                avg_resolution_sec=summary.avg_resolution_sec,
                fall_events=summary.fall_events,
                anomaly_flags=summary.anomaly_flags,
            )
        )


#: 틱 주기. 소실 감지·유예 만료·쿨다운이 이 간격으로 판정된다.
#:
#: 확정 → 경고가 **1초 이내**여야 하므로(FN-ALM-01) 그보다 충분히 짧아야 한다.
#: 다만 확정은 프레임이 도착할 때 그 자리에서 판정되므로(8fps → 125ms) 이 값은
#: "관측이 아예 끊겼을 때의 상한"에 가깝다.
TICK_SECONDS = 0.5

#: 정책값을 다시 읽는 주기(초). 설정 화면에서 임계값을 바꾸면 이만큼 안에 반영된다.
POLICY_REFRESH_SECONDS = 60.0
