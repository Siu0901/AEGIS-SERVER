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
      clip_status: ready      # 선택 — FN-REC-03. null 이면 "예약조차 걸리지 않았다"
      alert_suppressed: false # 선택 — 일시중지 중 확정되어 방송이 없었는가 (§4.8)
  metrics:
    correction_rate: 1.0    # 분모가 0이면 `null` 이다 (0.0 이 아니다 · §6.7)
    undetermined_rate: 0.0
    total_violations: 1
    resolved: 1             # 창 이내 해소 — 분자
    resolved_late: 0        # 창 초과 해소 — 분모에만 (unresolved 와 섞지 않는다)
    unresolved: 0
    undetermined: 0
    suppressed: 0           # 방송 없이 확정된 건 — 분모·분자 어디에도 안 든다 (§4.8)
    fall_events: 0
  alerts:                   # 선택 — FN-ALM-01·02. **전량 목록**이다(더 나가도 실패)
    - at_s: 3.5
      violation_type: no_helmet
      level: 2              # 1|2|3 · fall 은 항상 3
      repeat: false         # 재경고면 true
      sound: no_helmet.wav  # 실제로 튼 파일

manual:                     # 선택 — FN-EVT-05 수동 정정
  - at: 30.0
    match: {track_id: 3, violation_type: fall}
    patch: {is_false_positive: true}

mute:                       # 선택 — FN-ALM-05 경고 일시중지
  - at: 1.0
    cam_id: 1               # 생략하면 전체 카메라 (§4.5)
    minutes: 15             # 0 은 즉시 해제 · 생략하면 mute_default_duration_s
    reason: 정비 작업

restart_at: [12.0]          # 선택 — 이 시각에 서버를 내렸다 올린다 (저장소만 남는다)

rec:                        # 선택 — REC 응답을 바꿔 실패 경로를 본다 (§4.7)
  status: not_found         # ready(기본) | partial | not_found
  available: true           # false 면 REC 이 죽은 상황 (잡은 pending 으로 남아야 한다)
  segment_seconds: 10       # REC 이 보고하는 세그먼트 길이. 클립 예약 실행 시각이
                            # `확정 + 사후 10s + 이 값 + 여유 2s` 이므로(기능명세서 §4.4),
                            # 짧은 시나리오는 이 값을 줄여 타임라인을 늘리지 않는다
