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

from aegis_contracts import ManualAlertRequest, MuteAlertRequest, Policies, ViolationType
from aegis_vision.clock import FakeClock
from server.app.alert_service import LATENCY_BUDGET_MS, AlertService
from server.domain.alerts import AlertIntent, SoundEntry

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
    sounds = FakeSoundStore(
        {"no_helmet": SoundEntry(file_path="custom_notice.wav", level=2, label=None)}
    )
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


def test_fire_reports_whether_the_broadcast_actually_went_out() -> None:
    """★ §4.8 — 일시중지로 조용했다는 사실이 **호출자에게 돌아가야** 한다.

    이 반환값이 `events.alert_suppressed` 가 되고, 그 칸이 참인 이벤트는 「방송 후」
    시정률 모집단에서 빠진다. `None` 을 돌려주던 시절에는 집행 계층이 "방송이 나갔는지"
    를 알 방법이 없어 알린 적 없는 위반이 미시정으로 집계됐다.
    """
    service = started(FakeClock(NOW), player=FakePlayer())

    assert run(service.fire(intent(cam_id=1))) is True

    run(service.mute(MuteAlertRequest(cam_id=1, minutes=15, reason="정비 작업")))
    assert run(service.fire(intent(cam_id=1))) is False
    # 다른 카메라는 그대로 나간다 — 중지는 카메라 단위다.
    assert run(service.fire(intent(cam_id=2))) is True


def test_a_broken_speaker_still_counts_as_dispatched() -> None:
    """재생 실패는 `alert_suppressed` 가 아니다.

    "사람이 일부러 멈췄다"와 "내보내려 했으나 장치가 고장났다"는 다르다. 후자를
    지표에서 빼면 **장애가 시정률을 좋아 보이게 만든다.**
    """
    service = started(FakeClock(NOW), player=FakePlayer(fail=True))

    assert run(service.fire(intent())) is True
    assert service.sound_failed == 1


def test_muting_all_cameras_silences_every_camera() -> None:
    """§4.5 — `cam_id` 를 생략하면 전체 카메라 대상이다."""
    player = FakePlayer()
    service = started(FakeClock(NOW), player=player)

    run(service.mute(MuteAlertRequest(minutes=15, reason="전체 점검")))

    assert run(service.fire(intent(cam_id=1))) is False
    assert run(service.fire(intent(cam_id=2))) is False
    assert player.played == []
    # 카메라별 창이 없어도 **실제로 걸린다.** 하나만 보면 "안 멈췄다"고 잘못 표시한다.
    assert service.muted(1) is not None
    assert service.mute_status(1).muted is True


def test_the_mute_response_says_when_it_lifts() -> None:
    """§4.5 응답 — 화면이 「언제 풀리는지」를 다시 물어볼 수 있어야 한다.

    204 로만 답하던 시절에는 새로고침 한 번에 "경고가 꺼져 있다"는 사실이 화면에서
    사라졌다. 그 상태는 오탐보다 위험하다.
    """
    clock = FakeClock(NOW)
    service = started(clock, player=FakePlayer())

    response = run(service.mute(MuteAlertRequest(cam_id=1, minutes=15, reason="정비 작업")))
    assert response.cam_id == 1
    assert response.muted is True
    assert response.muted_until == NOW + timedelta(minutes=15)
    assert response.reason == "정비 작업"
    # 조회도 같은 형태다.
    assert service.mute_status(1) == response

    released = run(service.mute(MuteAlertRequest(cam_id=1, minutes=0, reason="완료")))
    assert released.muted is False
    assert released.muted_until is None
    assert released.reason is None


def test_omitting_minutes_uses_the_policy_default() -> None:
    """§4.5 `mute_default_duration_s`(기본 900초) — **기한 없는 중지는 만들 수 없다.**"""
    clock = FakeClock(NOW)
    service = started(clock, player=FakePlayer())

    response = run(service.mute(MuteAlertRequest(cam_id=1, reason="정비 작업")))

    assert response.muted_until == NOW + timedelta(minutes=15)


def test_the_policy_default_is_read_from_the_db_not_the_code() -> None:
    """절대규칙 6 — 정책값을 갈아끼우면 기한도 따라 바뀐다."""
    clock = FakeClock(NOW)
    service = started(clock, player=FakePlayer())
    service.set_policies(Policies(mute_default_duration_s=300.0))

    response = run(service.mute(MuteAlertRequest(cam_id=1, reason="정비 작업")))

    assert response.muted_until == NOW + timedelta(minutes=5)


