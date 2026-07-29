"""명세서 갱신분(v10) 반영 확인.

직전 마일스톤에서 「명세서 확인 필요」로 올렸던 것들이 명세서에서 정해졌다. 여기서는
**그 결론이 코드에 남아 있는지**를 잠근다 — 나중에 되돌아가는 것을 막기 위한 회귀
테스트이며, 각 항목은 되돌아갔을 때 무엇이 망가지는지를 함께 적는다.

| 항목 | 결론 |
|---|---|
| §4.8 시정률 식 | `resolved / (resolved + resolved_late + unresolved)` — §6.7 과 통일 |
| §4.2 판정 불가율 분모 | `resolved_late` 포함 — 늦은 시정은 모집단이지 판정 불가가 아니다 |
| §5.3 `metric` | `resolved_late` 추가 — 화면이 받은 숫자만으로 검산할 수 있다 |
| §4.1 `GET /events/{id}` | `last_alerted_at` · `note` 추가 — 저장만 되고 못 읽던 것이 끝났다 |
| §6 `events` | `dropped_at` 추가 — 종결 시각 셋이 모두 생겼다 |
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from aegis_contracts import (
    EventDetail,
    EventStatus,
    MetricMsg,
    Policies,
    SpecModel,
    ViolationType,
)
from aegis_vision.clock import FakeClock
from server.app.event_service import EventService
from server.domain.event_machine import EventMachine
from server.domain.metrics import MetricsRow, summarize
from server.domain.overlay import LiveTracks
from server.infra.db.models import Event as EventRow
from server.infra.db.repository import _timeline

from .conftest import FakeEventStore

NOW = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)


def test_late_resolutions_sit_in_the_denominator_of_both_rates() -> None:
    """§4.8 · §4.2 · §6.7 — 세 절의 식이 이제 같다.

    `resolved_late` 를 분모에서 빼면 시정률이 부풀려지고, 판정 불가율 분모에서 빼면
    "늦게라도 시정한 건"이 판정 불가와 같은 취급을 받는다. 둘 다 방어할 수 없다.
    """
    rows = [
        MetricsRow(ViolationType.NO_HELMET, EventStatus.RESOLVED, 12, False),
        MetricsRow(ViolationType.NO_HELMET, EventStatus.RESOLVED, 400, False),  # 창(300초) 초과
        MetricsRow(ViolationType.NO_HELMET, EventStatus.ALERTED, None, False),
        MetricsRow(ViolationType.NO_HELMET, EventStatus.EXPIRED, None, False),
    ]

    summary = summarize(rows, period="today", resolve_window_s=Policies().resolve_window_s)

    assert (summary.resolved, summary.resolved_late, summary.unresolved) == (1, 1, 1)
    assert summary.correction_rate == 1 / 3
    assert summary.undetermined_rate == 1 / 4
    assert summary.total_violations == 4


def test_the_metric_message_carries_resolved_late() -> None:
    """§5.3 — 화면이 받은 숫자만으로 시정률을 검산할 수 있어야 한다."""
    assert "resolved_late" in MetricMsg.model_fields

    store = FakeEventStore()
    published: list[SpecModel] = []

    async def publish(message: SpecModel) -> None:
        published.append(message)

    service = EventService(
        machine=EventMachine(clock=FakeClock(NOW), policies=Policies()),
        tracks=LiveTracks(),
        publish=publish,
        clock=FakeClock(NOW),
        store=store,
    )
    # 발행 페이로드를 직접 본다 — 대시보드가 실제로 받는 모양이 검증 대상이다.
    asyncio.run(service._publish_metric())

    message = published[0]
    assert isinstance(message, MetricMsg)
    denominator = message.resolved + message.resolved_late + message.unresolved
    assert denominator + message.undetermined == message.total_violations


def test_dropped_events_now_have_a_closing_time_in_the_timeline() -> None:
    """§6 `dropped_at` — 종결 셋(`resolved` · `expired` · `dropped`)이 모두 끝을 갖는다.

    없으면 §4.1 `timeline` 이 `candidate` 에서 끝나 "이 후보가 언제 사라졌는지"를 알
    수 없고, `confirm_duration_s` 튜닝 근거인 소멸까지의 시간도 잴 수 없다.
    """
    row = EventRow(
        event_id="EV-1",
        cam_id=1,
        track_id=3,
        violation_type="no_helmet",
        status="dropped",
        detected_at=NOW,
        dropped_at=NOW + timedelta(seconds=5),
    )

    timeline = _timeline(row)

    assert [entry.state for entry in timeline] == [EventStatus.CANDIDATE, EventStatus.DROPPED]
    assert timeline[-1].at == NOW + timedelta(seconds=5)


def test_the_state_machine_stamps_dropped_at() -> None:
    """확정 전 소멸이 시각과 함께 기록된다."""
    clock = FakeClock(NOW)
    machine = EventMachine(clock=clock, policies=Policies())
    from .test_event_service import candidate  # 시나리오와 같은 후보 하나

    machine.on_candidate(candidate(0.0), event_id="EV-1")
    effects = machine.tick(NOW + timedelta(seconds=60))

    dropped = [e for e in effects if e.changes.get("status") == EventStatus.DROPPED.value]
    assert dropped, "확정 전 후보가 dropped 로 종결되어야 한다"
    assert dropped[0].changes["dropped_at"] is not None


def test_restore_uses_the_stored_last_alerted_at() -> None:
    """§4.1 이 `last_alerted_at` 을 응답에 실으면서 복구가 정확해졌다.

    예전에는 `alerted_at`(최초)으로 대신 채웠는데, 재경고를 여러 번 한 이벤트는 재시작
    직후 쿨다운을 이미 넘긴 것으로 보여 **복구하자마자 재경고가 나갔다.**
    """
    clock = FakeClock(NOW)
    machine = EventMachine(clock=clock, policies=Policies())
    alerted_at = NOW - timedelta(minutes=10)
    recent = NOW - timedelta(seconds=5)

    summary = FakeEventStore(
        [
            _summary_with(alerted_at=alerted_at, last_alerted_at=recent),
        ]
    )
    machine.restore(asyncio.run(summary.find_open_all()), NOW)

    (event,) = machine.snapshot()
    assert event.alerted_at == alerted_at
    assert event.last_alerted_at == recent


def _summary_with(*, alerted_at: datetime, last_alerted_at: datetime) -> EventDetail:
    from .test_metrics_api import event

    return event("EV-1", EventStatus.ALERTED).model_copy(
        update={"alerted_at": alerted_at, "last_alerted_at": last_alerted_at}
    )