```
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, cast

import yaml

from aegis_contracts import (
    AlertCommand,
    CandidateMsg,
    ClipRequest,
    ClipResponse,
    EventDetail,
    EventPatchRequest,
    EventStatus,
    EventSummary,
    FrameMsg,
    MetricsSummary,
    MuteAlertRequest,
    Policies,
    RecRecordingStatus,
    RecStatusResponse,
    RecStorageStatus,
    SpecModel,
    TrackLostMsg,
    ViolationType,
)
from aegis_contracts.enums import AlertLevel, ClipExtractStatus
from aegis_vision.clock import FakeClock
from scripts.seed_sounds import AUDIO_DIR, DEFAULT_SOUNDS
from server.app.alert_service import AlertService
from server.app.event_service import EventService, Publisher
from server.domain.alerts import SoundEntry
from server.domain.event_machine import EventMachine, format_event_id
from server.domain.mcu_state import McuRuntime
from server.domain.metrics import MetricsRow
from server.domain.overlay import LiveTracks
from server.infra.audio import SoundLibrary
from server.infra.clip import ClipService
from server.infra.rec_client import RecUnavailableError

from .edge_sim.scripted import CASES_DIR, ScheduledMessage, load_case, resolve_case_path

#: 종결되지 않은 상태. 재시작 복구(`find_open_all`)가 되살릴 집합이다(§4.2).
_OPEN_STATUSES = frozenset(
    {
        EventStatus.CANDIDATE,
        EventStatus.ACTIVE,
        EventStatus.ALERTED,
        EventStatus.RE_ALERTED,
        EventStatus.LOST,
    }
)

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
    """메모리 이벤트 저장소. `EventService` 와 `ClipService` 가 요구하는 것만 구현한다.

    **재시작을 흉내 낼 수 있어야 한다.** `clip_recovery` 시나리오가 서버를 내렸다
    올리는데, 그때 살아남는 것은 이 저장소뿐이다 — 상태머신도 예약 큐도 새로 만들어진다.
    실제 DB 가 하는 일이 정확히 그것이다.
    """

    def __init__(self) -> None:
        self.events: dict[str, EventDetail] = {}
        self.false_positive: set[str] = set()
        self.notes: dict[str, str] = {}
        self.clip_status: dict[str, str] = {}
        """§6 `events.clip_status`. `EventDetail`(§4.1 응답)에 없는 컬럼이라 따로 든다."""
        self.clip_paths: dict[str, str] = {}
        self.keyframe_paths: dict[str, list[str]] = {}
        self._sequence = 0

    async def find_open_all(self) -> list[EventSummary]:
        """종결되지 않은 이벤트 전량. **재시작 복구의 입력이다.**"""
        return [
            EventSummary.model_validate(event.model_dump(include=set(EventSummary.model_fields)))
            for event in self.events.values()
            if event.status in _OPEN_STATUSES
        ]

    async def find_due_clip_jobs(self, now: datetime, delay_s: float) -> list[str]:
        """FN-REC-03 — 실행 시각이 지난 `pending` 예약. DB 질의와 같은 조건이다."""
        return sorted(
            event_id
            for event_id, status in self.clip_status.items()
            if status == "pending"
            and (confirmed := self.events[event_id].confirmed_at) is not None
            and confirmed + timedelta(seconds=delay_s) <= now
        )

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
        if (note := patch.get("note")) is not None:
            self.notes[event_id] = note
        if (status := patch.pop("clip_status", None)) is not None:
            self.clip_status[event_id] = str(status)
        if (clip_path := patch.pop("clip_path", None)) is not None:
            self.clip_paths[event_id] = str(clip_path)
            # 실제 저장소는 `clip_path` 를 `clip_url` 로 바꿔 내려준다(§5 경로 규약).
            patch["clip_url"] = f"/media/clips/{PurePosixPath(str(clip_path)).name}"
        if (keyframes := patch.pop("keyframe_paths", None)) is not None:
            self.keyframe_paths[event_id] = list(keyframes)
        # §6 컬럼이지만 §4.1 응답 모델에 자리가 없는 것들. `last_alerted_at` · `note` 는
        # 명세서가 §4.1 에 추가하면서 여기서 빠져나갔다 — 이제 모델 필드다.
        for key in ("prev_track_ids", "reassoc_count", "lost_at", "expired_at", "dropped_at"):
            patch.pop(key, None)
        self.events[event_id] = event.model_copy(update=patch)

    async def get(self, event_id: str) -> EventDetail | None:
        return self.events.get(event_id)

    async def metrics_rows(self, from_: datetime | None, to: datetime | None) -> list[MetricsRow]:
        return [
            MetricsRow(
                violation_type=event.violation_type,
                status=event.status,
                resolution_sec=event.resolution_sec,
                is_false_positive=event.event_id in self.false_positive,
                # ★ §4.8 — 방송이 나가지 않은 건은 「방송 후」 시정률의 모집단이 아니다.
                alert_suppressed=event.alert_suppressed,
            )
            for event in self.events.values()
            if (from_ is None or event.detected_at >= from_)
            and (to is None or event.detected_at <= to)
        ]


# --------------------------------------------------------------------------
# 가짜 장치 (FN-ALM-01 · 02 · FN-REC-03)
# --------------------------------------------------------------------------
# **시나리오는 소리를 내지도 브로커에 붙지도 REC 을 부르지도 않는다.** 대신 "무엇을
# 틀었고 무엇을 발행했고 무엇을 요청했는가"를 기록한다. 검증 대상은 장치가 아니라
# **서버가 그것들을 부르기로 판단했는가**이기 때문이다.


@dataclass(slots=True)
class PlayedSound:
    """재생된 음원 하나. 시각까지 잠가야 "확정과 같은 순간인가"를 볼 수 있다."""

    at: datetime
    filename: str


class CasePlayer:
    """`SoundPlayer` 대역. `clock` 을 들고 있어 재생 시각을 남긴다."""

    name = "case"

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.played: list[PlayedSound] = []

    def play(self, path: Path) -> None:
        self.played.append(PlayedSound(at=self._clock.now(), filename=path.name))


class CaseMqtt:
    """`MqttSender` 대역. 발행된 §3 `AlertCommand` 를 시각과 함께 기억한다."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.published: list[tuple[datetime, AlertCommand]] = []

    async def publish_alert(self, command: AlertCommand) -> None:
        self.published.append((self._clock.now(), command))


class CaseSounds:
    """`SoundReader` 대역 — `alert_sounds` 테이블 대신 시드 기본값 하나.

    **`scripts/seed_sounds.py` 의 표를 그대로 쓴다.** 여기서 따로 적으면 시드가
    바뀌었을 때 시나리오만 옛 등급으로 통과한다.
    """

    async def load_sounds(self) -> dict[str, SoundEntry]:
        return {
            key: SoundEntry(file_path=file_path, level=cast("AlertLevel", level), label=label)
            for key, (file_path, level, label) in DEFAULT_SOUNDS.items()
        }


class CaseRec:
    """`ClipExtractor` 대역 (§4.7).

    `extract_status` 를 바꾸면 `partial` · `not_found` 를 흉내 낼 수 있고,
    `available=False` 면 REC 이 죽은 상황이 된다 — 그때 잡은 `failed` 가 아니라
    `pending` 으로 남아야 한다.
    """

    def __init__(
        self,
        *,
        extract_status: ClipExtractStatus = "ready",
        available: bool = True,
        reason: str | None = None,
        segment_seconds: int = 10,
    ) -> None:
        self.extract_status = extract_status
        self.available = available
        self.reason = reason
        self.segment_seconds = segment_seconds
        self.keyframes: list[tuple[int, datetime]] = []
        self.clips: list[ClipRequest] = []

    async def status(self) -> RecStatusResponse:
        """§4.7 `GET /status` — 서버는 여기서 세그먼트 길이를 읽어 예약 시각에 더한다.

        **서버가 상수로 들고 있지 않다**(기능명세서 §4.4). 시나리오도 REC 역할이므로
        같은 값을 보고한다.
        """
        if not self.available:
            msg = "REC 에 닿지 못했다 (시나리오)"
            raise RecUnavailableError(msg)
        return RecStatusResponse(
            cameras=[],
            storage=RecStorageStatus(
                total_gb=500, used_gb=0, free_gb=500, retention_days=7, oldest_segment_at=None
            ),
            recording=RecRecordingStatus(
                segment_seconds=self.segment_seconds, snapshot_fps=1, snapshot_window_s=60
            ),
        )

    async def keyframe(self, cam_id: int, at: datetime) -> bytes:
        if not self.available:
            msg = "REC 에 닿지 못했다 (시나리오)"
            raise RecUnavailableError(msg)
        self.keyframes.append((cam_id, at))
        return b"\xff\xd8\xff\xd9"  # 최소 JPEG (SOI + EOI)

    async def create_clip(self, request: ClipRequest) -> ClipResponse:
        if not self.available:
            msg = "REC 에 닿지 못했다 (시나리오)"
            raise RecUnavailableError(msg)
        self.clips.append(request)
        if self.extract_status != "ready":
            return ClipResponse(
                status=self.extract_status,
                reason=self.reason or f"{self.extract_status} (시나리오)",
            )
        return ClipResponse(
            status="ready",
            size_bytes=4,
            download_url=f"/clips/{request.event_id}.mp4",
            actual_from=request.from_,
            actual_to=request.to,
        )

    async def download(self, url: str) -> bytes:
        del url
        return b"mp4."


@dataclass(frozen=True, slots=True)
class CaseResult:
    """시나리오 한 편을 끝까지 돌린 결과."""

    name: str
    events: list[EventDetail]
    metrics: MetricsSummary
    published: list[SpecModel]
    start: datetime
    machine: EventMachine = field(repr=False)
    played: list[PlayedSound] = field(default_factory=list)
    """FN-ALM-01 — 실제로 튼 wav 들."""
    alerts: list[tuple[datetime, AlertCommand]] = field(default_factory=list)
    """FN-ALM-02 — `aegis/alert` 로 나간 것들."""
    clip_status: dict[str, str] = field(default_factory=dict)
    """FN-REC-03 — 이벤트별 `clip_status` 최종값."""
    restarts: int = 0

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


def _build(
    store: CaseStore,
    clock: FakeClock,
    publish: Publisher,
    player: CasePlayer,
    mqtt: CaseMqtt,
    rec: CaseRec,
    media_root: Path,
) -> tuple[EventService, ClipService, EventMachine, AlertService]:
    """서버 한 벌을 조립한다. **재시작은 이 함수를 다시 부르는 것이다.**

    저장소(`store`)와 장치들만 살아남고 상태머신·예약 큐는 새로 만들어진다 — 실제
    프로세스 재시작에서 남는 것이 정확히 DB 뿐이기 때문이다.

    DB 를 띄우지 않으므로 계약 기본값(`Policies()`)을 쓴다. 그 값이 곧
    `scripts/seed_policies.py` 가 DB 에 넣는 값이라 실서버와 같은 임계값으로 판정된다.
    """
    alerts = AlertService(
        library=SoundLibrary(AUDIO_DIR, CaseSounds()),
        player=player,
        clock=clock,
        mcu=McuRuntime(),
        mqtt=mqtt,
        publish=publish,
    )
    clips = ClipService(
        rec=rec,
        store=store,
        clock=clock,
        media_root=media_root,
        publish=publish,
    )
    machine = EventMachine(clock=clock, policies=Policies())
    service = EventService(
        machine=machine,
        tracks=LiveTracks(),
        publish=publish,
        clock=clock,
        store=store,
        policies=None,
        alerts=alerts,
        clips=clips,
    )
    return service, clips, machine, alerts


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

    player = CasePlayer(clock)
    mqtt = CaseMqtt(clock)
    rec = CaseRec(
        extract_status=str((raw.get("rec") or {}).get("status", "ready")),  # type: ignore[arg-type]
        available=bool((raw.get("rec") or {}).get("available", True)),
        segment_seconds=int((raw.get("rec") or {}).get("segment_seconds", 10)),
    )

    manual = list(raw.get("manual") or [])
    mutes = list(raw.get("mute") or [])
    restarts = [float(value) for value in (raw.get("restart_at") or [])]

    with tempfile.TemporaryDirectory(prefix="aegis-case-") as tmp:
        media_root = Path(tmp)
        service, clips, machine, alerts = _build(
            store, clock, publish, player, mqtt, rec, media_root
        )
        # 음원 매핑을 읽는다(서버의 `AlertService.start`). 이것 없이 확정이 나면
        # "등록된 음원이 없다"로 방송이 실패한다 — 실서버에서도 같은 순서다.
        await alerts.start()
        await service.start()

        last_at = max((item.at_s for item in timeline), default=0.0)
        scripted = [*manual, *mutes]
        scripted_end = max((float(item.get("at", 0.0)) for item in scripted), default=0.0)
        end_s = (
            max(last_at, scripted_end, *restarts) + tail_s
            if restarts
            else (max(last_at, scripted_end) + tail_s)
        )

        done: list[float] = []
        for at_s in _grid(timeline, scripted, end_s, restarts):
            clock.set(start + timedelta(seconds=at_s))
            for moment in restarts:
                if abs(moment - at_s) < 1e-9 and moment not in done:
                    # ★ 서버를 내렸다 올린다. 남는 것은 저장소뿐이다.
                    done.append(moment)
                    service, clips, machine, alerts = _build(
                        store, clock, publish, player, mqtt, rec, media_root
                    )
                    await alerts.start()
                    await service.start()
            for item in _due(timeline, at_s):
                await _dispatch(service, item)
            for entry in _due_manual(manual, at_s):
                await _apply_manual(service, store, entry)
            for entry in _due_manual(mutes, at_s):
                await _apply_mute(alerts, entry)
            await service.tick()
            # 서버의 클립 루프(`_run_clips`)와 같은 일을 한다 — 실행 시각이 지난
            # 예약을 집어 든다. 재시작 뒤에도 같은 조회가 그대로 돌아 복구가 된다.
            await clips.run_due()
            # 뒤로 넘긴 키프레임 추출을 이 격자 안에서 마무리시킨다. 실서버에서는
            # 그대로 두지만, 시나리오는 결과가 격자마다 확정되어야 재현된다.
            await clips.wait_idle()

        return CaseResult(
            name=str(raw.get("name", case)),
            events=sorted(store.events.values(), key=lambda event: event.event_id),
            metrics=await service.summary(),
            published=published,
            start=start,
            machine=machine,
            played=player.played,
            alerts=mqtt.published,
            clip_status=dict(store.clip_status),
            restarts=len(done),
        )


def check_case(case: str, result: CaseResult) -> list[str]:
    """기대값과 대조한다. 어긋난 것들을 사람이 읽을 문장으로 돌려준다(없으면 빈 목록)."""
    expect: dict[str, Any] = _spec(case).get("expect") or {}
    problems: list[str] = []
    problems += _check_events(expect.get("events") or [], result)
    problems += _check_metrics(expect.get("metrics") or {}, result.metrics)
    if "alerts" in expect:
        problems += _check_alerts(expect.get("alerts") or [], result)
    if "restarts" in expect and result.restarts != expect["restarts"]:
        # 재시작이 실제로 일어났는지 잠근다. `restart_at` 오타 하나로 이 시나리오가
        # 평범한 시나리오가 되어 조용히 통과하는 것을 막는다.
        problems.append(f"재시작 횟수: 기대 {expect['restarts']} · 실제 {result.restarts}")
    return problems


# --------------------------------------------------------------------------
# 내부
# --------------------------------------------------------------------------


def _grid(
    timeline: Sequence[ScheduledMessage],
    scripted: Sequence[Mapping[str, Any]],
    end_s: float,
    restarts: Sequence[float] = (),
) -> Iterator[float]:
    """메시지 시각과 틱 격자를 시각 순으로 합친다."""
    moments = {round(item.at_s, 6) for item in timeline}
    moments |= {round(float(entry.get("at", 0.0)), 6) for entry in scripted}
    moments |= {round(float(value), 6) for value in restarts}
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


async def _apply_mute(alerts: AlertService | None, entry: Mapping[str, Any]) -> None:
    """FN-ALM-05 — 관리자가 `POST /alerts/mute` 를 누른 것을 그대로 흉내 낸다."""
    if alerts is None:
        msg = "경고 집행자가 없어 일시중지를 적용할 수 없다"
        raise ValueError(msg)
    cam_id = entry.get("cam_id")
    minutes = entry.get("minutes")
    await alerts.mute(
        MuteAlertRequest(
            # `cam_id` 를 적지 않으면 **전체 카메라**다(§4.5). 1 로 채우면 시나리오가
            # 전체 대상 중지를 검증할 수 없다.
            cam_id=None if cam_id is None else int(cam_id),
            # `minutes` 를 적지 않으면 정책 기본값(`mute_default_duration_s`)이 붙는다.
            minutes=None if minutes is None else int(minutes),
            reason=str(entry.get("reason", "")),
        )
    )


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
    for key in ("alert_count", "zone_id", "alert_suppressed"):
        if key in want and getattr(got, key) != want[key]:
            problems.append(f"{label} {key}: 기대 {want[key]} · 실제 {getattr(got, key)}")

    if "clip_status" in want:
        # FN-REC-03 — `pending → ready` 로 갔는지. `null` 은 "예약조차 걸리지 않았다"이며,
        # 확정된 적이 없는 이벤트(`dropped`)에서는 그것이 정답이다.
        stored = result.clip_status.get(got.event_id)
        if stored != want["clip_status"]:
            problems.append(
                f"{label} clip_status: 기대 {_shown(want['clip_status'])} · 실제 {_shown(stored)}"
            )

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


def _check_alerts(expected: list[Any], result: CaseResult) -> list[str]:
    """FN-ALM-01 · 02 — 경고가 **실제로 나갔는가**를 잠근다.

    두 경로를 한 표에서 함께 본다. `alerted` 로 전이했다는 기록만으로는 소리가 났는지
    경광등이 켜졌는지 알 수 없고, 그 둘이 이 마일스톤이 추가한 전부다.

    `expect.alerts` 는 **전량 목록**이다. 기대보다 많이 나갔으면 실패다 — 중복 경고는
    누락만큼이나 현장에서 문제가 된다(FN-EVT-04 쿨다운이 막아야 하는 것이다).
    """
    problems: list[str] = []
    fired = result.alerts
    if len(fired) != len(expected):
        problems.append(
            f"경고 발행 건수: 기대 {len(expected)} · 실제 {len(fired)} "
            f"({[command.event_id for _, command in fired]})"
        )
    for index, want in enumerate(expected):
        if index >= len(fired):
            break
        at, command = fired[index]
        label = f"경고[{index}]"
        for key in ("violation_type", "level", "repeat", "zone_id"):
            if key not in want:
                continue
            actual = command.type if key == "violation_type" else getattr(command, key)
            if actual != want[key]:
                problems.append(f"{label} {key}: 기대 {want[key]} · 실제 {actual}")
        if "at_s" in want:
            actual_s = result.offset_s(at)
            wanted_s = float(want["at_s"])
            if actual_s is None or abs(actual_s - wanted_s) > TIME_TOLERANCE_S:
                problems.append(
                    f"{label} 시각: 기대 +{wanted_s:.2f}s±{TIME_TOLERANCE_S} · 실제 {actual_s}"
                )
        if "sound" in want:
            played = result.played[index].filename if index < len(result.played) else None
            if played != want["sound"]:
                problems.append(f"{label} 음원: 기대 {want['sound']} · 실제 {played}")
    # 방송과 경광등은 서로 독립이지만(한쪽 실패가 다른 쪽을 막지 않는다), 정상 경로에서는
    # 같은 횟수여야 한다. 어긋나면 한쪽 경로가 조용히 죽은 것이다.
    if not any("일시중지" in problem for problem in problems) and len(result.played) != len(fired):
        problems.append(f"방송 {len(result.played)}건 · 경광등 {len(fired)}건 — 두 경로가 어긋났다")
    return problems


def _check_metrics(expected: Mapping[str, Any], got: MetricsSummary) -> list[str]:
    """기대 지표와 대조한다.

    **`null` 은 값이다.** 시정률은 분모가 0이면 `None` 이고(§6.7), 그것은 "0%"와
    다른 사실이다. 그래서 "필드가 없다"와 "값이 `None` 이다"를 섞지 않는다 —
    섞으면 `correction_rate: null` 기대가 오타 하나로도 통과해 버린다.
    """
    problems: list[str] = []
    for key, wanted in expected.items():
        if key not in MetricsSummary.model_fields:
            problems.append(f"지표에 없는 항목이다: {key}")
            continue
        actual = getattr(got, key)
        if wanted is None or actual is None:
            if wanted is not actual:
                problems.append(f"지표 {key}: 기대 {_shown(wanted)} · 실제 {_shown(actual)}")
            continue
        if isinstance(wanted, float) or isinstance(actual, float):
            if abs(float(actual) - float(wanted)) > RATE_TOLERANCE:
                problems.append(f"지표 {key}: 기대 {wanted} · 실제 {actual}")
        elif actual != wanted:
            problems.append(f"지표 {key}: 기대 {wanted} · 실제 {actual}")
    return problems


def _shown(value: Any) -> str:
    """`None` 을 `null`(판정 가능한 이벤트가 없음)로 읽히게 찍는다."""
    return "null" if value is None else str(value)


def _rate(value: float | None) -> str:
    """표에 찍을 비율. **분모가 0이면 `–` 다** — `0.00` 과 다르게 보여야 한다(§6.7)."""
    return "–" if value is None else f"{value:.2f}"


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
        f"{'시나리오':<20} {'시정률':>8} {'판정불가율':>10} {'해소':>4} {'늦은시정':>8} "
        f"{'미시정':>6} {'판정불가':>8} {'쓰러짐':>6}  결과"
    )
    for name in names:
        result = asyncio.run(run_case(name))
        problems = check_case(name, result)
        failed += bool(problems)
        metrics = result.metrics
        print(
            f"{name:<20} {_rate(metrics.correction_rate):>8} "
            f"{_rate(metrics.undetermined_rate):>10} "
            f"{metrics.resolved:>4} {metrics.resolved_late:>8} {metrics.unresolved:>6} "
            f"{metrics.undetermined:>8} {metrics.fall_events:>6} "
            f" {'OK' if not problems else 'FAIL'}"
        )
        for problem in problems:
            print(f"    - {problem}")

    print()
    print(f"{len(names)}개 중 {len(names) - failed}개 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
