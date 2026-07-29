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
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from aegis_contracts import (
    AlertCommand,
    ComponentSystemMsg,
    ManualAlertRequest,
    MuteAlertRequest,
    SpecModel,
    ViolationType,
)
from aegis_contracts.enums import AlertLevel
from aegis_vision.clock import Clock
from server.domain.alerts import AlertIntent
from server.domain.mcu_state import McuRuntime
from server.infra.audio import SoundLibrary, SoundNotFoundError, SoundPlayer, play_async

__all__ = [
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


class AlertSink(Protocol):
    """`EventService` 가 요구하는 경고 집행자. 시나리오 검사가 가짜를 끼워 넣는 자리다."""

    async def fire(self, intent: AlertIntent) -> None: ...


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
        self._mutes: dict[int, MuteWindow] = {}
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

    # -- 자동 경고 (FN-ALM-01 · 02) ---------------------------------------

    async def fire(self, intent: AlertIntent) -> None:
        """확정·재경고가 만든 경고 한 번을 집행한다.

        일시중지 중이면 **장치만 조용하고 이벤트는 그대로 진행한다**(FN-ALM-05).
        상태머신을 건드리지 않는 이유는 그쪽이 시정률의 정의이기 때문이다 — 다만
        방송이 나가지 않은 채로 분모에 남는 것이 옳은지는 명세서에 정의가 없어
        `docs/INDEX.md` 「명세서 확인 필요」에 올려 두었다.
        """
        now = self._clock.now()
        if (mute := self._mutes.get(intent.cam_id)) is not None and mute.active(now):
            log.warning(
                "경고 일시중지 중 — %s (cam=%s, 사유: %s, 해제 %s). "
                "이벤트는 그대로 진행하며 방송·경광등만 나가지 않는다",
                intent.event_id,
                intent.cam_id,
                mute.reason,
                mute.until.isoformat(),
            )
            return

        await self._play(intent.violation_type.value, event_id=intent.event_id, since=intent.at)
        await self._signal(intent)

    # -- 수동 방송 (FN-ALM-04) --------------------------------------------

    async def manual(self, request: ManualAlertRequest) -> None:
        """`POST /alerts/manual` — 관리자가 고른 음원을 그 카메라 구역에 내보낸다.

        **경광등은 함께 켜지 않는다.** §3 `AlertCommand` 는 `event_id` 와 위반 유형
        (`ViolationType`)을 필수로 요구하는데 수동 방송에는 둘 다 없다. 없는 값을
        지어내면 ESP32 와 대시보드가 존재하지 않는 이벤트를 참조하게 된다.
        요청의 `level` 을 장치로 내보낼 방법이 필요한지는 명세서 확인 대상이다.

        **일시중지를 무시한다.** 사람이 지금 누른 방송이므로, 정비 중이라도 그 사람이
        의도한 것이다. 자동 경고를 멈춘 것과 관리자가 직접 말하는 것은 다른 행위다.
        """
        log.info(
            "수동 방송 — cam=%s sound=%s level=%s", request.cam_id, request.sound, request.level
        )
        await self._play(request.sound, event_id=f"manual:cam{request.cam_id}", since=None)

    # -- 일시중지 (FN-ALM-05) ---------------------------------------------

    async def mute(self, request: MuteAlertRequest) -> MuteWindow:
        """`POST /alerts/mute` — 정비 작업 등으로 그 카메라의 경고를 기한부로 멈춘다.

        **기한이 반드시 있다.** 무기한 중지를 허용하면 꺼둔 사실을 잊는 순간 감시가
        조용히 멎는다(절대규칙 9). `minutes` 를 0 이하로 주면 즉시 해제로 읽는다.
        """
        now = self._clock.now()
        window = MuteWindow(until=now + timedelta(minutes=request.minutes), reason=request.reason)
        if request.minutes <= 0:
            self._mutes.pop(request.cam_id, None)
            log.info("경고 일시중지 해제 — cam=%s", request.cam_id)
        else:
            self._mutes[request.cam_id] = window
            log.warning(
                "경고 일시중지 — cam=%s %d분 (사유: %s, 해제 %s). "
                "이 동안 방송과 경광등이 나가지 않는다",
                request.cam_id,
                request.minutes,
                request.reason,
                window.until.isoformat(),
            )
        # 꺼져 있다는 사실이 화면에 드러나야 한다. §5.3 에 「경고」 구성요소가 없어
        # `mcu`(경광등·부저) 상태로 실어 보낸다 — 실제로 그 장치가 조용해지기 때문이다.
        await self._emit(
            ComponentSystemMsg(
                component="mcu",
                state="degraded" if request.minutes > 0 else self._mcu.state(now),
                detail=(
                    f"cam{request.cam_id} 경고 일시중지 {request.minutes}분 — {request.reason}"
                    if request.minutes > 0
                    else f"cam{request.cam_id} 경고 일시중지 해제"
                ),
                at=now,
            )
        )
        return window

    def muted(self, cam_id: int) -> MuteWindow | None:
        """지금 이 카메라가 일시중지 중인가. 만료된 창은 지운다."""
        window = self._mutes.get(cam_id)
        if window is None:
            return None
        if not window.active(self._clock.now()):
            self._mutes.pop(cam_id, None)
            return None
        return window

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

    async def _signal(self, intent: AlertIntent) -> None:
        """`aegis/alert` 발행. FN-ALM-02"""
        if self._mqtt is None:
            return
        command = _command(intent, duration_s=self._alert_duration_s)
        try:
            await self._mqtt.publish_alert(command)
        except Exception as exc:
            await self._emit(
                self._mcu.publish_failure(self._clock.now(), f"{type(exc).__name__}: {exc}")
            )
            log.error("경광등 경고 발행 실패 — %s: %s", intent.event_id, exc)
            return
        log.info(
            "경광등 경고 발행 — %s type=%s level=%s repeat=%s",
            intent.event_id,
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
