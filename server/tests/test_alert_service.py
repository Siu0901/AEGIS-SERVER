"""경고 발동 — FN-ALM-01 ~ FN-ALM-05 (기능명세서 §4.3 · API명세서 §3 · §4.5).

여기서 잠그는 것은 **소리와 빛이 실제로 나갔는가**다. 상태머신이 `alerted` 로 갔다는
사실은 M3 이 이미 검증했고, M4 가 더한 것은 그 순간 스피커와 경광등이 울리는 부분이다.

시스템 시계를 읽지 않는다(CLAUDE.md 절대규칙 1). `FakeClock` 을 감아 1초 예산과
일시중지 기한을 순간이동시킨다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aegis_contracts import ManualAlertRequest, MuteAlertRequest, ViolationType
from aegis_vision.clock import FakeClock
from server.app.alert_service import LATENCY_BUDGET_MS, AlertService
from server.domain.alerts import AlertIntent

from .conftest import FakeMqtt, FakePlayer, FakeSoundStore, make_alerts

NOW = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)


def intent(
    *,
    violation: ViolationType = ViolationType.NO_HELMET,
    level: int = 2,
    repeat: bool = False,
    at: datetime = NOW,
    cam_id: int = 1,
) -> AlertIntent:
    return AlertIntent(
        event_id="EV-20260814-0231",
        cam_id=cam_id,
        violation_type=violation,
        level=level,  # type: ignore[arg-type]
        zone_id="forklift_lane",
        repeat=repeat,
        at=at,
    )


def run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """이 레포의 테스트는 `pytest-asyncio` 를 쓰지 않는다(기존 테스트와 같은 방식).

    `AlertService` 의 호출들은 서로 상태를 루프에 남기지 않으므로 매 호출을 따로
    돌려도 결과가 같다.
    """
    return asyncio.run(awaitable)


def started(clock: FakeClock, **kwargs: object) -> AlertService:
    """음원 매핑까지 읽은 `AlertService`. 실서버의 기동 순서와 같다."""
    service = make_alerts(clock, **kwargs)  # type: ignore[arg-type]
    run(service.start())
    return service


def test_confirmation_plays_the_prerecorded_wav_for_that_violation() -> None:
    """FN-ALM-01 — 위반 유형에 **사전 매핑된** 파일을 튼다. TTS 가 아니다."""
    player = FakePlayer()
    service = started(FakeClock(NOW), player=player)

    run(service.fire(intent()))

    assert [path.name for path in player.played] == ["no_helmet.wav"]


def test_the_sound_mapping_comes_from_the_store_not_from_the_code() -> None:
    """FN-CFG-03 · 절대규칙 6 — 파일명이 코드에 없다. 매핑을 바꾸면 다른 파일이 난다."""
    player = FakePlayer()
    sounds = FakeSoundStore({"no_helmet": "custom_notice.wav"})
    service = started(FakeClock(NOW), player=player, sounds=sounds)

    run(service.fire(intent()))

    assert [path.name for path in player.played] == ["custom_notice.wav"]
    assert sounds.calls == 1


def test_the_mqtt_command_matches_the_spec_and_fall_is_always_level_three() -> None:
    """FN-ALM-02 · API명세서 §3 — `level` 은 1|2|3 이고 `fall` 은 항상 3 이다."""
    mqtt = FakeMqtt()
    service = started(FakeClock(NOW), mqtt=mqtt)

    run(service.fire(intent(violation=ViolationType.FALL, level=3)))

    assert len(mqtt.published) == 1
    command = mqtt.published[0]
    assert command.type is ViolationType.FALL
    assert command.level == 3
    assert command.zone_id == "forklift_lane"
    assert command.repeat is False
    assert command.duration_s > 0


def test_re_alert_is_marked_so_the_device_can_show_a_repeat_pattern() -> None:
    """§3 `repeat` — ESP32 가 상습 상황을 다른 점멸로 구분한다."""
    mqtt = FakeMqtt()
    service = started(FakeClock(NOW), mqtt=mqtt)

    run(service.fire(intent(repeat=True)))

    assert mqtt.published[0].repeat is True


def test_a_broken_speaker_does_not_stop_the_beacon() -> None:
    """두 경로는 서로를 막지 않는다. 한쪽 고장이 둘 고장이 되면 안 된다.

    소음이 심한 구역에서는 경광등이 유일한 경보이므로, 스피커가 죽었다고 그쪽까지
    건너뛰면 그 구역은 아무 경보도 받지 못한다.
    """
    player = FakePlayer(fail=True)
    mqtt = FakeMqtt()
    service = started(FakeClock(NOW), player=player, mqtt=mqtt)

    run(service.fire(intent()))

    assert player.played == []
    assert service.sound_failed == 1
    assert len(mqtt.published) == 1


def test_a_broken_broker_does_not_stop_the_broadcast() -> None:
    """반대 방향도 같다. 브로커가 죽어도 방송은 나간다."""
    player = FakePlayer()
    mqtt = FakeMqtt(fail=True)
    service = started(FakeClock(NOW), player=player, mqtt=mqtt)

    run(service.fire(intent()))

    assert [path.name for path in player.played] == ["no_helmet.wav"]
    assert mqtt.published == []


def test_a_missing_sound_is_counted_not_swallowed() -> None:
    """등록되지 않은 유형은 **조용히 넘어가지 않는다**(CLAUDE.md 절대규칙 9).

    "재생했다"는 기록만 남고 아무 소리도 나지 않는 상태가 가장 위험하다.
    """
    player = FakePlayer()
    service = started(FakeClock(NOW), player=player, sounds=FakeSoundStore({}))

    run(service.fire(intent()))

    assert player.played == []
    assert service.sound_failed == 1


def test_muting_silences_the_devices_for_that_camera_only() -> None:
    """FN-ALM-05 — 카메라 단위다. 정비 중인 라인 때문에 다른 라인이 조용해지지 않는다."""
    player = FakePlayer()
    mqtt = FakeMqtt()
    service = started(FakeClock(NOW), player=player, mqtt=mqtt)

    run(service.mute(MuteAlertRequest(cam_id=1, minutes=15, reason="정비 작업")))
    run(service.fire(intent(cam_id=1)))
    run(service.fire(intent(cam_id=2)))

    assert len(player.played) == 1
    assert len(mqtt.published) == 1
    assert service.muted(1) is not None
    assert service.muted(2) is None


def test_a_mute_expires_on_its_own() -> None:
    """**기한이 반드시 있다.** 꺼둔 것을 잊는 순간 감시가 조용히 멎으면 안 된다."""
    clock = FakeClock(NOW)
    player = FakePlayer()
    service = started(clock, player=player)

    run(service.mute(MuteAlertRequest(cam_id=1, minutes=15, reason="정비 작업")))
    clock.set(NOW + timedelta(minutes=16))
    run(service.fire(intent()))

    assert len(player.played) == 1
    assert service.muted(1) is None


def test_zero_minutes_releases_the_mute_immediately() -> None:
    clock = FakeClock(NOW)
    player = FakePlayer()
    service = started(clock, player=player)

    run(service.mute(MuteAlertRequest(cam_id=1, minutes=15, reason="정비")))
    run(service.mute(MuteAlertRequest(cam_id=1, minutes=0, reason="작업 종료")))
    run(service.fire(intent()))

    assert len(player.played) == 1


def test_manual_broadcast_ignores_the_mute_and_does_not_touch_the_beacon() -> None:
    """FN-ALM-04 — 사람이 지금 누른 방송이다.

    경광등은 함께 켜지 않는다 — §3 `AlertCommand` 는 `event_id` 와 위반 유형을 필수로
    요구하는데 수동 방송에는 둘 다 없다. 없는 값을 지어내지 않는다.
    """
    player = FakePlayer()
    mqtt = FakeMqtt()
    service = started(FakeClock(NOW), player=player, mqtt=mqtt)

    run(service.mute(MuteAlertRequest(cam_id=1, minutes=15, reason="정비 작업")))
    run(service.manual(ManualAlertRequest(cam_id=1, sound="custom_notice", level=2)))

    assert [path.name for path in player.played] == ["custom_notice.wav"]
    assert mqtt.published == []


def test_a_sound_name_cannot_escape_the_audio_directory() -> None:
    """수동 방송의 `sound` 는 바깥에서 온다. 그것이 경로가 되면 서버 파일이 열린다."""
    player = FakePlayer()
    service = started(
        FakeClock(NOW),
        player=player,
        sounds=FakeSoundStore({"evil": "../../.env"}),
    )

    run(service.manual(ManualAlertRequest(cam_id=1, sound="evil", level=2)))

    assert player.played == []
    assert service.sound_failed == 1


def test_the_latency_is_measured_from_the_observation_time() -> None:
    """FN-ALM-01 — 확정 시점부터 방송 시작까지. 기준은 **관측 시각**이다.

    서버 수신 시각을 쓰면 네트워크 지연이 예산에서 빠져 실제보다 좋아 보인다.
    """
    clock = FakeClock(NOW)
    service = started(clock, player=FakePlayer())

    clock.set(NOW + timedelta(milliseconds=120))
    run(service.fire(intent(at=NOW)))

    assert service.latencies_ms == pytest.approx([120.0])
    assert service.latencies_ms[0] < LATENCY_BUDGET_MS


def test_a_failed_broadcast_is_not_recorded_as_a_latency_sample() -> None:
    """소리가 나지 않았으면 "몇 ms 만에 방송했다"는 숫자도 없어야 한다."""
    service = started(FakeClock(NOW), player=FakePlayer(fail=True))

    run(service.fire(intent()))

    assert service.latencies_ms == []