def test_a_sub_minute_policy_default_does_not_collapse_into_a_release() -> None:
    """0분으로 내림되면 「즉시 해제」로 뒤집힌다 — 중지를 요청했는데 켜지는 셈이다."""
    clock = FakeClock(NOW)
    service = started(clock, player=FakePlayer())
    service.set_policies(Policies(mute_default_duration_s=30.0))

    response = run(service.mute(MuteAlertRequest(cam_id=1, reason="짧은 점검")))

    assert response.muted is True
    assert response.muted_until == NOW + timedelta(minutes=1)


def test_the_severity_map_comes_from_the_sound_library() -> None:
    """§6 `alert_sounds.level` — 등급의 원천은 코드가 아니라 DB 다(FN-CFG-03).

    상태머신에 주입할 매핑을 여기서 만든다. 위반 유형이 아닌 키(`custom_notice`)는
    빠져야 한다 — 그것을 열거형으로 변환하려 하면 터진다.
    """
    service = started(FakeClock(NOW), player=FakePlayer())

    severity = service.severity_map()

    assert severity[ViolationType.FALL] == 3
    assert severity[ViolationType.NO_HELMET] == 2
    assert len(severity) == 4  # `custom_notice` 는 위반 유형이 아니다


def test_an_unregistered_violation_is_left_to_the_state_machine_default() -> None:
    """등록되지 않은 유형에 `2` 를 지어내지 않는다.

    시드가 빠진 상태와 관리자가 2로 정한 상태는 다르다. 상태머신이 자기 기본표
    (`SEVERITY`)를 유지하도록 **빼고** 준다.
    """
    service = started(
        FakeClock(NOW),
        player=FakePlayer(),
        sounds=FakeSoundStore(
            {"no_helmet": SoundEntry(file_path="no_helmet.wav", level=1, label=None)}
        ),
    )

    severity = service.severity_map()

    assert severity == {ViolationType.NO_HELMET: 1}


def test_manual_broadcast_ignores_the_mute() -> None:
    """FN-ALM-04 — 사람이 지금 누른 방송이다. 정비 중이라도 그 사람이 의도한 것이다."""
    player = FakePlayer()
    mqtt = FakeMqtt()
    service = started(FakeClock(NOW), player=player, mqtt=mqtt)

    run(service.mute(MuteAlertRequest(cam_id=1, minutes=15, reason="정비 작업")))
    run(service.manual(ManualAlertRequest(cam_id=1, sound="custom_notice", level=2)))

    assert [path.name for path in player.played] == ["custom_notice.wav"]


def test_notify_device_publishes_the_manual_level_to_mqtt() -> None:
    """FN-ALM-04 · §4.5 — `notify_device`(기본 참)면 `level` 로 §3 도 발행한다.

    `event_id` 가 `EV-` 로 시작하면 안 된다 — 수동 방송에는 이벤트 레코드가 없으므로,
    조회 가능한 이벤트처럼 보이는 ID 를 내보내면 ESP32 와 대시보드가 존재하지 않는
    것을 참조한다.
    """
    mqtt = FakeMqtt()
    service = started(FakeClock(NOW), player=FakePlayer(), mqtt=mqtt)

    run(service.manual(ManualAlertRequest(cam_id=1, sound="custom_notice", level=3)))

    assert len(mqtt.published) == 1
    command = mqtt.published[0]
    assert command.level == 3
    assert command.repeat is False
    assert command.event_id.startswith("MANUAL-cam1-")
    assert not command.event_id.startswith("EV-")


def test_notify_device_false_keeps_the_beacon_dark() -> None:
    """§4.5 — 스피커만 울리고 경광등은 끄고 싶을 때."""
    player = FakePlayer()
    mqtt = FakeMqtt()
    service = started(FakeClock(NOW), player=player, mqtt=mqtt)

    run(
        service.manual(
            ManualAlertRequest(cam_id=1, sound="custom_notice", level=2, notify_device=False)
        )
    )

    assert [path.name for path in player.played] == ["custom_notice.wav"]
    assert mqtt.published == []


def test_manual_broadcast_without_a_sound_uses_the_default_notice() -> None:
    """§4.5 — `sound` 미지정 시 기본 안내 음원. 파일명은 그래도 DB 에서 온다."""
    player = FakePlayer()
    service = started(FakeClock(NOW), player=player)

    run(service.manual(ManualAlertRequest(cam_id=1, level=2)))

    assert [path.name for path in player.played] == ["custom_notice.wav"]


def test_a_sound_name_cannot_escape_the_audio_directory() -> None:
    """수동 방송의 `sound` 는 바깥에서 온다. 그것이 경로가 되면 서버 파일이 열린다."""
    player = FakePlayer()
    service = started(
        FakeClock(NOW),
        player=player,
        sounds=FakeSoundStore({"evil": SoundEntry(file_path="../../.env", level=2, label=None)}),
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
