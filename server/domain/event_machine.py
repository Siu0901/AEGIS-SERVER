"""이벤트 상태머신 — FN-EVT-01 ~ FN-EVT-07 (기능명세서 §4.2).

```
candidate ─→ active ─→ alerted ⇄ re_alerted
    │                     │           │
    │                     └─────┬─────┘
    │                           ↓
    │                         lost ──재결합 성공──→ 직전 상태로 복귀
    │                           │                  (해소 타이머는 0부터 재시작)
    │                           └──유예 만료──→ expired (판정 불가)
    │
    └──확정 전 조건 소멸──→ dropped (지표 전량 제외 · 진단용으로 보존)

            alerted / re_alerted ──위반 소멸 지속──→ resolved (시정 성공)
```

**I/O 가 없다**(CLAUDE.md 절대규칙 2). 여기서 나오는 것은 `Effect` — "무엇을 만들고,
무엇을 갱신하고, 무엇을 대시보드에 알릴지"라는 판단이다. 실제 저장과 발행은
`server/app/event_service.py` 가 한다.

**시간을 직접 읽지 않는다**(절대규칙 1). `Clock` 을 주입받고, 그마저도 타이머 적산에는
쓰지 않는다 — 적산 기준은 **관측 시각**(`frame.ts` · `candidate.ts`)이다. 서버 수신
시각을 쓰면 네트워크 지연이 시정 소요 시간에 섞이고, 그 값이 곧 시정률이 된다.

**임계값을 하드코딩하지 않는다**(절대규칙 6). 전부 `Policies`(DB `policies`)에서 온다.

이 모듈이 지키는 규칙 중 지표 신뢰성에 직결되는 것들:

* **타이머는 관측이 있을 때만 흐른다.** 사람이 보이지 않는 구간에서 해소 타이머가
  차오르면, 그냥 사라진 사람이 "시정했다"로 집계된다.
* **게이팅 보류 구간에서는 타이머를 초기화하지 않고 멈춘다**(§6.3). 초기화하면
  조건이 영원히 충족되지 않는다.
* **재결합은 이벤트를 살리는 처리이지 시정을 인정하는 처리가 아니다**(FN-EVT-07 ③).
  복귀 후 위반이 사라져 보여도 해소 타이머를 0부터 다시 채운다.
* **확정되지 않은 후보는 `dropped` 로 종결한다**(§4.2). 지우지 않는다 —
  `dropped / (dropped + 확정)` 비율이 `confirm_duration_s` 튜닝의 유일한 근거다.
  `dropped` 는 종결 상태이므로 병합 키(FN-EVT-01)를 점유하지 않는다.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from aegis_contracts import (
    CandidateMsg,
    DetectedPerson,
    DetectedVehicle,
    EventCreatedMsg,
    EventDetail,
    EventStatus,
    EventSummary,
    EventUpdatedMsg,
    FrameMsg,
    Policies,
    SpecModel,
    TrackLostMsg,
    ViolationType,
)
from aegis_contracts.enums import AlertLevel, Posture
from aegis_vision.clock import Clock
from server.domain.alerts import AlertIntent
from server.domain.reassociation import LostTrack, match_lost_track

__all__ = [
    "EVENT_ID_PREFIX",
    "SEVERITY",
    "CandidatePlan",
    "Effect",
    "EventMachine",
    "Judgement",
    "OpenEvent",
    "build_candidate_event",
    "format_event_id",
    "merge_changes",
    "plan_candidate",
]

#: 이벤트 ID 접두사. 기능명세서 §6 — `EV-YYYYMMDD-NNNN`.
EVENT_ID_PREFIX = "EV"

#: 위반 유형별 위험 등급. API명세서 §3 `AlertCommand.level` · §5.2 `severity` — 같은 값.
#:
#: 명세서가 못박은 것은 **`fall` = 3(긴급)** 하나이고 §3 예시가 `no_helmet` = 2 다.
#: 나머지 둘은 같은 「경고」 급으로 둔다. 1(주의)은 위반이 아닌 이상 탐지(FN-AI-04)의
#: 자리이며, 이상 탐지는 애초에 경고를 발동하지 않는다.
SEVERITY: Mapping[ViolationType, AlertLevel] = {
    ViolationType.NO_HELMET: 2,
    ViolationType.ZONE_INTRUSION: 2,
    ViolationType.PROXIMITY: 2,
    ViolationType.FALL: 3,
}

#: 한 관측 시점의 판정. `gated` 는 "판정할 수 없다"이지 "위반이 없다"가 아니다(§6.3).
Judgement = Literal["violating", "cleared", "gated"]


# --------------------------------------------------------------------------
# FN-EVT-01 · 후보 병합
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidatePlan:
    """후보 한 건을 어떻게 처리할지. 위반 유형 단위로 갈린다."""

    creates: tuple[ViolationType, ...]
    """진행 중인 이벤트가 없어 새로 만들 위반 유형."""

    updates: tuple[tuple[ViolationType, str], ...]
    """이미 있어 갱신할 (위반 유형, `event_id`). **새로 만들지 않는다**(FN-EVT-01)."""


def plan_candidate(
    candidate: CandidateMsg,
    open_events: Mapping[ViolationType, str],
) -> CandidatePlan:
    """FN-EVT-01 — 후보를 진행 중 이벤트에 병합하거나 새로 만든다.

    Args:
        candidate: 엣지가 올린 후보(§2.2). **위반 유형 하나를 나른다.**
        open_events: 같은 `cam_id` · `track_id` 에 대해 이미 진행 중인
            {위반 유형: `event_id`}.

    한 트랙에 유형이 여럿 걸리면 후보 메시지가 유형 수만큼 따로 온다(§2.2). 그래도
    이벤트는 유형별로 갈린다 — 안전모 미착용과 구역 침입은 시정 행동도 규정 조항도
    달라서 한 건으로 묶으면 시정률의 의미가 무너진다.
    """
    violation = candidate.violation_type
    existing = open_events.get(violation)
    if existing is None:
        return CandidatePlan(creates=(violation,), updates=())
    return CandidatePlan(creates=(), updates=((violation, existing),))


def format_event_id(at: datetime, sequence: int) -> str:
    """`EV-YYYYMMDD-NNNN`. 기능명세서 §6

    날짜는 **UTC** 기준이다 — 저장이 UTC 이므로(§1.2) 로컬 자정으로 끊으면 같은
    날짜 접두사가 서로 다른 두 날에 걸친다.
    """
    return f"{EVENT_ID_PREFIX}-{at.strftime('%Y%m%d')}-{sequence:04d}"


def build_candidate_event(
    candidate: CandidateMsg,
    violation: ViolationType,
    event_id: str,
) -> EventDetail:
    """후보에서 **아직 확정되지 않은** 이벤트 레코드 하나를 만든다. FN-REC-04

    `status` 는 `candidate` 에 머문다. 확정은 `EventMachine` 이 `confirm_duration_s`
    를 채운 뒤에 하며, 그 전에 `confirmed_at` · `alerted_at` 을 채우면 시정률의 분모가
    오염된다.

    `detected_at` 은 **후보를 관측한 시각**(`candidate.ts`)이지 서버가 받은 시각이
    아니다 — 서버 수신 시각을 쓰면 네트워크 지연이 시정 소요 시간에 섞인다(§4.1).
    """
    return EventDetail(
        event_id=event_id,
        cam_id=candidate.cam_id,
        track_id=candidate.track_id,
        violation_type=violation,
        zone_id=candidate.zone_id,
        status=EventStatus.CANDIDATE,
        detected_at=candidate.ts,
        confirmed_at=None,
        alerted_at=None,
        last_alerted_at=None,
        note=None,
        resolved_at=None,
        resolution_sec=None,
        alert_count=0,
        min_distance_m=_min_distance(candidate),
        posture=candidate.posture,
        # FN-EVT-06(반복 위반 집계)은 읽을 때 저장소가 세어 채운다.
        repeat_count_7d=0,
        thumbnail_url=None,
        clip_url=None,
        keyframe_urls=[],
        helmet_conf=candidate.helmet_conf,
        stillness_s=None,
        height_ratio=None,
        depth_verified=_depth_verified(candidate),
        nearby_snapshot=[],
        llm_analysis=None,
        regulation_refs=[],
        similar_incidents=[],
        timeline=[],
    )


# --------------------------------------------------------------------------
# 상태머신
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Effect:
    """상태머신이 바깥에 시키는 일 한 건. 순서대로 적용한다."""

    action: Literal["create", "update"]
    """`delete` 는 없다 — 확정 전 소멸도 `dropped` 로 **갱신**해 레코드를 남긴다(§4.2)."""
    event_id: str
    cam_id: int
    track_id: int
    """전이가 일어난 시점의 트랙. 오버레이(§5.1)의 어느 박스를 다시 그릴지 정한다."""
    event: EventDetail | None = None
    """`create` 일 때의 레코드."""
    changes: Mapping[str, Any] = field(default_factory=dict)
    """`update` 일 때 DB 에 쓸 컬럼들."""
    message: SpecModel | None = None
    """대시보드에 내보낼 §5.2 메시지. 없으면 알릴 것이 없는 갱신이다."""
    alert: AlertIntent | None = None
    """지금 소리를 내고 경광등을 켜라는 지시(FN-ALM-01 · 02). 확정·재경고에만 실린다.

    **이 자리를 상태 문자열로 대신하지 않는다.** 집행 계층이 `changes["status"]` 를 보고
    "alerted 니까 경고겠지"라고 되짚으면, 재시작 복구처럼 상태만 다시 쓰는 경로에서도
    방송이 나간다 — 이미 지나간 위반에 뒤늦게 스피커가 울리는 것이 그 결과다.
    """
    note: str = ""
    """사람이 읽을 한 줄. 로그로 나간다."""


@dataclass(slots=True)
class OpenEvent:
    """진행 중인 이벤트 하나의 런타임 상태.

    DB 레코드와 별개로 **타이머**를 들고 있다. 타이머를 DB 에 두면 후보 빈도(초당
    여러 번)만큼 쓰기가 발생하고, 그렇다고 매번 읽으면 판정이 DB 왕복에 묶인다.
    """

    event_id: str
    cam_id: int
    track_id: int
    violation_type: ViolationType
    status: EventStatus
    zone_id: str | None
    detected_at: datetime
    last_tick_at: datetime
    last_seen_at: datetime

    alerted_at: datetime | None = None
    """**최초** 경고 시각. `resolution_sec` 의 기준이며 재경고로 덮지 않는다."""
    last_alerted_at: datetime | None = None
    """**최근** 경고 시각. 쿨다운(FN-EVT-04) 기준이자 DB `events.last_alerted_at`(§6)."""
    lost_at: datetime | None = None
    status_before_lost: EventStatus | None = None

    alert_count: int = 0
    reassoc_count: int = 0
    prev_track_ids: list[int] = field(default_factory=list)

    min_distance_m: float | None = None
    posture: Posture | None = None

    violating: bool = True
    """마지막 관측에서 위반이 지속 중이었는가."""
    gated: bool = False
    """마지막 관측이 게이팅 보류였는가(§6.3). 이 구간의 시간은 적산하지 않는다."""
    observed_s: float = 0.0
    """확정 타이머 — 위반이 연속 관측된 시간."""
    cleared_s: float = 0.0
    """해소 타이머 — 위반이 사라진 상태가 지속된 시간."""


class EventMachine:
    """진행 중인 이벤트 전량의 상태를 들고 있는 순수 상태머신.

    입력은 엣지 메시지 셋(`candidate` · `frame` · `track_lost`)과 시간의 흐름(`tick`)
    이고, 출력은 `Effect` 목록이다. 저장·발행·로깅은 전부 호출자의 몫이다.
    """

    def __init__(self, *, clock: Clock, policies: Policies) -> None:
        self._clock = clock
        self._policies = policies
        self._events: dict[str, OpenEvent] = {}
        self._by_track: dict[tuple[int, int], dict[ViolationType, str]] = {}
        self._seen: dict[tuple[int, int], datetime] = {}
        self._foot: dict[tuple[int, int], tuple[float, float]] = {}
        self._helmet_checked: dict[tuple[int, int], datetime] = {}

    # -- 정책 · 조회 ----------------------------------------------------

    @property
    def policies(self) -> Policies:
        return self._policies

    def set_policies(self, policies: Policies) -> None:
        """`PATCH /policies` 이후 반영. 진행 중인 타이머는 새 값으로 판정된다."""
        self._policies = policies

    @property
    def _miss_s(self) -> float:
        """이 시간 이상 트랙이 관측되지 않으면 **소실**로 본다. FN-EVT-07 ①

        `track_miss_timeout_ms`(기본 1500ms · §4.5)다. 엣지가 `track_lost` 를 보내지
        못하고 끊긴 경우의 대비책이며, **표시용 키인 `overlay_stale_ms` 와 혼용하지
        않는다** — 박스를 흐리게 그릴 시점과 이벤트를 `lost` 로 보낼 시점은 튜닝
        이유가 다르다.
        """
        return self._policies.track_miss_timeout_ms / 1000.0

    def open_events(
        self, cam_id: int, track_id: int
    ) -> dict[ViolationType, tuple[str, EventStatus]]:
        """이 트랙에 붙어 있는 진행 중 이벤트. 오버레이(§5.1)가 읽는다."""
        return {
            violation: (event_id, self._events[event_id].status)
            for violation, event_id in self._by_track.get((cam_id, track_id), {}).items()
        }

    def snapshot(self) -> list[OpenEvent]:
        """진행 중인 이벤트 전량. 진단·테스트용."""
        return list(self._events.values())

    def restore(self, events: Iterable[EventSummary], at: datetime) -> None:
        """서버 재시작 시 열려 있던 이벤트를 상태머신에 되살린다.

        되살리지 않으면 그 이벤트들은 영원히 종결되지 않아 시정률 분모에 미해소로
        남는다 — 재시작 한 번이 지표를 통째로 왜곡한다.

        타이머는 **0부터 다시 채운다.** 재시작 전 얼마나 관측했는지는 DB 에 없고,
        모르는 값을 추정해 채우면 확정·해소가 관측 없이 일어난다. `lost` 의 유예도
        `at` 부터 다시 센다(더 늦게 종결되는 쪽이 안전하다).

        쿨다운 기준(`last_alerted_at`)은 **저장된 값 그대로** 쓴다. §4.1 응답에 그 칸이
        생기기 전에는 `alerted_at`(최초)으로 대신 채웠는데, 그러면 재경고를 여러 번 한
        이벤트가 재시작 직후 쿨다운을 이미 넘긴 것으로 보여 **복구하자마자 재경고가
        나갔다.** 값이 비어 있을 때만(경고 전이었거나 구버전 행) `alerted_at` 으로
        떨어진다 — 그쪽은 재경고가 늦어지는 방향으로만 틀린다.
        """
        for summary in events:
            if summary.status not in _OPEN_STATUSES:
                continue
            event = OpenEvent(
                event_id=summary.event_id,
                cam_id=summary.cam_id,
                track_id=summary.track_id,
                violation_type=summary.violation_type,
                status=summary.status,
                zone_id=summary.zone_id,
                detected_at=summary.detected_at,
                last_tick_at=at,
                last_seen_at=at,
                alerted_at=summary.alerted_at,
                last_alerted_at=summary.last_alerted_at or summary.alerted_at,
                lost_at=at if summary.status is EventStatus.LOST else None,
                status_before_lost=(
                    EventStatus.ALERTED if summary.status is EventStatus.LOST else None
                ),
                alert_count=summary.alert_count,
                min_distance_m=summary.min_distance_m,
                posture=summary.posture,
            )
            self._register(event)

    # -- 입력: candidate ------------------------------------------------

    def needs_event_id(self, candidate: CandidateMsg) -> bool:
        """새 이벤트를 만들어야 하는가. `event_id` 발급은 저장소의 일이라 먼저 묻는다."""
        key = (candidate.cam_id, candidate.track_id)
        return candidate.violation_type not in self._by_track.get(key, {})

    def on_candidate(self, candidate: CandidateMsg, event_id: str | None = None) -> list[Effect]:
        """FN-EVT-01 · FN-EVT-02 — 후보 한 건.

        Args:
            candidate: 엣지가 올린 후보(§2.2).
            event_id: `needs_event_id` 가 참일 때 저장소가 발급한 새 ID.
        """
        at = candidate.ts
        key = (candidate.cam_id, candidate.track_id)
        effects: list[Effect] = self._reassociate(key, at, candidate.foot_point_m)
        self._see(key, at, candidate.foot_point_m)

        existing = self._by_track.get(key, {}).get(candidate.violation_type)
        if existing is None:
            if event_id is None:
                msg = "새 이벤트를 만들어야 하는데 event_id 가 없다 (needs_event_id 를 먼저 물어라)"
                raise ValueError(msg)
            record = build_candidate_event(candidate, candidate.violation_type, event_id)
            event = OpenEvent(
                event_id=event_id,
                cam_id=candidate.cam_id,
                track_id=candidate.track_id,
                violation_type=candidate.violation_type,
                status=EventStatus.CANDIDATE,
                zone_id=candidate.zone_id,
                detected_at=at,
                last_tick_at=at,
                last_seen_at=at,
                min_distance_m=record.min_distance_m,
                posture=candidate.posture,
            )
            self._register(event)
            effects.append(
                Effect(
                    action="create",
                    event_id=event_id,
                    cam_id=event.cam_id,
                    track_id=event.track_id,
                    event=record,
                    note=(
                        f"이벤트 생성 {event_id} — cam={candidate.cam_id} "
                        f"track={candidate.track_id} type={candidate.violation_type.value}"
                    ),
                )
            )
        else:
            event = self._events[existing]
            changes = merge_changes(event, candidate)
            self._apply(event, changes)
            if changes:
                effects.append(
                    Effect(
                        action="update",
                        event_id=event.event_id,
                        cam_id=event.cam_id,
                        track_id=event.track_id,
                        changes=changes,
                    )
                )

        # 후보가 올라왔다는 것은 그 순간 규칙이 걸려 있었다는 뜻이다(§2.2).
        # `observed_ms`(엣지가 잰 연속 관측 시간)는 확정 판정에 쓰지 않는다 — 서버가
        # 자기 관측으로 확정 조건을 재는 것이 FN-EVT-02 이고, 엣지 값을 그대로 믿으면
        # 엣지 규칙이 바뀔 때 서버의 확정 기준까지 함께 흔들린다.
        self._observe(event, at, "violating")
        effects += self._evaluate(event, at)
        return effects

    # -- 입력: frame ----------------------------------------------------

    def on_frame(self, frame: FrameMsg) -> list[Effect]:
        """FN-EVT-03 — 프레임 한 장으로 진행 중 이벤트들의 위반 지속·소멸을 판정한다.

        해소 판정을 프레임으로 하는 이유: 후보는 규칙이 걸릴 때만 올라오므로(§2.2)
        "후보가 끊겼다"만으로는 위반이 사라진 것과 대상이 사라진 것을 구분할 수 없다.
        프레임에는 두 경우가 다르게 나타난다 — 전자는 트랙이 있고 조건이 풀린 것이고,
        후자는 트랙 자체가 없다.
        """
        at = frame.ts
        effects: list[Effect] = []
        vehicles = [obj for obj in frame.objects if isinstance(obj, DetectedVehicle)]
        for obj in frame.objects:
            if not isinstance(obj, DetectedPerson):
                continue
            key = (frame.cam_id, obj.track_id)
            effects += self._reassociate(key, at, obj.foot_point_m)
            self._see(key, at, obj.foot_point_m)
            gated = self._helmet_gate(key, obj)
            for event_id in list(self._by_track.get(key, {}).values()):
                event = self._events.get(event_id)
                if event is None or event.status is EventStatus.LOST:
                    continue
                self._observe(event, at, self._judge(event, obj, vehicles, gated=gated))
                effects += self._evaluate(event, at)
        return effects

    # -- 입력: track_lost -----------------------------------------------

    def on_track_lost(self, message: TrackLostMsg) -> list[Effect]:
        """FN-EVT-07 ① — 소실 유예. 즉시 종결하지 않는다.

        즉시 종결하면 세 가지가 한꺼번에 망가진다(기능명세서 §4.2): 시정하러 이동
        중 이탈한 건이 미집계되고(시정률 과소), 가림으로 끊긴 트랙이 새 이벤트로
        재생성되며(중복 경고), ID 스위치가 **가짜 시정**으로 집계된다(시정률 과대).
        """
        key = (message.cam_id, message.track_id)
        at = message.last_ts
        self._foot[key] = message.last_foot_point_m
        effects: list[Effect] = []
        for event_id in list(self._by_track.get(key, {}).values()):
            effects += self._to_lost(self._events[event_id], at)
        self._seen.pop(key, None)
        self._helmet_checked.pop(key, None)
        return effects

    # -- 시간의 흐름 ----------------------------------------------------

    def tick(self, now: datetime | None = None) -> list[Effect]:
        """관측이 없어도 흘러야 하는 것들 — 소실 감지 · 유예 만료 · 쿨다운.

        **타이머(확정 · 해소)는 여기서 흐르지 않는다.** 그 둘은 관측이 있어야 흐르며,
        관측 없이 차오르면 사라진 사람이 시정한 것으로 집계된다.
        """
        at = now if now is not None else self._clock.now()
        effects: list[Effect] = []
        for event in list(self._events.values()):
            if event.status is EventStatus.LOST:
                if event.lost_at is not None and _elapsed(event.lost_at, at) >= (
                    self._policies.track_lost_grace_s
                ):
                    effects += self._to_expired(event, at)
                continue
            if _elapsed(event.last_seen_at, at) > self._miss_s:
                effects += self._to_lost(event, at)
                continue
            effects += self._evaluate(event, at)
        self._prune(at)
        return effects

    # -- 수동 정정 (FN-EVT-05) -------------------------------------------

    def forget(self, event_id: str) -> None:
        """이벤트를 상태머신에서 내린다. 바깥에서 종결시켰을 때(수동 정정) 쓴다."""
        event = self._events.pop(event_id, None)
        if event is None:
            return
        slot = self._by_track.get((event.cam_id, event.track_id))
        if slot is not None:
            slot.pop(event.violation_type, None)
            if not slot:
                self._by_track.pop((event.cam_id, event.track_id), None)

    # ------------------------------------------------------------------
    # 내부 — 등록 · 관측
    # ------------------------------------------------------------------

    def _register(self, event: OpenEvent) -> None:
        self._events[event.event_id] = event
        slot = self._by_track.setdefault((event.cam_id, event.track_id), {})
        slot[event.violation_type] = event.event_id

    def _close(self, event: OpenEvent) -> None:
        self.forget(event.event_id)

    def _see(self, key: tuple[int, int], at: datetime, foot_point_m: tuple[float, float]) -> None:
        self._seen[key] = at
        self._foot[key] = foot_point_m
        for event_id in self._by_track.get(key, {}).values():
            self._events[event_id].last_seen_at = at

    def _helmet_gate(self, key: tuple[int, int], person: DetectedPerson) -> bool:
        """게이팅 보류인가. API명세서 §6.3

        | 상황 | `frame` | 판정 |
        |---|---|---|
        | 게이트 통과 | `helmet` · `helmet_checked_at` 갱신 | 정상 |
        | 미통과 · 캐시 있음 | 직전 `helmet` 유지, `helmet_checked_at` **그대로** | **동결** |
        | 미통과 · 캐시 없음 | `helmet` 필드 **생략** | **동결** |
        """
        if person.helmet is None:
            return True
        checked_at = person.helmet_checked_at
        if checked_at is None:
            # 엣지가 이 필드를 싣지 않으면 신선도를 알 수 없다. 값이 있는 것을 믿는다 —
            # 여기서 동결로 기울면 게이트를 통과한 판정까지 전부 멈춘다.
            return False
        stale = self._helmet_checked.get(key) == checked_at
        self._helmet_checked[key] = checked_at
        return stale

    def _judge(
        self,
        event: OpenEvent,
        person: DetectedPerson,
        vehicles: list[DetectedVehicle],
        *,
        gated: bool,
    ) -> Judgement:
        """유형별 해소 조건. 기능명세서 §4.2 FN-EVT-03

        | 유형 | 해소 조건 |
        |---|---|
        | `no_helmet` | 분류 결과가 `on` 으로 전환된 상태 지속 |
        | `zone_intrusion` | 접지점이 구역 밖 |
        | `proximity` | 거리가 임계값 초과 |
        | `fall` | 자세가 `standing` 으로 복귀 |
        """
        if event.violation_type is ViolationType.NO_HELMET:
            if gated:
                return "gated"
            return "violating" if person.helmet == "off" else "cleared"

        if event.violation_type is ViolationType.ZONE_INTRUSION:
            # 이탈 히스테리시스(`buffer_m`)는 엣지가 `in_zone` 을 만들 때 이미
            # 적용한다(FN-DET-07). 서버가 다시 판단하면 기준이 둘이 된다.
            inside = person.in_zone is not None and (
                event.zone_id is None or person.in_zone == event.zone_id
            )
            return "violating" if inside else "cleared"

        if event.violation_type is ViolationType.PROXIMITY:
            if not vehicles:
                # 잴 대상이 화면에 없다. 위험원이 사라진 것이므로 해소로 본다.
                return "cleared"
            # **거리는 호모그래피 지면 좌표로만 잰다**(CLAUDE.md 절대규칙 4).
            #
            # 여기서 잰 값을 `min_distance_m` 에 쓰지 않는다. 그 컬럼의 원천은 후보가
            # 실어 오는 `nearby[].dist_m`(마스크 최근접 · §6.5)이고, 접지점↔`anchor`
            # 거리는 그보다 거칠다. 두 값을 같은 칸에 섞으면 어느 방식으로 잰 숫자인지
            # 사후에 알 수 없다.
            nearest = min(math.dist(person.foot_point_m, vehicle.anchor_m) for vehicle in vehicles)
            return "violating" if nearest <= self._policies.proximity_threshold_m else "cleared"

        if person.posture == "unknown":
            # 자세를 판정하지 못한 구간이다. "일어섰다"가 아니므로 타이머를 멈춘다.
            return "gated"
        return "violating" if person.posture == "fallen" else "cleared"

    def _observe(self, event: OpenEvent, at: datetime, judgement: Judgement) -> None:
        """관측 한 건을 타이머에 반영한다.

        지난 구간의 시간은 **그때의 판정**에 적산한다. 관측이 끊겼던 구간
        (`_miss_s` 초과)과 게이팅 보류 구간은 어느 쪽에도 넣지 않는다.
        """
        elapsed = _elapsed(event.last_tick_at, at)
        event.last_tick_at = at
        if 0.0 < elapsed <= self._miss_s and not event.gated:
            if event.violating:
                event.observed_s += elapsed
            else:
                event.cleared_s += elapsed

        if judgement == "gated":
            event.gated = True
            return

        event.gated = False
        violating = judgement == "violating"
        if violating == event.violating:
            return
        event.violating = violating
        if violating:
            # 위반이 다시 관측됐다. 해소는 "지속"이 조건이므로 처음부터 다시 센다.
            event.cleared_s = 0.0
        else:
            # 확정도 "연속 관측"이 조건이다. 끊기면 처음부터다.
            event.observed_s = 0.0

    # ------------------------------------------------------------------
    # 내부 — 전이
    # ------------------------------------------------------------------

    def _evaluate(self, event: OpenEvent, at: datetime) -> list[Effect]:
        """타이머가 임계를 넘었는지 보고 전이시킨다."""
        policies = self._policies
        match event.status:
            case EventStatus.CANDIDATE:
                if event.observed_s >= policies.confirm_duration_s:
                    return self._to_alerted(event, at)
                if event.cleared_s >= policies.confirm_duration_s:
                    return self._to_dropped(event, at, "확정 전 위반 소멸")
                return []
            case EventStatus.ACTIVE:
                # 확정과 경고 발동은 같은 순간이지만(§4.2 "즉시"), 재시작 복구처럼
                # `active` 인 채로 들어온 경우가 있어 경로를 남겨 둔다.
                return self._to_alerted(event, at)
            case EventStatus.ALERTED | EventStatus.RE_ALERTED:
                if event.cleared_s >= policies.resolve_duration_s:
                    return self._to_resolved(event, at)
                if (
                    event.violating
                    and event.last_alerted_at is not None
                    and _elapsed(event.last_alerted_at, at) >= policies.cooldown_s
                ):
                    return self._to_re_alerted(event, at)
                return []
            case _:
                return []

    def _to_alerted(self, event: OpenEvent, at: datetime) -> list[Effect]:
        """FN-EVT-02 — 확정과 동시에 경고를 발동한다(요구: 1초 이내).

        `alerted_at` · `alert_count` 를 기록하고, 같은 `Effect` 에 **경고 의도**를 싣는다.
        기록이 먼저인 것은 시정률의 기준점이 그 시각이기 때문이고, 소리와 경광등은
        집행 계층(`server/app/alert_service.py`)이 그 의도를 보고 낸다.
        """
        confirmed = event.status is EventStatus.CANDIDATE
        event.status = EventStatus.ALERTED
        if event.alerted_at is None:
            event.alerted_at = at
        event.last_alerted_at = at
        event.alert_count += 1
        changes: dict[str, Any] = {
            "status": EventStatus.ALERTED.value,
            # `alerted_at` 은 **최초**로 고정되고, 매번 갱신되는 것은 `last_alerted_at`
            # 이다(§5.2 · §6). 재경고로 `alerted_at` 을 덮으면 `resolution_sec` 이
            # 마지막 방송 기준으로 줄어 시정률이 부풀려진다.
            "alerted_at": event.alerted_at,
            "last_alerted_at": event.last_alerted_at,
            "alert_count": event.alert_count,
        }
        if confirmed:
            # `zone_id` 는 여기서 얼어붙는다(§4.2) — 이후 최신 관측으로 따라가지 않는다.
            changes["confirmed_at"] = at
        message = EventCreatedMsg(
            event_id=event.event_id,
            cam_id=event.cam_id,
            violation_type=event.violation_type,
            track_id=event.track_id,
            zone_id=event.zone_id,
            status=EventStatus.ALERTED,
            confirmed_at=at,
            alerted_at=event.alerted_at,
            severity=SEVERITY[event.violation_type],
            # **M3 에는 키프레임 추출이 없다**(FN-REC-03 · M4). §5.2 가 이 필드를
            # nullable 로 넓혔으므로 아직 없는 파일을 가리키는 URL 대신 `null` 을
            # 보낸다 — "존재하지 않는 URL 을 문자열로 내보내지 않는다".
            keyframe_url=None,
        )
        return [
            Effect(
                action="update",
                event_id=event.event_id,
                cam_id=event.cam_id,
                track_id=event.track_id,
                changes=changes,
                message=message,
                alert=self._intent(event, at),
                note=f"확정·경고 발동 {event.event_id} — {event.violation_type.value}",
            )
        ]

    def _intent(self, event: OpenEvent, at: datetime) -> AlertIntent:
        """FN-ALM-01 · 02 — 이 전이가 내보낼 경고 한 번. **`alert_count` 증가 뒤에 부른다.**

        `at` 은 **관측 시각**이다(`frame.ts` · `candidate.ts`). 서버 수신 시각을 쓰면
        확정 → 방송 1초 이내(FN-ALM-01)를 재는 기준점에 네트워크 지연이 섞인다.

        `repeat` 은 상태가 아니라 **횟수**로 정한다. 재시작 직후 `active` 로 복구된
        이벤트가 첫 경고를 내보내는 경로가 있는데, 상태로 판별하면 그 첫 경고가
        재경고로 나가 ESP32 가 상습 패턴을 점멸한다.
        """
        return AlertIntent(
            event_id=event.event_id,
            cam_id=event.cam_id,
            violation_type=event.violation_type,
            level=SEVERITY[event.violation_type],
            zone_id=event.zone_id,
            repeat=event.alert_count > 1,
            at=at,
        )

    def _to_re_alerted(self, event: OpenEvent, at: datetime) -> list[Effect]:
        """FN-EVT-04 — 미해소 상태로 쿨다운이 지났다. 재경고하고 횟수를 센다."""
        event.status = EventStatus.RE_ALERTED
        event.last_alerted_at = at
        event.alert_count += 1
        return [
            Effect(
                action="update",
                event_id=event.event_id,
                cam_id=event.cam_id,
                track_id=event.track_id,
                changes={
                    "status": EventStatus.RE_ALERTED.value,
                    # **`alerted_at` 은 건드리지 않는다**(§5.2 · §6). 갱신되는 것은
                    # 최근 경고 시각뿐이다.
                    "last_alerted_at": at,
                    "alert_count": event.alert_count,
                },
                message=EventUpdatedMsg(
                    event_id=event.event_id,
                    status=EventStatus.RE_ALERTED,
                    last_alerted_at=at,
                    alert_count=event.alert_count,
                ),
                alert=self._intent(event, at),
                note=f"재경고 {event.event_id} — {event.alert_count}회",
            )
        ]

    def _to_resolved(self, event: OpenEvent, at: datetime) -> list[Effect]:
        """FN-EVT-03 — 위반 소멸이 `resolve_duration_s` 이상 유지됐다. **시정 성공**."""
        resolution_sec = (
            round(_elapsed(event.alerted_at, at)) if event.alerted_at is not None else None
        )
        self._close(event)
        return [
            Effect(
                action="update",
                event_id=event.event_id,
                cam_id=event.cam_id,
                track_id=event.track_id,
                changes={
                    "status": EventStatus.RESOLVED.value,
                    "resolved_at": at,
                    "resolution_sec": resolution_sec,
                },
                message=EventUpdatedMsg(
                    event_id=event.event_id,
                    status=EventStatus.RESOLVED,
                    resolved_at=at,
                    resolution_sec=resolution_sec,
                ),
                note=f"시정 완료 {event.event_id} — {resolution_sec}초",
            )
        ]

    def _to_lost(self, event: OpenEvent, at: datetime) -> list[Effect]:
        if event.status is EventStatus.CANDIDATE:
            # 확정 전 후보는 `dropped` 로 종결한다. `expired` 로 보내면 판정 불가율이
            # "위반이었는지도 모르는 것들"로 부풀어 지표의 뜻이 흐려진다(§4.2).
            return self._to_dropped(event, at, "확정 전 트랙 소실")
        if event.status is EventStatus.LOST:
            return []
        event.status_before_lost = (
            event.status if event.status is not EventStatus.ACTIVE else EventStatus.ALERTED
        )
        event.status = EventStatus.LOST
        event.lost_at = at
        return [
            Effect(
                action="update",
                event_id=event.event_id,
                cam_id=event.cam_id,
                track_id=event.track_id,
                changes={"status": EventStatus.LOST.value, "lost_at": at},
                message=EventUpdatedMsg(
                    event_id=event.event_id,
                    status=EventStatus.LOST,
                    lost_at=at,
                ),
                note=f"트랙 소실 유예 {event.event_id}",
            )
        ]

    def _to_expired(self, event: OpenEvent, at: datetime) -> list[Effect]:
        """FN-EVT-07 ① — 유예가 끝났고 재결합도 실패했다. **판정 불가**로 종결한다.

        미시정이 아니다. 시정률 분모·분자 모두에서 빠지고 `undetermined_rate` 로
        따로 집계된다(§6.7).
        """
        self._close(event)
        return [
            Effect(
                action="update",
                event_id=event.event_id,
                cam_id=event.cam_id,
                track_id=event.track_id,
                changes={"status": EventStatus.EXPIRED.value, "expired_at": at},
                message=EventUpdatedMsg(
                    event_id=event.event_id,
                    status=EventStatus.EXPIRED,
                    expired_at=at,
                ),
                note=f"판정 불가 종결 {event.event_id}",
            )
        ]

    def _to_dropped(self, event: OpenEvent, at: datetime, why: str) -> list[Effect]:
        """§4.2 — 확정 전(`candidate`)에 조건이 사라졌다. **레코드를 남기고 종결한다.**

        후보가 `confirm_duration_s` 를 채우지 못하고 사라지는 일은 정상적으로 흔하다.
        그래서 세 가지 선택지 중 하나를 골라야 했고, 명세서가 `dropped` 를 신설했다.

        | 대안 | 문제 |
        |---|---|
        | 레코드 삭제 | 튜닝 근거(`dropped / (dropped + 확정)`)가 사라진다 |
        | `expired` 로 종결 | 판정 불가율이 오염된다 — 그쪽은 "경고까지 갔는데 못 봤다"는 뜻이다 |
        | `candidate` 로 방치 | 병합 키(FN-EVT-01)를 점유해 같은 트랙의 새 위반이 병합된다 |

        `dropped` 는 종결 상태이므로 `_close` 로 상태머신에서 내린다 — 병합 키가
        풀리고, 지표에는 어느 쪽으로도 들어가지 않는다.

        `dropped_at` 은 §6 이 신설한 종결 시각이다(`resolved_at` · `expired_at` 과 짝).
        `detected_at` 만으로는 후보가 **얼마나 버티다** 사라졌는지 알 수 없어
        `confirm_duration_s` 튜닝에 쓸 수 없다.
        """
        event.status = EventStatus.DROPPED
        self._close(event)
        return [
            Effect(
                action="update",
                event_id=event.event_id,
                cam_id=event.cam_id,
                track_id=event.track_id,
                changes={"status": EventStatus.DROPPED.value, "dropped_at": at},
                message=EventUpdatedMsg(
                    event_id=event.event_id,
                    status=EventStatus.DROPPED,
                ),
                note=f"확정 전 소멸 {event.event_id} — {why}",
            )
        ]

    # ------------------------------------------------------------------
    # 내부 — 재결합 (FN-EVT-07 ②③)
    # ------------------------------------------------------------------

    def _reassociate(
        self,
        key: tuple[int, int],
        at: datetime,
        foot_point_m: tuple[float, float],
    ) -> list[Effect]:
        """새 트랙이 나타났다. 같은 카메라의 `lost` 이벤트에 이어 붙일 수 있는가.

        **결합은 트랙 단위다.** 한 사람에게 안전모 미착용과 구역 침입이 동시에
        걸려 있었다면 두 이벤트가 함께 살아나야 한다 — 하나만 살리면 나머지가
        `expired` 로 떨어져 판정 불가율이 이유 없이 오른다.
        """
        cam_id, track_id = key
        if key in self._seen or key in self._by_track:
            return []

        lost = self._lost_tracks(cam_id)
        if not lost:
            return []
        policies = self._policies
        match = match_lost_track(
            appeared_at=at,
            foot_point_m=foot_point_m,
            lost=lost,
            window_s=policies.reassoc_window_s,
            max_speed_ms=policies.reassoc_max_speed_ms,
            cap_m=policies.reassoc_radius_cap_m,
        )
        if match is None:
            return []

        old_track = self._events[match.event_id].track_id
        effects: list[Effect] = []
        for event_id in list(self._by_track.get((cam_id, old_track), {}).values()):
            effects.append(self._revive(self._events[event_id], track_id, at, match.distance_m))
        self._seen.pop((cam_id, old_track), None)
        self._helmet_checked.pop((cam_id, old_track), None)
        return effects

    def _lost_tracks(self, cam_id: int) -> list[LostTrack]:
        """카메라 안의 `lost` 이벤트를 **트랙 단위로** 묶는다."""
        by_track: dict[int, LostTrack] = {}
        for event in self._events.values():
            if event.status is not EventStatus.LOST or event.cam_id != cam_id:
                continue
            if event.lost_at is None:
                continue
            if event.track_id in by_track:
                continue
            by_track[event.track_id] = LostTrack(
                event_id=event.event_id,
                track_id=event.track_id,
                lost_at=event.lost_at,
                last_foot_point_m=self._foot.get((cam_id, event.track_id), (0.0, 0.0)),
            )
        return list(by_track.values())

    def _revive(
        self,
        event: OpenEvent,
        track_id: int,
        at: datetime,
        distance_m: float,
    ) -> Effect:
        """FN-EVT-07 ③ — 직전 상태로 복귀시킨다.

        **해소 타이머를 0부터 다시 시작한다.** 재결합으로 돌아온 이벤트는 위반이 이미
        사라진 상태로 관측되더라도 즉시 시정 처리하지 않는다 — 추적 ID 스위치로 다른
        작업자가 트랙을 물려받은 경우를 방어하기 위한 규칙이며, 이 조건을 통과하면
        최소한 "그 위치에서 해소 지속시간 동안 위반 없는 상태가 유지되었다"는 사실은
        보장된다.

        **쿨다운은 이어받는다.** `last_alerted_at` 을 건드리지 않으므로 복귀 직후 중복
        경고가 나가지 않는다.
        """
        previous = event.status_before_lost or EventStatus.ALERTED
        old_track = event.track_id
        self.forget(event.event_id)

        event.prev_track_ids = [*event.prev_track_ids, old_track]
        event.track_id = track_id
        event.reassoc_count += 1
        event.status = previous
        event.status_before_lost = None
        event.lost_at = None
        event.last_seen_at = at
        event.last_tick_at = at
        event.cleared_s = 0.0
        event.violating = True
        event.gated = False
        self._register(event)

        return Effect(
            action="update",
            event_id=event.event_id,
            cam_id=event.cam_id,
            track_id=event.track_id,
            changes={
                "status": previous.value,
                "track_id": track_id,
                "prev_track_ids": list(event.prev_track_ids),
                "reassoc_count": event.reassoc_count,
            },
            message=EventUpdatedMsg(
                event_id=event.event_id,
                status=previous,
                track_id=track_id,
                reassoc_count=event.reassoc_count,
            ),
            note=(
                f"재결합 {event.event_id} — track {old_track} → {track_id}, "
                f"지면거리 {distance_m:.2f}m"
            ),
        )

    def _prune(self, at: datetime) -> None:
        """오래된 트랙 기억을 버린다. 재결합 창을 넘긴 것은 더 쓸 데가 없다."""
        horizon = max(self._policies.reassoc_window_s, self._miss_s)
        for key, seen_at in list(self._seen.items()):
            if key not in self._by_track and _elapsed(seen_at, at) > horizon:
                self._seen.pop(key, None)
                self._foot.pop(key, None)
                self._helmet_checked.pop(key, None)

    def _apply(self, event: OpenEvent, changes: Mapping[str, Any]) -> None:
        if "zone_id" in changes:
            event.zone_id = changes["zone_id"]
        if "min_distance_m" in changes:
            event.min_distance_m = changes["min_distance_m"]
        if "posture" in changes:
            event.posture = changes["posture"]


#: 종결되지 않은 상태. FN-EVT-01 이 "진행 중"이라고 부르는 집합(기능명세서 §4.2).
_OPEN_STATUSES: frozenset[EventStatus] = frozenset(
    {
        EventStatus.CANDIDATE,
        EventStatus.ACTIVE,
        EventStatus.ALERTED,
        EventStatus.RE_ALERTED,
        EventStatus.LOST,
    }
)


def merge_changes(existing: OpenEvent, candidate: CandidateMsg) -> dict[str, Any]:
    """FN-EVT-01 — 진행 중 이벤트에 후보를 병합할 때 **실제로 달라진 것만** 돌려준다.

    바뀐 것이 없으면 빈 dict 다. 후보는 초당 여러 번 오므로 매번 같은 값을 다시 쓰면
    DB 가 후보 빈도만큼 갱신 부하를 받는다.

    `min_distance_m` 은 덮어쓰지 않고 **더 작은 값으로만** 내린다 — 이벤트가 살아 있는
    동안 얼마나 가까웠는지가 위험도의 근거이고(§4.1), 마지막 값으로 덮으면 지게차가
    멀어진 뒤에는 위험했던 사실이 사라진다.

    `zone_id` 는 반대로 **확정되면 얼어붙는다**(§4.2). 두 필드가 다르게 동작하는 이유는
    묻는 질문이 다르기 때문이다 — "얼마나 위험했나"는 구간 전체의 최댓값이고,
    "어디서 확정됐나"는 한 순간의 사실이다.
    """
    changes: dict[str, Any] = {}

    if existing.status is EventStatus.CANDIDATE and existing.zone_id != candidate.zone_id:
        changes["zone_id"] = candidate.zone_id

    distance = _min_distance(candidate)
    closest = existing.min_distance_m
    if distance is not None and (closest is None or distance < closest):
        changes["min_distance_m"] = distance

    if candidate.posture is not None and candidate.posture != existing.posture:
        changes["posture"] = candidate.posture

    return changes


def _min_distance(candidate: CandidateMsg) -> float | None:
    """가장 가까운 지게차까지의 거리. 주변에 없으면 `null`.

    0.0 으로 채우지 않는다 — "붙어 있었다"와 "잴 대상이 없었다"는 다른 사실이다.
    """
    if not candidate.nearby:
        return None
    return min(vehicle.dist_m for vehicle in candidate.nearby)


def _depth_verified(candidate: CandidateMsg) -> bool | None:
    """뎁스로 앞뒤 분리를 확인했는가. 잴 대상이 없었으면 `null`.

    §2.2 는 트리거 미충족으로 **미실행**일 때도 `false` 를 싣게 한다. 그 `false` 는
    그대로 옮기고, `nearby` 자체가 비었을 때만 `null` 이다.
    """
    if not candidate.nearby:
        return None
    return any(vehicle.depth_verified for vehicle in candidate.nearby)


def _elapsed(since: datetime, until: datetime) -> float:
    return (until - since).total_seconds()
