"""클립 예약 추출 — FN-REC-03 (기능명세서 §4.4 · API명세서 §4.7).

가장 중요한 것 둘:

1. **확정 즉시 뽑지 않는다.** 그 순간에는 사후 구간이 아직 녹화되지 않았다.
   너무 일찍 부르면 앞부분만 담긴 클립이 `ready` 로 기록되고, 그 실패는 되돌릴 수 없다.
2. **예약이 DB 에만 있다.** 그래서 서버가 죽어도 남고, 재시작 뒤 첫 조회가 곧 복구다.
   메모리 타이머였다면 재시작 순간 진행 중이던 이벤트의 클립이 영원히 `pending` 이다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aegis_contracts import (
    ClipRequest,
    ClipResponse,
    EventStatus,
    EventUpdatedMsg,
    RecStatusResponse,
    SpecModel,
)
from aegis_contracts.enums import ClipExtractStatus
from aegis_vision.clock import FakeClock
from server.infra.clip import ClipService
from server.infra.rec_client import RecUnavailableError

from .conftest import REC_STATUS, FakeEventStore
from .test_metrics_api import event

NOW = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)
CONFIRMED = datetime(2026, 8, 14, 5, 36, 0, tzinfo=UTC)


def run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


class StubRec:
    """`ClipExtractor` 대역 (§4.7)."""

    def __init__(
        self,
        *,
        extract_status: ClipExtractStatus = "ready",
        available: bool = True,
        reason: str | None = None,
    ) -> None:
        self.extract_status = extract_status
        self.available = available
        self.reason = reason
        self.keyframes: list[tuple[int, datetime]] = []
        self.clips: list[ClipRequest] = []
        self.downloads: list[str] = []
        self.status_calls = 0

    async def status(self) -> RecStatusResponse:
        """§4.7 — 세그먼트 길이는 REC 이 보고한다(기능명세서 §4.4)."""
        self.status_calls += 1
        if not self.available:
            msg = "REC 에 닿지 못했다 (테스트)"
            raise RecUnavailableError(msg)
        return REC_STATUS

    async def keyframe(self, cam_id: int, at: datetime) -> bytes:
        if not self.available:
            msg = "REC 에 닿지 못했다 (테스트)"
            raise RecUnavailableError(msg)
        self.keyframes.append((cam_id, at))
        return b"\xff\xd8\xff\xd9"

    async def create_clip(self, request: ClipRequest) -> ClipResponse:
        if not self.available:
            msg = "REC 에 닿지 못했다 (테스트)"
            raise RecUnavailableError(msg)
        self.clips.append(request)
        if self.extract_status != "ready":
            return ClipResponse(status=self.extract_status, reason=self.reason or "사유 (테스트)")
        return ClipResponse(
            status="ready",
            size_bytes=4,
            download_url=f"/clips/{request.event_id}.mp4",
            actual_from=request.from_,
            actual_to=request.to,
        )

    async def download(self, url: str) -> bytes:
        self.downloads.append(url)
        return b"mp4."


class Captured:
    """§5.2 발행을 모으는 통로."""

    def __init__(self) -> None:
        self.messages: list[SpecModel] = []

    async def __call__(self, message: SpecModel) -> None:
        self.messages.append(message)


def build(
    tmp_path: Path,
    store: FakeEventStore,
    rec: StubRec,
    clock: FakeClock,
) -> tuple[ClipService, Captured]:
    published = Captured()
    service = ClipService(
        rec=rec,
        store=store,
        clock=clock,
        media_root=tmp_path,
        publish=published,
    )
    return service, published


def confirmed_store() -> FakeEventStore:
    """확정된 이벤트 하나가 들어 있는 저장소."""
    row = event("EV-1", EventStatus.ALERTED).model_copy(
        update={"confirmed_at": CONFIRMED, "detected_at": CONFIRMED}
    )
    return FakeEventStore([row])


def test_confirmation_marks_pending_and_grabs_keyframes_immediately(tmp_path: Path) -> None:
    """확정 시에는 **키프레임만** 즉시 뽑고 클립은 예약만 한다(기능명세서 §4.4)."""
    store, rec = confirmed_store(), StubRec()
    service, _ = build(tmp_path, store, rec, FakeClock(CONFIRMED))

    async def confirm_and_settle() -> None:
        await service.on_confirmed("EV-1", cam_id=1, confirmed_at=CONFIRMED)
        # 키프레임 추출은 **뒤로 넘겨진다**(ffmpeg 이 초 단위로 걸려 이벤트 처리 경로를
        # 막으면 안 된다). 그것이 끝났는지 보려면 여기서만 기다린다.
        await service.wait_idle()

    run(confirm_and_settle())

    assert store.clip_status["EV-1"] == "pending"
    assert len(rec.keyframes) == 2
    assert rec.clips == []  # ★ 아직 부르지 않았다
    assert (tmp_path / "keyframes" / "EV-1_0.jpg").is_file()


def test_the_job_waits_for_the_segment_to_close(tmp_path: Path) -> None:
    """★ `confirmed_at + post_roll + 세그먼트 길이 + margin` 전에는 실행되지 않는다.

    세그먼트 길이 항이 빠지면 사후 구간을 담은 파일이 **아직 열려 있는** 동안 잘라내게
    되고, 그 클립은 뒤가 비어 `partial` 이 된다(기능명세서 §4.4 · 실측 뒤 2.9초 없음).
    """
    store, rec = confirmed_store(), StubRec()
    clock = FakeClock(CONFIRMED)
    service, _ = build(tmp_path, store, rec, clock)
    run(service.on_confirmed("EV-1", cam_id=1, confirmed_at=CONFIRMED))

    # 사후 구간(10초) + 여유(2초)만 지났다. 세그먼트(10초)는 아직 닫히지 않았다.
    clock.set(CONFIRMED + timedelta(seconds=12))
    assert run(service.run_due()) == []
    assert rec.clips == []

    # 10 + 10 + 2 = 22초.
    clock.set(CONFIRMED + timedelta(seconds=22))
    assert run(service.run_due()) == ["EV-1"]
    assert len(rec.clips) == 1
    assert service.delay_s == 22.0


def test_the_segment_length_comes_from_rec_not_from_a_constant(tmp_path: Path) -> None:
    """REC 이 다른 길이를 보고하면 실행 시각이 따라 움직인다(기능명세서 §4.4).

    서버에 상수로 두면 REC 설정을 바꿨을 때 서버가 모른 채 잘못된 시각에 추출한다.
    """
    store, rec = confirmed_store(), StubRec()
    service, _ = build(tmp_path, store, rec, FakeClock(CONFIRMED))
    service.set_segment_seconds(4.0)
    assert service.delay_s == 16.0


def test_an_unknown_segment_length_defers_instead_of_guessing(tmp_path: Path) -> None:
    """REC 에 닿지 못해 세그먼트 길이를 모르면 **실행하지 않는다.**

    기본값으로 추측해 뽑으면 뒤가 잘린 클립이 `ready` 로 굳어 되돌릴 수 없다. 예약은
    DB 에 남아 있으므로 REC 이 살아나는 순간 다음 주기에 집힌다.
    """
    store = confirmed_store()
    rec = StubRec(available=False)
    clock = FakeClock(CONFIRMED + timedelta(seconds=60))
    service, _ = build(tmp_path, store, rec, clock)
    run(service.on_confirmed("EV-1", cam_id=1, confirmed_at=CONFIRMED))

    assert service.delay_s is None
    assert run(service.run_due()) == []
    assert store.clip_status["EV-1"] == "pending"

    rec.available = True
    assert run(service.run_due()) == ["EV-1"]
    assert service.segment_seconds == 10.0


def test_the_requested_window_is_pre_roll_to_post_roll_around_the_confirmation(
    tmp_path: Path,
) -> None:
    """§4.7 `POST /clips` — 확정 시각 기준 앞 10초 · 뒤 10초."""
    store, rec = confirmed_store(), StubRec()
    clock = FakeClock(CONFIRMED + timedelta(seconds=25))
    service, _ = build(tmp_path, store, rec, clock)
    run(service.on_confirmed("EV-1", cam_id=1, confirmed_at=CONFIRMED))
    run(service.run_due())

    request = rec.clips[0]
    assert request.from_ == CONFIRMED - timedelta(seconds=10)
    assert request.to == CONFIRMED + timedelta(seconds=10)
    assert request.event_id == "EV-1"


def test_a_ready_clip_is_stored_and_broadcast(tmp_path: Path) -> None:
    """받은 파일을 **서버 저장소에 영구 보관**하고 §5.2 로 `clip_url` 을 알린다.

    REC 의 7일 원본은 사라지므로, 옮겨 적지 않으면 증거가 보존 기간과 함께 없어진다.
    """
    store, rec = confirmed_store(), StubRec()
    clock = FakeClock(CONFIRMED + timedelta(seconds=25))
    service, published = build(tmp_path, store, rec, clock)
    run(service.on_confirmed("EV-1", cam_id=1, confirmed_at=CONFIRMED))
    run(service.run_due())

    assert (tmp_path / "clips" / "EV-1.mp4").read_bytes() == b"mp4."
    assert store.clip_status["EV-1"] == "ready"
    updates = [m for m in published.messages if isinstance(m, EventUpdatedMsg)]
    assert updates[-1].clip_status == "ready"
    assert updates[-1].clip_url == "/media/clips/EV-1.mp4"


def test_a_not_found_response_fails_the_job_and_records_the_reason(tmp_path: Path) -> None:
    """§4.7 — `partial` · `not_found` 는 REC 이 정상 동작한 결과다. 사유를 남긴다.

    `status` 만으로는 "보존 기간이 지났다"와 "그 시각에 녹화가 없었다"가 구분되지
    않는데 대응이 다르다.
    """
    store = confirmed_store()
    rec = StubRec(extract_status="not_found", reason="보존 기간 경과")
    clock = FakeClock(CONFIRMED + timedelta(seconds=25))
    service, published = build(tmp_path, store, rec, clock)
    run(service.on_confirmed("EV-1", cam_id=1, confirmed_at=CONFIRMED))
    run(service.run_due())

    assert store.clip_status["EV-1"] == "failed"
    # §6 `events.clip_error` 에 남는다. `note`(관리자 메모)는 건드리지 않는다 —
    # `[클립]` 접두사로 한 칸을 나눠 쓰던 임시 처리가 사라졌다.
    assert "보존 기간 경과" in store.clip_errors["EV-1"]
    assert "EV-1" not in store.notes
    assert not (tmp_path / "clips" / "EV-1.mp4").exists()
    assert [m for m in published.messages if isinstance(m, EventUpdatedMsg)][-1].clip_status == (
        "failed"
    )


def test_an_unreachable_rec_leaves_the_job_pending_for_the_next_round(tmp_path: Path) -> None:
    """REC 에 닿지 못한 것은 **잡의 실패가 아니다.**

    `failed` 로 굳히면 REC 이 살아나도 아무도 다시 부르지 않고, 그 이벤트는 영원히
    증거 없이 남는다.
    """
    store = confirmed_store()
    rec = StubRec(available=False)
    clock = FakeClock(CONFIRMED)
    service, _ = build(tmp_path, store, rec, clock)
    run(service.on_confirmed("EV-1", cam_id=1, confirmed_at=CONFIRMED))

    clock.set(CONFIRMED + timedelta(seconds=25))
    assert run(service.run_due()) == []
    assert store.clip_status["EV-1"] == "pending"

    # REC 이 살아났다. 같은 예약이 그대로 실행된다.
    rec.available = True
    assert run(service.run_due()) == ["EV-1"]
    assert store.clip_status["EV-1"] == "ready"


def test_a_pending_job_survives_a_restart(tmp_path: Path) -> None:
    """★ FN-REC-03 — **서버 재시작 시 `pending` 잡은 DB 에서 복구해 재실행한다.**

    새 `ClipService` 는 예약에 대해 아무것도 모른 채 만들어진다. 그런데도 잡이 도는
    것은 예약의 유일한 표현이 저장소의 `clip_status = pending` 이기 때문이다.
    """
    store, rec = confirmed_store(), StubRec()
    before, _ = build(tmp_path, store, rec, FakeClock(CONFIRMED))
    run(before.on_confirmed("EV-1", cam_id=1, confirmed_at=CONFIRMED))
    assert store.clip_status["EV-1"] == "pending"

    del before  # 서버가 죽었다. 남는 것은 저장소뿐이다.

    after, published = build(tmp_path, store, rec, FakeClock(CONFIRMED + timedelta(seconds=30)))
    assert run(after.run_due()) == ["EV-1"]

    assert store.clip_status["EV-1"] == "ready"
    assert (tmp_path / "clips" / "EV-1.mp4").is_file()
    assert [m for m in published.messages if isinstance(m, EventUpdatedMsg)][-1].clip_url


def test_a_finished_job_is_not_run_twice(tmp_path: Path) -> None:
    """`ready` 로 넘어간 잡은 다시 집히지 않는다. 같은 클립을 계속 다시 받으면 안 된다."""
    store, rec = confirmed_store(), StubRec()
    clock = FakeClock(CONFIRMED + timedelta(seconds=25))
    service, _ = build(tmp_path, store, rec, clock)
    run(service.on_confirmed("EV-1", cam_id=1, confirmed_at=CONFIRMED))

    run(service.run_due())
    run(service.run_due())

    assert len(rec.clips) == 1
