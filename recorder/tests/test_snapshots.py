"""스냅샷 버퍼 — 확정 직후의 프레임을 메모리에서 낸다. FN-REC-03 (기능명세서 §4.4)

버퍼는 순수 자료구조라 ffmpeg 없이 검증한다. `GET /keyframe` 이 실제로 버퍼를 먼저
보는지는 앱을 띄워 확인한다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aegis_vision.clock import FakeClock
from recorder.service import RecorderService
from recorder.snapshots import SnapshotBuffer
from recorder.tests.conftest import make_settings

BASE = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)


def _buffer(window_s: float = 60.0, fps: float = 1.0) -> SnapshotBuffer:
    return SnapshotBuffer(window_s=window_s, fps=fps)


def test_rejects_degenerate_settings() -> None:
    with pytest.raises(ValueError, match="0보다"):
        SnapshotBuffer(window_s=0.0, fps=1.0)
    with pytest.raises(ValueError, match="0보다"):
        SnapshotBuffer(window_s=60.0, fps=0.0)


def test_empty_buffer_has_no_answer() -> None:
    assert _buffer().nearest(BASE) is None


def test_returns_the_closest_frame() -> None:
    buffer = _buffer()
    for index in range(5):
        buffer.add(BASE + timedelta(seconds=index), f"jpeg{index}".encode())
    hit = buffer.nearest(BASE + timedelta(seconds=2, milliseconds=300))
    assert hit is not None
    assert hit[1] == b"jpeg2"


def test_request_outside_the_sample_interval_falls_through() -> None:
    """샘플 간격보다 멀면 `None` — 세그먼트에서 뽑으라는 뜻이다.

    가장 가까운 것을 무조건 돌려주면 30초 전 사건의 그림으로 지금을 설명하게 된다.
    """
    buffer = _buffer()
    buffer.add(BASE, b"jpeg")
    assert buffer.nearest(BASE + timedelta(seconds=0.9)) is not None
    assert buffer.nearest(BASE + timedelta(seconds=1.1)) is None
    assert buffer.nearest(BASE - timedelta(seconds=30)) is None


def test_window_drops_the_oldest() -> None:
    """최근 `rec_snapshot_window_s` 만 남는다 — 메모리가 무한히 늘지 않는다."""
    buffer = _buffer(window_s=5.0)
    for index in range(20):
        buffer.add(BASE + timedelta(seconds=index), b"x")
    assert buffer.count == 6  # 5초 창 + 경계 한 장
    assert buffer.oldest_at == BASE + timedelta(seconds=14)
    assert buffer.newest_at == BASE + timedelta(seconds=19)


def test_confirmation_moment_is_answerable_immediately() -> None:
    """§4.4 의 요구 그 자체 — 확정 시각의 프레임이 파일에 없어도 답이 나온다.

    스냅샷이 0.4초 전이면 §4.4 가 허용한 0.5초 안이다.
    """
    buffer = _buffer()
    buffer.add(BASE - timedelta(seconds=0.4), b"jpeg")
    assert buffer.nearest(BASE) is not None


def test_status_reports_the_recording_section(tmp_path: Path) -> None:
    """§4.7 `recording` — 서버가 클립 예약 시각을 계산하는 데 쓰는 값들.

    이 절이 없으면 서버가 세그먼트 길이를 자기 상수로 들고 있어야 하고, REC 설정을
    바꾼 순간 아직 열려 있는 파일을 잘라내게 된다(기능명세서 §4.4).
    """
    settings = make_settings(tmp_path / "rec", rec_segment_seconds=10)
    service = RecorderService(settings, FakeClock())
    status = asyncio.run(service.status())
    assert status.recording.segment_seconds == 10
    assert status.recording.snapshot_fps == 1
    assert status.recording.snapshot_window_s == 60


def test_service_hands_out_the_buffer_per_camera(tmp_path: Path) -> None:
    service = RecorderService(make_settings(tmp_path / "rec"), FakeClock())
    assert service.snapshots(1) is not None
    assert service.snapshots(9) is None
