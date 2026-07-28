"""세그먼트 이름 규약과 인덱스 (API명세서 §4.7 경로 규약)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from recorder.segments import (
    ffmpeg_output_pattern,
    parse_segment_path,
    scan_segments,
    select_overlapping,
)

from .conftest import BASE_AT, SEGMENT_SECONDS, write_run, write_segment


def test_output_pattern_follows_path_convention(tmp_path: Path) -> None:
    pattern = ffmpeg_output_pattern(tmp_path, 1)
    assert pattern.endswith("1/%Y-%m-%d/%H-%M-%S.mp4")


def test_filename_is_parsed_as_utc(tmp_path: Path) -> None:
    path = tmp_path / "1" / "2026-08-14" / "05-37-10.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")

    segment = parse_segment_path(1, path)

    assert segment is not None
    assert segment.start_at == datetime(2026, 8, 14, 5, 37, 10, tzinfo=UTC)
    assert segment.start_at.tzinfo is not None


def test_non_conforming_files_are_not_segments(tmp_path: Path) -> None:
    """보존 정책이 이 판단으로 파일을 지운다. 아무거나 세그먼트로 보면 남의 파일을 지운다."""
    directory = tmp_path / "1" / "2026-08-14"
    directory.mkdir(parents=True)
    for name in ("메모.txt", "05-37-10.txt", "not-a-time.mp4", "2026-08-14.mp4"):
        candidate = directory / name
        candidate.write_bytes(b"x")
        assert parse_segment_path(1, candidate) is None


def test_scan_returns_segments_in_start_order(tmp_path: Path) -> None:
    write_run(tmp_path, 1, BASE_AT, 3)

    found = scan_segments(tmp_path, 1)

    assert [item.start_at for item in found] == [
        BASE_AT + timedelta(seconds=SEGMENT_SECONDS * index) for index in range(3)
    ]
    assert all(item.size_bytes > 0 for item in found)


def test_scan_spans_utc_midnight(tmp_path: Path) -> None:
    """UTC 자정을 넘기면 디렉토리가 갈린다. 인덱스는 그 경계를 몰라야 한다."""
    midnight = datetime(2026, 8, 14, 23, 59, 50, tzinfo=UTC)
    write_segment(tmp_path, 1, midnight, seconds=SEGMENT_SECONDS)
    write_segment(tmp_path, 1, midnight + timedelta(seconds=20), seconds=SEGMENT_SECONDS)

    found = scan_segments(tmp_path, 1)

    assert len(found) == 2
    assert found[0].start_at < found[1].start_at
    assert found[0].path.parent.name != found[1].path.parent.name


def test_select_overlapping_picks_only_covering_segments(tmp_path: Path) -> None:
    write_run(tmp_path, 1, BASE_AT, 4)  # 0~4, 4~8, 8~12, 12~16
    segments = scan_segments(tmp_path, 1)

    picked = select_overlapping(
        segments,
        BASE_AT + timedelta(seconds=5),
        BASE_AT + timedelta(seconds=9),
        nominal_seconds=float(SEGMENT_SECONDS),
    )

    assert [item.start_at for item in picked] == [
        BASE_AT + timedelta(seconds=4),
        BASE_AT + timedelta(seconds=8),
    ]


def test_select_overlapping_returns_empty_outside_range(tmp_path: Path) -> None:
    write_run(tmp_path, 1, BASE_AT, 2)
    segments = scan_segments(tmp_path, 1)

    picked = select_overlapping(
        segments,
        BASE_AT - timedelta(hours=1),
        BASE_AT - timedelta(minutes=59),
        nominal_seconds=float(SEGMENT_SECONDS),
    )

    assert picked == []
