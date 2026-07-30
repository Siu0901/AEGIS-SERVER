"""상태머신과 바깥세상을 잇는 층 — 저장 · 발행 · 로깅.

`server/domain/event_machine.py` 는 판단만 하고 I/O 를 모른다(CLAUDE.md 절대규칙 2).
여기서 그 판단(`Effect`)을 실제로 집행한다.

| 하는 일 | 근거 |
|---|---|
| `Effect` 를 저장소에 적용 (생성 · 갱신) | FN-REC-04 |
| §5.2 `event_created` · `event_updated` 발행 | API명세서 §5.2 |
| 전이 후 오버레이 트랙 상태 동기화 | §5.1 `alert_state` |
| 종결 전이마다 §5.3 `metric` 재발행 | FN-SYS-04 |
| 기동 시 열려 있던 이벤트 복구 | 재시작이 지표를 왜곡하지 않게 |
| 수동 정정 (FN-EVT-05) | API명세서 §4.1 `PATCH` |
| 경고 집행 지시 (`AlertIntent` → wav · MQTT) | FN-ALM-01 · 02 |
| 확정 시 클립 예약 · 키프레임 (FN-REC-03) | 기능명세서 §4.4 |

**소리를 내는 것도 클립을 뽑는 것도 여기가 직접 하지 않는다.** 이 층은 상태머신의
판단을 해당 부품(`alert_service` · `infra/clip`)으로 넘길 뿐이다. 순서는 정해져 있다 —
**저장 · 발행 · 경고가 먼저이고 클립 예약이 나중**이다. 클립은 20초 뒤에 뽑히는 것이라
1초 예산과 무관하지만, 그 앞에 두면 DB 왕복 한 번이 방송 앞을 막는다.
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
from server.app.alert_service import AlertSink
from server.domain.event_machine import Effect, EventMachine
from server.domain.metrics import MetricsRow, summarize
from server.domain.overlay import LiveTracks

__all__ = [
    "POLICY_REFRESH_SECONDS",
    "TICK_SECONDS",
    "ClipScheduler",
    "EventService",
    "EventStore",
    "PolicyReader",
    "Publisher",
    "today_window",
]

log = logging.getLogger("server.events")

#: 종결 상태. 여기에 닿으면 지표가 바뀌므로 `metric` 을 다시 내보낸다(§5.3).
#:
#: `dropped` 는 여기 없다 — 시정률·판정 불가율 어느 쪽에도 들어가지 않으므로(§4.2)
#: 그 전이로는 지표가 한 숫자도 움직이지 않는다.
_TERMINAL: frozenset[EventStatus] = frozenset({EventStatus.RESOLVED, EventStatus.EXPIRED})


class EventStore(Protocol):
    """상태머신이 요구하는 저장소. 구현은 `server/infra/db/repository.py`."""

    async def find_open_all(self) -> list[EventSummary]: ...

    async def next_event_id(self, at: datetime) -> str: ...

    async def create(self, event: EventDetail) -> None: ...

    async def update(self, event_id: str, changes: Mapping[str, Any]) -> None: ...

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


class ClipScheduler(Protocol):
    """확정 시 클립을 예약하는 부품. 구현은 `server/infra/clip/service.py`. FN-REC-03"""

    async def on_confirmed(self, event_id: str, cam_id: int, confirmed_at: datetime) -> None: ...


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
        alerts: AlertSink | None = None,
        clips: ClipScheduler | None = None,
    ) -> None:
        self._machine = machine
        self._tracks = tracks
        self._publish = publish
        self._clock = clock
        self._store = store
        self._policies = policies
        self._alerts = alerts
        self._clips = clips

    @property
    def machine(self) -> EventMachine:
        return self._machine

    @property
    def alerts(self) -> AlertSink | None:
        """경고 집행자. 수동 방송·일시중지(FN-ALM-04 · 05)가 같은 것을 쓴다."""
        return self._alerts

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
            message = message.model_copy(update={"is_false_positive": request.is_false_positive})
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

        if request.note is not None:
            # §6 `events.note` — **저장한다.** 여기 남지 않으면 오탐 판단의 근거가
            # 다시 조회했을 때 사라진다. §5.2 「수동 정정」 동반 필드이기도 하다.
            changes["note"] = request.note
            message = message.model_copy(update={"note": request.note})

        if not changes:
            return event

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
            # 경고가 먼저다(FN-ALM-01 · 1초 이내). 클립 예약은 20초 뒤에 실행될 잡이라
            # 이 순서가 바뀌면 예약 기록의 DB 왕복이 방송 앞을 막는다.
            if effect.alert is not None:
                await self._fire(effect)
            await self._schedule_clip(effect)
            touched.add((effect.cam_id, effect.track_id))
            status = effect.changes.get("status")
            terminal = terminal or status in {state.value for state in _TERMINAL}
        for cam_id, track_id in touched:
            self._tracks.set_events(cam_id, track_id, self._machine.open_events(cam_id, track_id))
        if terminal:
            await self._publish_metric()

    async def _fire(self, effect: Effect) -> None:
        """FN-ALM-01 · 02 — 상태머신이 낸 경고 지시를 집행자에게 넘긴다.

        **실패해도 전이를 되돌리지 않는다.** 경고가 나가지 않은 것은 심각하지만
        (집행자가 ERROR 로 남기고 집계한다), 그 때문에 이벤트를 되돌리면 `alerted_at`
        이 사라져 시정률의 기준점이 없어진다 — 위반 사실 자체는 관측된 것이다.

        **일시중지로 방송이 나가지 않았다면 그 사실을 기록한다**(§4.8). 집행자가
        `False` 를 돌려주면 `alert_suppressed = true` 로 남겨 시정률 모집단에서
        제외한다 — 알린 적이 없는 위반을 미시정으로 세면 지표가 자기 이름
        (「방송 후 시정률」)과 어긋난다.
        """
        if effect.alert is None:
            return
        if self._alerts is None:
            log.error(
                "경고 집행자가 없어 %s 의 방송·경광등이 나가지 않았다 (조립 문제)",
                effect.event_id,
            )
            return
        try:
            dispatched = await self._alerts.fire(effect.alert)
        except Exception:
            # 집행이 죽었다. **`alert_suppressed` 로 적지 않는다** — 그 칸은 "사람이
            # 일부러 멈췄다"는 뜻이고, 여기는 "내보내려 했으나 고장났다"다. 후자를
            # 지표에서 빼면 장애가 시정률을 좋아 보이게 만든다.
            log.exception("경고 집행이 실패했다 — %s", effect.event_id)
            return
        if not dispatched:
            await self._mark_suppressed(effect.event_id)

    async def _mark_suppressed(self, event_id: str) -> None:
        """FN-ALM-05 · §4.8 — 방송 없이 확정된 이벤트를 표시한다."""
        if self._store is None:
            return
        try:
            await self._store.update(event_id, {"alert_suppressed": True})
        except Exception:
            # 조용히 넘기면 그 이벤트가 미시정으로 집계되어 시정률이 낮아진다.
            log.exception(
                "alert_suppressed 를 기록하지 못했다 — %s 가 시정률 분모에 남는다", event_id
            )

    async def _schedule_clip(self, effect: Effect) -> None:
        """FN-REC-03 — 확정된 이벤트의 키프레임을 뽑고 클립 추출을 예약한다.

        `confirmed_at` 이 `changes` 에 실린 전이가 **확정 그 순간**이다. 재경고나 해소는
        이 칸을 건드리지 않으므로 예약이 두 번 걸리지 않는다.
        """
        confirmed_at = effect.changes.get("confirmed_at")
        if confirmed_at is None or self._clips is None:
            return
        try:
            await self._clips.on_confirmed(effect.event_id, effect.cam_id, confirmed_at)
        except Exception:
            log.exception("클립 예약이 실패했다 — %s", effect.event_id)

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
        # §5.3 이 `resolved_late` 를 실으면서 화면이 받은 숫자만으로 시정률을 검산할
        # 수 있게 됐다 — 네 버킷의 합이 `total_violations` 이고, 분자는 `resolved` 다.
        await self._publish(
            MetricMsg(
                period=summary.period,
                correction_rate=summary.correction_rate,
                undetermined_rate=summary.undetermined_rate,
                total_violations=summary.total_violations,
                resolved=summary.resolved,
                resolved_late=summary.resolved_late,
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
