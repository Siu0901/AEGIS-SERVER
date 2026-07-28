"""보존 정책 (FN-REC-02 7일 링버퍼 · FN-REC-05 용량 관리)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aegis_vision.clock import FakeClock
from recorder.retention import enforce, plan_deletions
from recorder.segments import Segment, scan_segments
from recorder.service import RecorderService

from .conftest import BASE_AT, SEGMENT_SECONDS, make_settings, write_run

_NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


def _fake(cam_id: int, minutes_ago: float, size_bytes: int) -> Segment:
    start = _NOW - timedelta(minutes=minutes_ago)
    return Segment(
        cam_id=cam_id,
        path=Path(f"/rec/{cam_id}/{start:%Y-%m-%d}/{start:%H-%M-%S}.mp4"),
        start_at=start,
        size_bytes=size_bytes,
    )


def test_only_expired_segments_are_planned() -> None:
    segments = sorted(
        [_fake(1, 60 * 24 * 8, 100), _fake(1, 60, 100), _fake(1, 30, 100)],
        key=lambda item: item.start_at,
    )

    plan = plan_deletions(
        segments,
        now=_NOW,
        retention_seconds=7 * 86400,
        max_bytes=10**9,
        keep_newest=0,
    )

    assert [item.start_at for item in plan.expired] == [segments[0].start_at]
    assert plan.over_quota == []


def test_quota_evicts_oldest_first() -> None:
    segments = [_fake(1, 50 - index, 100) for index in range(5)]
    segments.sort(key=lambda item: item.start_at)

    plan = plan_deletions(
        segments,
        now=_NOW,
        retention_seconds=7 * 86400,
        max_bytes=250,
        keep_newest=0,
    )

    assert plan.expired == []
    # 500바이트를 250 이하로 — 오래된 쪽 3개가 밀려난다.
    assert [item.start_at for item in plan.over_quota] == [
        segments[0].start_at,
        segments[1].start_at,
        segments[2].start_at,
    ]


def test_newest_segment_per_camera_is_protected() -> None:
    """기록 중인 파일을 지우면 ffmpeg 이 쓰고 있는 대상이 사라져 녹화가 깨진다."""
    segments = sorted(
        [_fake(1, 60 * 24 * 9, 100), _fake(2, 60 * 24 * 9, 100)],
        key=lambda item: item.start_at,
    )

    plan = plan_deletions(
        segments,
        now=_NOW,
        retention_seconds=7 * 86400,
        max_bytes=1,
        keep_newest=1,
    )

    assert plan.doomed == []


def test_nothing_is_deleted_when_under_quota() -> None:
    segments = [_fake(1, 10, 100), _fake(1, 5, 100)]
    segments.sort(key=lambda item: item.start_at)

    plan = plan_deletions(
        segments,
        now=_NOW,
        retention_seconds=7 * 86400,
        max_bytes=10**9,
        keep_newest=0,
    )

    assert plan.doomed == []


def test_enforce_deletes_files_and_prunes_empty_day_dirs(tmp_path: Path) -> None:
    root = tmp_path / "rec"
    old = datetime(2026, 8, 1, 3, 0, 0, tzinfo=UTC)
    write_run(root, 1, old, 2)
    write_run(root, 1, BASE_AT, 2)
    before = scan_segments(root, 1)
    assert len(before) == 4

    enforce(
        root,
        [1],
        now=BASE_AT + timedelta(seconds=SEGMENT_SECONDS * 2),
        retention_seconds=7 * 86400,
        max_bytes=10**9,
    )

    after = scan_segments(root, 1)
    assert [item.start_at for item in after] == [item.start_at for item in before[2:]]
    assert not (root / "1" / "2026-08-01").exists()
    assert (root / "1" / "2026-08-14").exists()


def test_today_directory_survives_even_when_empty(tmp_path: Path) -> None:
    """기동 직후 빈 오늘 디렉토리를 지우면 ffmpeg 이 즉사한다.

    `segment` muxer 는 디렉토리를 만들지 못해서 `capture.py` 가 미리 만들어 두는데,
    그 시점에는 파일이 하나도 없다. 스윕이 그걸 빈 디렉토리로 보고 치우면
    `Failed to open segment` 로 녹화가 시작되지 못한다. 실제로 겪은 회귀다.
    """
    root = tmp_path / "rec"
    today = root / "1" / BASE_AT.strftime("%Y-%m-%d")
    tomorrow = root / "1" / (BASE_AT + timedelta(days=1)).strftime("%Y-%m-%d")
    stale = root / "1" / "2026-08-01"
    for path in (today, tomorrow, stale):
        path.mkdir(parents=True)

    enforce(root, [1], now=BASE_AT, retention_seconds=7 * 86400, max_bytes=10**9)

    assert today.exists()
    assert tomorrow.exists()
    assert not stale.exists()  # 지난 날짜의 빈 디렉토리는 치운다


def test_service_sweep_applies_retention_window(tmp_path: Path) -> None:
    """`REC_RETENTION_DAYS` 를 짧게 두면 실제로 지워지는지 (완료 조건 5)."""
    settings = make_settings(
        tmp_path / "rec",
        rec_cam_ids=[1],
        # 3분. `rec_retention_days` 가 소수를 허용하는 이유가 바로 이 확인이다.
        rec_retention_days=180.0 / 86400.0,
    )
    write_run(settings.rec_media_root, 1, BASE_AT, 3)
    clock = FakeClock(start=BASE_AT)

    service = RecorderService(settings, clock)
    assert service.sweep().doomed == []  # 아직 3분이 지나지 않았다

    clock.advance(600)  # 10분 뒤
    plan = service.sweep()

    assert len(plan.expired) == 2  # 최신 1개는 기록 중일 수 있으므로 지키다
    assert len(scan_segments(settings.rec_media_root, 1)) == 1
