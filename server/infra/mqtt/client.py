"""MQTT — `aegis/alert` 발행, `aegis/device/status` 구독. FN-ALM-02 · FN-SYS-01

출처: API명세서 §3

두 방향이 있고 뜻이 다르다.

| 방향 | 토픽 | 내용 |
|---|---|---|
| 서버 → ESP32 | `aegis/alert` | `AlertCommand` — 유형·등급·지속시간·재경고 여부 |
| ESP32 → 서버 | `aegis/device/status` | `DeviceStatus` — 주기 생존 보고 |

**브로커가 죽어도 안전 루프는 계속 돈다.** paho 가 자동 재연결을 맡고, 발행 실패는
예외로 올라와 집행 계층이 잡아 집계한다(`McuRuntime.publish_failure`). 경광등이 울리지
않은 것을 조용히 넘기지 않되(절대규칙 9), 그 실패가 확정·시정 판정을 막지도 않는다.

**paho 는 자기 스레드에서 돈다.** 그래서 구독 콜백은 이벤트 루프 밖에서 불린다.
거기서 `await` 를 쓸 수 없으므로 `run_coroutine_threadsafe` 로 루프에 되던진다 —
루프를 모른 채 `asyncio.run` 을 부르면 두 번째 루프가 생겨 허브 전송이 엉킨다.
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import Any, Protocol, Self

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from pydantic import ValidationError

from aegis_contracts import (
    ALERT_TOPIC,
    DEVICE_STATUS_TOPIC,
    AlertCommand,
    DeviceStatus,
    SpecModel,
)
from aegis_vision.clock import Clock
from server.domain.mcu_state import McuRuntime

__all__ = ["AlertPublisher", "MqttAlertClient", "MqttUnavailableError"]

log = logging.getLogger("server.mqtt")


class MqttUnavailableError(RuntimeError):
    """브로커에 닿지 못했거나 발행이 큐에 들어가지 못했다."""


class AlertPublisher(Protocol):
    """경고 발행 능력. 테스트가 가짜를 끼워 넣는 자리다."""

    async def publish_alert(self, command: AlertCommand) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class MqttAlertClient:
    """`aegis/alert` 를 내보내고 `aegis/device/status` 를 받아 `McuRuntime` 에 반영한다."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        mcu: McuRuntime,
        clock: Clock,
        publish: object = None,
        client_id: str = "aegis-server",
        keepalive: int = 60,
    ) -> None:
        self._host = host
        self._port = port
        self._mcu = mcu
        self._clock = clock
        # `Publisher`(대시보드 허브)를 직접 타입으로 받지 않는 이유는 순환 import 다.
        # 넘어오는 것은 `async def (SpecModel) -> None` 하나뿐이다.
        self._publish = publish
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=client_id)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        # 브로커가 늦게 뜨는 것은 정상이다(docker compose 순서). 재연결 간격에 상한을
        # 두어 끊긴 뒤에도 최대 이 간격으로 계속 두드린다.
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._keepalive = keepalive
        self._started = False

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.stop()

    async def start(self) -> None:
        """연결을 **비동기로** 건다. 브로커가 없어도 서버 기동을 막지 않는다.

        `connect_async` + `loop_start` 조합이라 여기서 블로킹하지 않는다. 브로커가 뒤늦게
        떠도 paho 가 알아서 붙고, 그때 `on_connect` 가 상태를 `ok` 로 올린다.
        """
        self._loop = asyncio.get_running_loop()
        self._client.connect_async(self._host, self._port, keepalive=self._keepalive)
        self._client.loop_start()
        self._started = True
        log.info("MQTT 연결 시도 — %s:%s (경고 발행 · 장치 상태 구독)", self._host, self._port)

    async def stop(self) -> None:
        if not self._started:
            return
        self._client.loop_stop()
        self._client.disconnect()
        self._started = False

    async def publish_alert(self, command: AlertCommand) -> None:
        """`aegis/alert` 발행. FN-ALM-02

        QoS 1 이다. 경고가 한 번 더 울리는 것(중복 수신)보다 **울리지 않는 것**이 나쁘고,
        ESP32 는 같은 `event_id` 를 두 번 받아도 같은 패턴을 이어 켤 뿐이다.
        """
        payload = command.model_dump_json(by_alias=True)
        info = await asyncio.to_thread(self._client.publish, ALERT_TOPIC, payload, 1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            msg = f"aegis/alert 발행 실패 (rc={info.rc}, {self._host}:{self._port})"
            raise MqttUnavailableError(msg)

    # -- paho 콜백 (다른 스레드에서 불린다) --------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any = None,
    ) -> None:
        client.subscribe(DEVICE_STATUS_TOPIC, qos=1)
        self._emit(
            self._mcu.broker(
                connected=True,
                at=self._clock.now(),
                detail=f"MQTT 브로커 연결 ({reason_code})",
            )
        )
        log.info("MQTT 연결됨 (%s) — %s 구독", reason_code, DEVICE_STATUS_TOPIC)

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: Any = None,
        reason_code: Any = None,
        _properties: Any = None,
    ) -> None:
        self._emit(
            self._mcu.broker(
                connected=False,
                at=self._clock.now(),
                detail=f"MQTT 브로커 연결 끊김 ({reason_code})",
            )
        )
        log.warning("MQTT 연결 끊김 (%s) — 경광등 경고가 나가지 않는다", reason_code)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        if message.topic != DEVICE_STATUS_TOPIC:
            return
        try:
            status = DeviceStatus.model_validate_json(message.payload)
        except ValidationError as exc:
            # 조용히 버리지 않는다(절대규칙 9). 장치 펌웨어가 계약과 어긋나기 시작하면
            # `mcu.online` 이 영영 false 로 남는데, 로그가 없으면 원인이 보이지 않는다.
            log.warning("device/status 가 API명세서 §3 과 다르다: %s", exc)
            return
        self._emit(self._mcu.apply_status(status, self._clock.now()))

    def _emit(self, message: SpecModel | None) -> None:
        """paho 스레드에서 만든 §5.3 메시지를 이벤트 루프로 넘긴다."""
        if message is None or self._publish is None or self._loop is None:
            return
        publish = self._publish
        if not callable(publish):
            return
        try:
            asyncio.run_coroutine_threadsafe(publish(message), self._loop)
        except RuntimeError as exc:
            # 루프가 이미 닫혔다(종료 중). 상태 표시가 한 건 빠질 뿐 안전 기능과 무관하다.
            log.debug("system 메시지를 루프로 넘기지 못했다: %s", exc)
