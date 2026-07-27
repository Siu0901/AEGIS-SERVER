"""가짜 ESP32 — `aegis/alert` 구독, `aegis/device/status` 주기 발행.

    uv run python -m sim.mcu_sim.main
    uv run python -m sim.mcu_sim.main --host localhost --port 1883 --device esp32-01

실물 ESP32는 `level` 에 따라 점멸 패턴과 부저를 제어한다(1=주의·부저 없음,
2=경고, 3=긴급·연속 부저 — **`fall` 은 항상 3**). 여기서는 콘솔에 그대로 찍는다.

시각은 `Clock` 에서만 얻는다(CLAUDE.md 절대규칙 1).
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from pydantic import ValidationError

from aegis_contracts import ALERT_TOPIC, DEVICE_STATUS_TOPIC, AlertCommand, DeviceStatus
from aegis_vision.clock import Clock, RealClock

__all__ = ["main", "run"]

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 1883
DEFAULT_STATUS_INTERVAL_S = 10

#: `level` → 실물 장치의 동작. API명세서 §3.
_LEVEL_BEHAVIOR = {
    1: "주의 · 경광등만",
    2: "경고 · 경광등 + 단속 부저",
    3: "긴급 · 경광등 + 연속 부저",
}


def _on_alert(payload: bytes | bytearray) -> None:
    try:
        command = AlertCommand.model_validate_json(payload)
    except ValidationError as exc:
        print(f"[mcu_sim] 경고 메시지 파싱 실패: {exc}", file=sys.stderr)
        return

    behavior = _LEVEL_BEHAVIOR.get(command.level, f"알 수 없는 등급 {command.level}")
    repeat = " (재경고)" if command.repeat else ""
    zone = f" · {command.zone_id}" if command.zone_id else ""
    print(
        f"[mcu_sim] ALERT {command.event_id} · {command.type}{zone}{repeat}"
        f"  → {behavior}, {command.duration_s}s"
    )


def run(
    *,
    host: str,
    port: int,
    device: str,
    status_interval_s: int,
    clock: Clock,
) -> None:
    started = clock.monotonic()
    last_alert: Any = None

    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=device)

    def on_connect(
        _client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any = None,
    ) -> None:
        print(f"[mcu_sim] 브로커 연결 ({reason_code}) — {ALERT_TOPIC} 구독")
        _client.subscribe(ALERT_TOPIC)

    def on_message(_client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        nonlocal last_alert
        if message.topic == ALERT_TOPIC:
            _on_alert(message.payload)
            last_alert = clock.now()

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(host, port, keepalive=60)
    client.loop_start()
    print(f"[mcu_sim] {device} 기동 — {host}:{port}, 상태 발행 주기 {status_interval_s}s")

    try:
        while True:
            status = DeviceStatus(
                device=device,
                online=True,
                uptime_s=int(clock.monotonic() - started),
                last_alert=last_alert,
            )
            client.publish(DEVICE_STATUS_TOPIC, status.model_dump_json(by_alias=True))
            time.sleep(status_interval_s)
    finally:
        client.loop_stop()
        client.disconnect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="가짜 ESP32 — MQTT 경고 구독 · 상태 발행")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--device", default="esp32-01")
    parser.add_argument("--interval", type=int, default=DEFAULT_STATUS_INTERVAL_S)
    args = parser.parse_args(argv)

    try:
        run(
            host=args.host,
            port=args.port,
            device=args.device,
            status_interval_s=args.interval,
            clock=RealClock(),
        )
    except KeyboardInterrupt:
        print("\n[mcu_sim] 중단")
        return 130
    except OSError as exc:
        print(f"[mcu_sim] 브로커에 연결할 수 없다: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
