"""시나리오를 서버 상태머신에 태워 **기대값과 자동으로 대조**한다.

    uv run tasks.py cases
    uv run tasks.py cases --case normal_resolve

시나리오 파일(`sim/cases/*.yaml`)에 `expect:` 블록이 있으면 그것이 이 시나리오의
정답이다. 눈으로 화면을 보고 "맞는 것 같다"고 판단하는 방식은 쓰지 않는다 —
「방송 후 시정률」은 이 프로젝트의 유일한 차별점이고, 그 숫자가 맞는지를 사람의
인상으로 확인하면 검증이 아니라 관측이 된다.

**엣지는 판단하지 않는다.** 여기서도 마찬가지다. 시나리오에는 관측된 사실
(`frame` · `candidate` · `track_lost`)만 적히고, 확정·해소·재결합·집계는 전부
`server/domain` 이 한다. `expect` 는 "서버가 이렇게 판정하기를 기대한다"는 뜻이다.

DB 도 서버도 띄우지 않는다. `EventService` 에 메모리 저장소를 물리고 `FakeClock` 으로
시간을 감으므로 3초·10초·15초·30초 타이머가 실시간을 기다리지 않는다.

`expect` 형식:

```yaml
expect:
  tail_s: 20.0            # 마지막 메시지 뒤로 더 흘려보낼 시간 (기본 0.5)
  events:                   # 남아 있어야 할 이벤트 **전량**. 하나라도 더 있으면 실패다
    - track_id: 3           # 재결합했다면 **바뀐 뒤**의 트랙 번호
      violation_type: no_helmet
      status: resolved
      alert_count: 1        # 선택
      zone_id: forklift_lane  # 선택
      confirmed_at_s: 3.5   # 선택 — 시나리오 시작 기준 초 (±0.3)
      alerted_at_s: 3.5     # 선택
      resolved_at_s: 16.0   # 선택
      resolution_sec: 12    # 선택 (±1 허용)
  metrics:
    correction_rate: 1.0
    undetermined_rate: 0.0
    total_violations: 1
    resolved: 1
    unresolved: 0
    undetermined: 0
    fall_events: 0

manual:                     # 선택 — FN-EVT-05 수동 정정
  - at: 30.0
    match: {track_id: 3, violation_type: fall}
    patch: {is_false_positive: true}
```
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from aegis_contracts import (
    CandidateMsg,
    EventDetail,
    EventPatchRequest,
    EventStatus,
    EventSummary,
    FrameMsg,
    MetricsSummary,
    Policies,
    SpecModel,
    TrackLostMsg,
    ViolationType,
)
from aegis_vision.clock import FakeClock
from server.app.event_service import EventService
from server.domain.event_machine import EventMachine, format_event_id
from server.domain.metrics import MetricsRow
from server.domain.overlay import LiveTracks

from .edge_sim.scripted import CASES_DIR, ScheduledMessage, load_case, resolve_case_path

__all__ = [
    "DEFAULT_TAIL_S",
    "TICK_S",
    "CaseResult",
    "CaseStore",
    "cases_with_expectations",
    "check_case",
    "run_case",
]

#: 상태머신에 시간을 흘려보내는 간격. 서버 런타임(`TICK_SECONDS` = 0.5초)보다 촘촘히
#: 돌려 유예 만료·쿨다운 시각이 틱 간격에 묻히지 않게 한다.
TICK_S = 0.25

#: 마지막 메시지 뒤로 더 흘려보낼 기본 시간. 관측이 끊긴 뒤의 전이(소실 → 유예 만료)를
#: 보려면 이 값을 시나리오에서 늘린다.
DEFAULT_TAIL_S = 0.5

#: 시각 비교 허용 오차(초). 프레임이 8fps(0.125초)로 들어오므로 전이 시각은 그
#: 격자에 걸린다. 격자보다 넉넉하되 1초 타이머 차이는 잡아내는 값이다.
TIME_TOLERANCE_S = 0.3

#: `resolution_sec` 은 초 단위 반올림이라 경계에서 ±1 이 갈린다.
DURATION_TOLERANCE_S = 1

#: 비율 비교 허용 오차.
RATE_TOLERANCE = 1e-6


class CaseStore:
    """메모리 이벤트 저장소. `EventService` 가 요구하는 것만 구현한다."""

    def __init__(self) -> None:
        self.events: dict[str, EventDetail] = {}
        self.deleted: list[str] = []
        self.false_positive: set[str] = set()
        self._sequence = 0

    async def find_open_all(self) -> list[EventSummary]:
        # 시나리오는 항상 빈 상태에서 시작한다. 재시작 복구는 여기서 볼 것이 없다.
        return []

    async def next_event_id(self, at: datetime) -> str:
        self._sequence += 1
        return format_event_id(at, self._sequence)

    async def create(self, event: EventDetail) -> None:
        self.events[event.event_id] = event

    async def update(self, event_id: str, changes: Mapping[str, Any]) -> None:
        event = self.events.get(event_id)
        if event is None:
            return
        patch = dict(changes)
        # DB 컬럼 이름과 계약 모델 필드가 다른 것들은 여기서 흡수한다. 상태머신은
        # DB 컬럼 이름으로 말하고(`status` 는 문자열), 계약 모델은 열거형을 쓴다.
        if "status" in patch:
            patch["status"] = EventStatus(patch["status"])
        if patch.pop("is_false_positive", False):
            # `EventDetail`(§4.1 응답)에는 이 필드가 없다. DB `events` 컬럼이므로
            # 저장소 쪽에서 기억하고 지표 집계에만 쓴다.
            self.false_positive.add(event_id)
        for key in ("prev_track_ids", "reassoc_count", "lost_at", "expired_at"):
            patch.pop(key, None)
        self.events[event_id] = event.model_copy(update=patch)

    async def delete(self, event_id: str) -> None:
        self.deleted.append(event_id)
        self.events.pop(event_id, None)

    async def get(self, event_id: str) -> EventDetail | None:
        return self.events.get(event_id)

    async def metrics_rows(self, from_: datetime | None, to: datetime | None) -> list[MetricsRow]:
        return [
            MetricsRow(
                violation_type=event.violation_type,
                status=event.status,
                resolution_sec=event.resolution_sec,
                is_false_positive=event.event_id in self.false_positive,
            )
            for event in self.events.values()
            if (from_ is None or event.detected_at >= from_)
            and (to is None or event.detected_at <= to)
        ]


@dataclass(frozen=True, slots=True)
class CaseResult:
    """시나리오 한 편을 끝까지 돌린 결과."""

    name: str
    events: list[EventDetail]
    metrics: MetricsSummary
    published: list[SpecModel]
    start: datetime
    machine: EventMachine = field(repr=False)

    def offset_s(self, at: datetime | None) -> float | None:
        return None if at is None else (at - self.start).total_seconds()


def cases_with_expectations() -> list[str]:
    """`expect:` 가 적힌 시나리오 이름들. 기대값이 없는 파일은 대조 대상이 아니다."""
    found: list[str] = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("expect"), dict):
            found.append(path.stem)
    return found


def _spec(case: str) -> dict[str, Any]:
    path: Path = resolve_case_path(case)
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"시나리오 최상위는 매핑이어야 한다: {path}"
        raise ValueError(msg)
    return raw


async def run_case(case: str) -> CaseResult:
    """시나리오를 상태머신에 태우고 결과를 돌려준다."""
    raw = _spec(case)
    expect: dict[str, Any] = raw.get("expect") or {}
    tail_s = float(expect.get("tail_s", DEFAULT_TAIL_S))

    clock = FakeClock()
    start = clock.now()
    timeline = load_case(case, start)

    store = CaseStore()
    published: list[SpecModel] = []

    async def publish(message: SpecModel) -> None:
        published.append(message)

    # DB 를 띄우지 않으므로 계약 기본값을 쓴다. 그 값이 곧 `scripts/seed_policies.py`
    # 가 DB 에 넣는 값이므로 실서버와 같은 임계값으로 판정된다(절대규칙 6).
    machine = EventMachine(clock=clock, policies=Policies())
    service = EventService(
        machine=machine,
        tracks=LiveTracks(),
        publish=publish,
        clock=clock,
        store=store,
        policies=None,
    )

    manual = list(raw.get("manual") or [])
    last_at = max((item.at_s for item in timeline), default=0.0)
    manual_end = max((float(item.get("at", 0.0)) for item in manual), default=0.0)
    end_s = max(last_at, manual_end) + tail_s

    for at_s in _grid(timeline, manual, end_s):
        clock.set(start + timedelta(seconds=at_s))
        for item in _due(timeline, at_s):
            await _dispatch(service, item)
        for entry in _due_manual(manual, at_s):
            await _apply_manual(service, store, entry)
        await service.tick()

    return CaseResult(
        name=str(raw.get("name", case)),
        events=sorted(store.events.values(), key=lambda event: event.event_id),
        metrics=await service.summary(),
        published=published,
        start=start,
        machine=machine,
    )


def check_case(case: str, result: CaseResult) -> list[str]:
    """기대값과 대조한다. 어긋난 것들을 사람이 읽을 문장으로 돌려준다(없으면 빈 목록)."""
    expect: dict[str, Any] = _spec(case).get("expect") or {}
    problems: list[str] = []
    problems += _check_events(expect.get("events") or [], result)
    problems += _check_metrics(expect.get("metrics") or {}, result.metrics)
    return problems


# --------------------------------------------------------------------------
# 내부
# --------------------------------------------------------------------------


def _grid(
    timeline: Sequence[ScheduledMessage],
    manual: Sequence[Mapping[str, Any]],
    end_s: float,
) -> Iterator[float]:
    """메시지 시각과 틱 격자를 시각 순으로 합친다."""
    moments = {round(item.at_s, 6) for item in timeline}
    moments |= {round(float(entry.get("at", 0.0)), 6) for entry in manual}
    step = 0
    while step * TICK_S <= end_s:
        moments.add(round(step * TICK_S, 6))
        step += 1
    return iter(sorted(moments))


def _due(timeline: list[ScheduledMessage], at_s: float) -> list[ScheduledMessage]:
    return [item for item in timeline if abs(item.at_s - at_s) < 1e-9]


def _due_manual(manual: list[Mapping[str, Any]], at_s: float) -> list[Mapping[str, Any]]:
    return [entry for entry in manual if abs(float(entry.get("at", 0.0)) - at_s) < 1e-9]


async def _dispatch(service: EventService, item: ScheduledMessage) -> None:
    message = item.message
    if isinstance(message, FrameMsg):
        await service.on_frame(message)
    elif isinstance(message, CandidateMsg):
        await service.on_candidate(message)
    elif isinstance(message, TrackLostMsg):
        await service.on_track_lost(message)
    # heartbeat 는 상태머신의 입력이 아니다(§2.4 는 장비 상태 보고다).


async def _apply_manual(
    service: EventService,
    store: CaseStore,
    entry: Mapping[str, Any],
) -> None:
    """FN-EVT-05 — 관리자가 화면에서 누르는 것을 그대로 흉내 낸다."""
    match: Mapping[str, Any] = entry.get("match") or {}
    target = next(
        (
            event
            for event in store.events.values()
            if all(_matches(event, key, value) for key, value in match.items())
        ),
        None,
    )
    if target is None:
        msg = f"수동 정정 대상 이벤트를 찾지 못했다: {dict(match)}"
        raise ValueError(msg)
    del store  # 오탐 표시는 저장소가 `update` 에서 받아 기억한다.
    request = EventPatchRequest.model_validate(dict(entry.get("patch") or {}))
    await service.patch(target.event_id, request)


def _matches(event: EventDetail, key: str, value: Any) -> bool:
    actual = getattr(event, key)
    if isinstance(actual, ViolationType | EventStatus):
        return bool(actual.value == value)
    return bool(actual == value)


def _check_events(expected: list[Any], result: CaseResult) -> list[str]:
    problems: list[str] = []
    remaining = list(result.events)
    for want in expected:
        found = next(
            (
                event
                for event in remaining
                if event.track_id == want.get("track_id")
                and event.violation_type.value == want.get("violation_type")
            ),
            None,
        )
        if found is None:
            problems.append(
                f"기대한 이벤트가 없다: track={want.get('track_id')} "
                f"type={want.get('violation_type')}"
            )
            continue
        remaining.remove(found)
        problems += _check_event(want, found, result)

    for leftover in remaining:
        problems.append(
            f"기대하지 않은 이벤트가 남았다: {leftover.event_id} "
            f"track={leftover.track_id} type={leftover.violation_type.value} "
            f"status={leftover.status.value}"
        )
    return problems


def _check_event(want: Mapping[str, Any], got: EventDetail, result: CaseResult) -> list[str]:
    problems: list[str] = []
    label = f"{got.event_id}({got.violation_type.value})"

    if "status" in want and got.status.value != want["status"]:
        problems.append(f"{label} status: 기대 {want['status']} · 실제 {got.status.value}")
    for key in ("alert_count", "zone_id"):
        if key in want and getattr(got, key) != want[key]:
            problems.append(f"{label} {key}: 기대 {want[key]} · 실제 {getattr(got, key)}")

    if "resolution_sec" in want:
        actual = got.resolution_sec
        wanted = want["resolution_sec"]
        if actual is None or abs(actual - wanted) > DURATION_TOLERANCE_S:
            problems.append(
                f"{label} resolution_sec: 기대 {wanted}±{DURATION_TOLERANCE_S} · 실제 {actual}"
            )

    for key, field_name in (
        ("confirmed_at_s", "confirmed_at"),
        ("alerted_at_s", "alerted_at"),
        ("resolved_at_s", "resolved_at"),
    ):
        if key not in want:
            continue
        actual_s = result.offset_s(getattr(got, field_name))
        wanted_s = float(want[key])
        if actual_s is None or abs(actual_s - wanted_s) > TIME_TOLERANCE_S:
            problems.append(
                f"{label} {field_name}: 기대 +{wanted_s:.2f}s±{TIME_TOLERANCE_S} · "
                f"실제 {'없음' if actual_s is None else f'+{actual_s:.2f}s'}"
            )
    return problems


def _check_metrics(expected: Mapping[str, Any], got: MetricsSummary) -> list[str]:
    problems: list[str] = []
    for key, wanted in expected.items():
        actual = getattr(got, key, None)
        if actual is None:
            problems.append(f"지표에 없는 항목이다: {key}")
            continue
        if isinstance(wanted, float) or isinstance(actual, float):
            if abs(float(actual) - float(wanted)) > RATE_TOLERANCE:
                problems.append(f"지표 {key}: 기대 {wanted} · 실제 {actual}")
        elif actual != wanted:
            problems.append(f"지표 {key}: 기대 {wanted} · 실제 {actual}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """`uv run tasks.py cases` 의 알맹이. 결과를 표로 찍고 하나라도 어긋나면 1을 낸다."""
    import argparse
    import io
    import sys

    # `tasks.py cases` 가 이 모듈을 자식으로 돌리면 출력이 파이프가 되고, 그때 파이썬은
    # 콘솔 코드페이지가 아니라 로케일 인코딩(한글 Windows 는 cp949)을 쓴다. 그러면
    # '—' 하나에 UnicodeEncodeError 로 죽어 **검사가 시작도 못 한 채 실패**한다.
    # tasks.py · sim/edge_sim/main.py 와 같은 처리다.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="시나리오 기대값 자동 대조")
    parser.add_argument("--case", default=None, help="이 시나리오만 검사 (기본: 전부)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    names = [args.case] if args.case else cases_with_expectations()
    if not names:
        print("expect 블록이 있는 시나리오가 없다.")
        return 1

    failed = 0
    print(
        f"{'시나리오':<20} {'시정률':>8} {'판정불가율':>10} {'해소':>4} {'미시정':>6} "
        f"{'판정불가':>8} {'쓰러짐':>6}  결과"
    )
    for name in names:
        result = asyncio.run(run_case(name))
        problems = check_case(name, result)
        failed += bool(problems)
        metrics = result.metrics
        print(
            f"{name:<20} {metrics.correction_rate:>8.2f} {metrics.undetermined_rate:>10.2f} "
            f"{metrics.resolved:>4} {metrics.unresolved:>6} {metrics.undetermined:>8} "
            f"{metrics.fall_events:>6}  {'OK' if not problems else 'FAIL'}"
        )
        for problem in problems:
            print(f"    - {problem}")

    print()
    print(f"{len(names)}개 중 {len(names) - failed}개 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
