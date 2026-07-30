"""경고 집행 — 소리를 내고 경광등을 켠다. FN-ALM-01 ~ FN-ALM-05

기능명세서 §4.3 · API명세서 §3 · §4.5

상태머신은 `AlertIntent`(`server/domain/alerts.py`)로 "지금 경고하라"고만 말한다.
여기서 그 지시를 실제 장치로 옮긴다.

| 하는 일 | 근거 |
|---|---|
| 위반 유형별 사전 녹음 wav 재생 (TTS 아님) | FN-ALM-01 |
| `aegis/alert` 로 `AlertCommand` 발행 | FN-ALM-02 · API §3 |
| 수동 방송 | FN-ALM-04 · API §4.5 |
| 경고 일시중지 (카메라별 · 기한부) | FN-ALM-05 · API §4.5 |
| 확정 → 방송 시작 지연 실측 | FN-ALM-01 요구(1초 이내) |

**두 경로는 서로를 막지 않는다.** 스피커가 죽어도 경광등은 켜지고, 브로커가 죽어도
방송은 나간다. 소음이 심한 구역에서는 경광등이 유일한 경보이고, 그 반대도 마찬가지다.
한쪽 실패로 다른 쪽을 건너뛰면 **하나 고장이 둘 고장이 된다.**

**실패를 삼키지 않는다**(CLAUDE.md 절대규칙 9). 어느 쪽이 실패해도 ERROR 로 남기고
집계하며, 그 사실은 `GET /system/status` 의 `mcu` 절과 §5.3 `system` 으로 드러난다.
다만 예외를 위로 던지지는 않는다 — 경고 실패가 상태 전이를 되돌리면 이벤트가 반쯤
적용된 채 남고, 그쪽이 훨씬 위험하다.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from aegis_contracts import (
    AlertCommand,
    ComponentSystemMsg,
    ManualAlertRequest,
    MuteAlertRequest,
    MuteAlertResponse,
    Policies,
    SpecModel,
    ViolationType,
)
from aegis_contracts.enums import AlertLevel
from aegis_vision.clock import Clock
from server.domain.alerts import AlertIntent
from server.domain.mcu_state import McuRuntime
from server.infra.audio import (
    DEFAULT_MANUAL_SOUND,
    SoundLibrary,
    SoundNotFoundError,
    SoundPlayer,
    play_async,
)

__all__ = [
    "ALL_CAMERAS",
    "MANUAL_EVENT_PREFIX",
    "SOUND_REFRESH_SECONDS",
    "AlertService",
    "AlertSink",
    "MuteWindow",
]

log = logging.getLogger("server.alerts")

#: 음원 매핑을 다시 읽는 주기(초). 설정 화면에서 음원을 바꾸면 이만큼 안에 반영된다.
SOUND_REFRESH_SECONDS = 60.0

#: 확정 → 방송 시작 요구치(밀리초). 기능명세서 §4.3 FN-ALM-01 · §7 비기능 요구.
LATENCY_BUDGET_MS = 1000.0

#: 수동 방송이 §3 `AlertCommand.event_id` 에 쓰는 접두사. FN-ALM-04
#:
#: **`EV-` 를 쓰지 않는다.** 수동 방송에는 이벤트 레코드가 없으므로, 조회 가능한
#: 이벤트처럼 보이는 ID 를 내보내면 ESP32 와 대시보드가 존재하지 않는 것을 참조한다.
MANUAL_EVENT_PREFIX = "MANUAL"


class AlertSink(Protocol):
    """`EventService` 가 요구하는 경고 집행자. 시나리오 검사가 가짜를 끼워 넣는 자리다."""

    async def fire(self, intent: AlertIntent) -> bool:
        """경고 한 번을 집행하고 **방송이 실제로 나갔는지**를 돌려준다.

        `False` 는 일시중지(FN-ALM-05) 때문에 장치가 조용했다는 뜻이며, 호출자는 그
        이벤트를 `alert_suppressed = true` 로 기록해 시정률에서 제외한다(§4.8).
        재생 실패는 `False` 가 아니다 — 그쪽은 "방송하려 했으나 장치가 고장났다"이고
        집행자가 따로 집계한다.
        """
        ...

    def severity_map(self) -> Mapping[ViolationType, AlertLevel]:
        """DB `alert_sounds.level` 이 정한 유형별 위험 등급(§6 · FN-CFG-03)."""
        ...


class Broadcaster(Protocol):
    """대시보드로 계약 모델 하나를 밀어 넣는 통로(`DashboardHub.broadcast`)."""

    async def __call__(self, message: SpecModel) -> None: ...


class MqttSender(Protocol):
    """`aegis/alert` 발행 능력(`server/infra/mqtt`)."""

    async def publish_alert(self, command: AlertCommand) -> None: ...


@dataclass(frozen=True, slots=True)
class MuteWindow:
    """FN-ALM-05 — 이 카메라의 경고를 언제까지 멈추는가."""

    until: datetime
    reason: str

    def active(self, at: datetime) -> bool:
        return at < self.until


#: `_mutes` 에서 「전체 카메라」를 가리키는 키. §4.5 는 `cam_id` 생략을 그렇게 정의한다.
#:
#: `None` 을 그대로 키로 쓴다 — 0 이나 -1 같은 가짜 카메라 번호를 만들면 실제 카메라
#: 번호와 섞일 수 있고, 그때 조용히 잘못된 카메라의 경고가 멎는다.
ALL_CAMERAS: None = None


class AlertService:
    """경고 한 번을 소리와 빛으로 옮긴다."""

    def __init__(
        self,
        *,
        library: SoundLibrary,
        player: SoundPlayer,
        clock: Clock,
        mcu: McuRuntime,
        mqtt: MqttSender | None = None,
        publish: Broadcaster | None = None,
        alert_duration_s: int = 5,
    ) -> None:
        self._library = library
        self._player = player
        self._clock = clock
        self._mcu = mcu
        self._mqtt = mqtt
        self._publish = publish
        self._alert_duration_s = alert_duration_s
        self._mutes: dict[int | None, MuteWindow] = {}
        """카메라별 일시중지 창. 키 `None` 은 전체 카메라(§4.5 `cam_id` 생략)."""
        self._default_mute_s = Policies().mute_default_duration_s
        self._latencies_ms: list[float] = []
        self.sound_failed = 0
        """소리를 내지 못한 누적 건수. 0이 아니면 방송이 나가지 않은 이벤트가 있다."""

    # -- 기동 ------------------------------------------------------------

    async def start(self) -> None:
        await self._library.refresh()
        log.info(
            "경고 집행 준비 — 재생기=%s 음원=%d종 (%s)",
            self._player.name,
            len(self._library.keys),
            self._library.root,
        )

    async def refresh_sounds(self) -> None:
        await self._library.refresh()

    def set_policies(self, policies: Policies) -> None:
        """`mute_default_duration_s`(§4.5)를 DB 값으로 갈아끼운다(절대규칙 6)."""
        self._default_mute_s = policies.mute_default_duration_s

    def severity_map(self) -> Mapping[ViolationType, AlertLevel]:
        """DB `alert_sounds.level` 이 정한 유형별 위험 등급(§6 · FN-CFG-03).

        **상태머신에 주입하기 위한 값이다.** §6 이 "관리자가 설정 화면에서 유형별 음원과
        등급을 바꿀 수 있다"고 정했으므로 등급의 원천은 코드가 아니라 DB 다(절대규칙 6).
        상태머신은 이 매핑을 받아 `AlertIntent.level` 과 §5.2 `severity` 를 같은 값으로
        만든다 — 여기서 따로 덮어쓰면 ESP32 가 받은 등급과 화면에 뜬 등급이 갈린다.

        등록되지 않은 유형은 **빼고** 준다. 상태머신이 자기 기본표(`SEVERITY`)를
        유지하므로, 시드가 빠진 유형에 `2` 를 지어내지 않는다.
        """
        found: dict[ViolationType, AlertLevel] = {}
        for key, entry in self._library.entries.items():
            try:
                found[ViolationType(key)] = entry.level
            except ValueError:
                # 수동 방송용 키(`custom_notice` 등)다. 위반 유형이 아니므로 건너뛴다.
                continue
        return found

    # -- 자동 경고 (FN-ALM-01 · 02) ---------------------------------------

    async def fire(self, intent: AlertIntent) -> bool:
        """확정·재경고가 만든 경고 한 번을 집행한다. **방송이 나갔으면 `True`.**

        일시중지 중이면 **장치만 조용하고 이벤트는 그대로 진행한다**(FN-ALM-05) —
        이벤트까지 멈추면 정비 시간 동안의 위반이 통째로 사라져 그 구간에 사고가 나도
        기록이 없다. 다만 `False` 를 돌려주어 호출자가 `alert_suppressed` 를 기록하게
        하고, 그 이벤트는 「방송 후」 시정률에서 제외된다(§4.8).
        """
        now = self._clock.now()
        if (mute := self._muted(intent.cam_id, now)) is not None:
            log.warning(
                "경고 일시중지 중 — %s (cam=%s, 사유: %s, 해제 %s). "
                "이벤트는 그대로 진행하되 방송·경광등이 나가지 않으므로 "
                "시정률 모집단에서 제외된다(alert_suppressed)",
                intent.event_id,
                intent.cam_id,
                mute.reason,
                mute.until.isoformat(),
            )
            return False

        await self._play(intent.violation_type.value, event_id=intent.event_id, since=intent.at)
        await self._signal(_command(intent, duration_s=self._alert_duration_s), intent.event_id)
        return True

    # -- 수동 방송 (FN-ALM-04) --------------------------------------------

    async def manual(self, request: ManualAlertRequest) -> datetime:
        """`POST /alerts/manual` — 관리자가 고른 음원을 그 카메라 구역에 내보낸다.

        `notify_device` 가 참이면(기본) **요청의 `level` 로 §3 `aegis/alert` 도 발행한다.**
        §4.5 가 그렇게 정의했다. `AlertCommand` 가 요구하는 두 값은 이렇게 채운다.

        * `event_id` = `MANUAL-cam{N}-{ISO8601}` — 이벤트 테이블에 없다는 것이 드러나는
          형태여야 한다. `EV-` 접두사를 쓰면 ESP32 와 대시보드가 조회 가능한 이벤트로
          오해한다.
        * `type` = `zone_intrusion` — §3 `type` 은 `ViolationType` 이고 수동 방송에는
          위반 유형이 없다. **점멸 패턴을 고르는 값**이므로 아무 것이나 될 수 없어,
          「지금 그 구역을 주목하라」에 가장 가까운 일반 경보를 쓴다.

        `type` 을 지어내는 것 자체가 §3 에 수동 방송의 자리가 없다는 뜻이므로
        `docs/INDEX.md` 「명세서 확인 필요」에 남겨 두었다.

        **일시중지를 무시한다.** 사람이 지금 누른 방송이므로, 정비 중이라도 그 사람이
        의도한 것이다. 자동 경고를 멈춘 것과 관리자가 직접 말하는 것은 다른 행위다.
        """
        at = self._clock.now()
        key = request.sound or DEFAULT_MANUAL_SOUND
        log.info(
            "수동 방송 — cam=%s sound=%s level=%s 장치=%s",
            request.cam_id,
            key,
            request.level,
            "발행" if request.notify_device else "생략",
        )
        event_id = f"{MANUAL_EVENT_PREFIX}-cam{request.cam_id}-{at.isoformat()}"
        await self._play(key, event_id=event_id, since=None)
        if request.notify_device:
            await self._signal(
                AlertCommand(
                    event_id=event_id,
                    type=ViolationType.ZONE_INTRUSION,
                    level=request.level,
                    zone_id=None,
                    duration_s=self._alert_duration_s,
                    repeat=False,
                ),
                event_id,
            )
        return at

    # -- 일시중지 (FN-ALM-05) ---------------------------------------------

    async def mute(self, request: MuteAlertRequest) -> MuteAlertResponse:
        """`POST /alerts/mute` — 정비 작업 등으로 경고를 기한부로 멈춘다.

        **기한이 반드시 있다.** 무기한 중지를 허용하면 꺼둔 사실을 잊는 순간 감시가
        조용히 멎는다(절대규칙 9). `minutes` 를 생략하면 `mute_default_duration_s`
        (기본 900초 = 15분)가 붙고, `0` 이면 즉시 해제다(§4.5).

        `cam_id` 를 생략하면 **전체 카메라**가 대상이다(§4.5).
        """
        now = self._clock.now()
        minutes = self._minutes(request.minutes)
        target = request.cam_id
        scope = f"cam{target}" if target is not None else "전체 카메라"

        if minutes <= 0:
            self._mutes.pop(target, None)
            log.info("경고 일시중지 해제 — %s", scope)
            response = MuteAlertResponse(cam_id=target, muted=False, muted_until=None, reason=None)
        else:
            window = MuteWindow(until=now + timedelta(minutes=minutes), reason=request.reason)
            self._mutes[target] = window
            log.warning(
                "경고 일시중지 — %s %d분 (사유: %s, 해제 %s). 이 동안 방송과 경광등이 "
                "나가지 않으며, 그때 확정된 이벤트는 시정률에서 제외된다",
                scope,
                minutes,
                request.reason,
                window.until.isoformat(),
            )
            response = MuteAlertResponse(
                cam_id=target,
                muted=True,
                muted_until=window.until,
                reason=window.reason,
            )

        # 꺼져 있다는 사실이 화면에 드러나야 한다. §5.3 에 「경고」 구성요소가 없어
        # `mcu`(경광등·부저) 상태로 실어 보낸다 — 실제로 그 장치가 조용해지기 때문이다.
        await self._emit(
            ComponentSystemMsg(
                component="mcu",
                state="degraded" if minutes > 0 else self._mcu.state(now),
                detail=(
                    f"{scope} 경고 일시중지 {minutes}분 — {request.reason}"
                    if minutes > 0
                    else f"{scope} 경고 일시중지 해제"
                ),
                at=now,
            )
        )
        return response

    def mute_status(self, cam_id: int | None) -> MuteAlertResponse:
        """`GET /alerts/mute` — 지금 상태. §4.5 가 `POST` 와 같은 형태를 요구한다.

        `cam_id` 를 주면 **그 카메라에 실제로 걸리는** 창을 본다 — 전체 대상 일시중지가
        켜져 있으면 카메라별 창이 없어도 조용하다. 화면이 "이 카메라는 안 멈췄다"고
        표시하면 안 되는 상황이 그것이다.
        """
        window = self._muted(cam_id, self._clock.now()) if cam_id is not None else None
        if cam_id is None:
            window = self._active(None, self._clock.now())
        if window is None:
            return MuteAlertResponse(cam_id=cam_id, muted=False, muted_until=None, reason=None)
        return MuteAlertResponse(
            cam_id=cam_id,
            muted=True,
            muted_until=window.until,
            reason=window.reason,
        )

    def muted(self, cam_id: int) -> MuteWindow | None:
        """지금 이 카메라의 경고가 멈춰 있는가(전체 대상 중지 포함). 만료된 창은 지운다."""
        return self._muted(cam_id, self._clock.now())

    def _muted(self, cam_id: int, at: datetime) -> MuteWindow | None:
        """카메라별 창을 먼저 보고, 없으면 전체 대상 창을 본다.

        **둘 중 하나라도 살아 있으면 조용하다.** 카메라별 창만 보면 "전체 정비 중"이
            무시되어 방송이 나간다.
        """
        return self._active(cam_id, at) or self._active(ALL_CAMERAS, at)

    def _active(self, key: int | None, at: datetime) -> MuteWindow | None:
        window = self._mutes.get(key)
        if window is None:
            return None
        if not window.active(at):
            self._mutes.pop(key, None)
            return None
        return window

    def _minutes(self, requested: int | None) -> int:
        """요청이 길이를 주지 않으면 정책 기본값(초 → 분)을 붙인다.

        **0 으로 떨어지지 않게 올림한다.** 정책값이 30초처럼 1분 미만이면 내림하면
        0 이 되어 "즉시 해제"로 뒤집힌다 — 일시중지를 요청했는데 해제되는 것이
        가장 나쁜 결과다.
        """
        if requested is not None:
            return requested
        return max(1, math.ceil(self._default_mute_s / 60.0))

    # -- 실측 (FN-ALM-01 요구: 1초 이내) -----------------------------------

    @property
    def latencies_ms(self) -> list[float]:
        """확정 → 재생 시작까지 걸린 시간들. 시연·보고용 실측치다."""
        return list(self._latencies_ms)

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    async def _play(self, key: str, *, event_id: str, since: datetime | None) -> None:
        """음원 하나를 튼다. 실패는 집계하되 위로 던지지 않는다."""
        try:
            path: Path = self._library.path_for(key)
        except SoundNotFoundError as exc:
            self.sound_failed += 1
            log.error("경고 방송 실패 — %s: %s", event_id, exc)
            return
        try:
            await play_async(self._player, path)
        except Exception as exc:
            self.sound_failed += 1
            log.error(
                "경고 방송 실패 — %s: %s: %s (재생기=%s)",
                event_id,
                type(exc).__name__,
                exc,
                self._player.name,
            )
            return
        self._record_latency(event_id, key, since)

    def _record_latency(self, event_id: str, key: str, since: datetime | None) -> None:
        if since is None:
            log.info("방송 시작 — %s (%s)", event_id, key)
            return
        elapsed_ms = (self._clock.now() - since).total_seconds() * 1000.0
        self._latencies_ms.append(elapsed_ms)
        if elapsed_ms > LATENCY_BUDGET_MS:
            # 요구를 넘겼다는 사실은 반드시 드러나야 한다(절대규칙 9). 지연이 커지는
            # 것을 아무도 모르는 채로 두면 시연 당일에야 발견한다.
            log.warning(
                "확정 → 방송 %.0fms — FN-ALM-01 요구(%.0fms)를 넘겼다: %s (%s)",
                elapsed_ms,
                LATENCY_BUDGET_MS,
                event_id,
                key,
            )
        else:
            log.info("방송 시작 — %s (%s) 확정 후 %.0fms", event_id, key, elapsed_ms)

    async def _signal(self, command: AlertCommand, event_id: str) -> None:
        """`aegis/alert` 발행. FN-ALM-02 · FN-ALM-04

        자동 경고와 수동 방송이 같은 경로를 쓴다 — 발행 실패를 집계하고 `mcu` 상태로
        드러내는 규칙이 둘에 똑같이 적용되어야 한다.
        """
        if self._mqtt is None:
            return
        try:
            await self._mqtt.publish_alert(command)
        except Exception as exc:
            await self._emit(
                self._mcu.publish_failure(self._clock.now(), f"{type(exc).__name__}: {exc}")
            )
            log.error("경광등 경고 발행 실패 — %s: %s", event_id, exc)
            return
        log.info(
            "경광등 경고 발행 — %s type=%s level=%s repeat=%s",
            event_id,
            command.type.value,
            command.level,
            command.repeat,
        )

    async def _emit(self, message: SpecModel | None) -> None:
        if message is None or self._publish is None:
            return
        await self._publish(message)


def _command(intent: AlertIntent, *, duration_s: int) -> AlertCommand:
    """`AlertIntent` → §3 `AlertCommand`.

    `duration_s`(경광등·부저 지속 시간)만 서버 설정에서 붙는다. 상태머신이 그 값까지
    들고 있으면 「언제 경고하는가」와 「경광등을 몇 초 켜는가」가 한 곳에 섞인다.
    """
    level: AlertLevel = intent.level
    violation: ViolationType = intent.violation_type
    return AlertCommand(
        event_id=intent.event_id,
        type=violation,
        level=level,
        zone_id=intent.zone_id,
        duration_s=duration_s,
        repeat=intent.repeat,
    )
