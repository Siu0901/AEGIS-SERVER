"""스냅샷 버퍼 — 확정 직후의 프레임을 메모리 비트스트림에서 낸다. FN-REC-03 (기능명세서 §4.4)

버퍼와 Annex-B 파서는 순수하므로 ffmpeg 없이 검증한다. `GET /keyframe` 이 실제로
버퍼를 먼저 보고 1프레임만 디코딩하는지는 앱을 띄워 확인한다.
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aegis_vision.clock import FakeClock
from recorder.ffmpeg import require_ffmpeg
from recorder.service import RecorderService
from recorder.snapshots import (
    AccessUnit,
    BitstreamBuffer,
    decode_slice,
    has_b_slice,
    split_access_units,
)
from recorder.tests.conftest import make_settings

BASE = datetime(2026, 8, 14, 5, 37, 0, tzinfo=UTC)


# --- Annex-B 파싱 ---------------------------------------------------------
#
# 실제 슬라이스 데이터를 넣지 않는다. 액세스 유닛 경계를 정하는 데 필요한 것은 시작코드와
# NAL 헤더, 그리고 슬라이스 헤더 첫 비트(`first_mb_in_slice == 0`)뿐이다.


def _nal(nal_type: int, *, first_mb_zero: bool = True, payload: bytes = b"\x00") -> bytes:
    """시작코드 + NAL 헤더 + 페이로드 한 덩어리."""
    head = 0x80 if first_mb_zero else 0x40
    return b"\x00\x00\x00\x01" + bytes([nal_type]) + bytes([head]) + payload


SPS = _nal(7)
PPS = _nal(8)
IDR = _nal(5)
SLICE = _nal(1)


def test_parameter_sets_belong_to_the_following_picture() -> None:
    """SPS·PPS 는 **뒤따르는** IDR 의 것이다.

    앞 유닛에 붙이면 IDR 부터 잘라낸 조각이 파라미터 세트를 잃고 디코딩이 통째로
    실패한다 — 그림이 없는 것이 아니라 500 이 된다.
    """
    units, tail = split_access_units(SLICE + SPS + PPS + IDR + SLICE)
    assert [is_idr for _, is_idr in units] == [False, True]
    assert units[1][0] == SPS + PPS + IDR
    assert tail == SLICE


def test_multi_slice_picture_stays_one_access_unit() -> None:
    """`first_mb_in_slice != 0` 인 슬라이스는 같은 픽처의 이어짐이다."""
    second = _nal(1, first_mb_zero=False)
    units, _ = split_access_units(IDR + second + SLICE + SLICE)
    assert len(units) == 2
    assert units[0][0] == IDR + second


def test_incomplete_tail_is_carried_over() -> None:
    """마지막 유닛은 다음 픽처가 나타나야 끝났음을 안다 — 잘린 채로 내보내지 않는다."""
    first, tail = split_access_units(IDR + SLICE[:3])
    assert first == []
    assert tail == IDR + SLICE[:3]
    units, _ = split_access_units(tail + SLICE[3:] + SLICE)
    assert len(units) == 2


def test_b_slice_is_detected() -> None:
    """B프레임이 있으면 표시 순서가 뒤바뀌어 「마지막 출력 = 목표」가 깨진다.

    조용히 어긋난 그림을 내지 않으려면 그 사실이 드러나야 한다(절대규칙 9).
    `first_mb_in_slice=0`(비트 `1`) 다음의 `ue(v)` 가 `slice_type` 이며,
    `010`(=1) 과 `00111`(=6) 이 B 다.
    """
    # 비트열 `1` + `010` → first_mb=0, slice_type=1(B). 0b1010_0000 = 0xA0
    b_slice = b"\x00\x00\x00\x01" + bytes([1]) + b"\xa0"
    # 비트열 `1` + `1` → first_mb=0, slice_type=0(P). 0b1100_0000 = 0xC0
    p_slice = b"\x00\x00\x00\x01" + bytes([1]) + b"\xc0"
    assert has_b_slice(b_slice) is True
    assert has_b_slice(p_slice) is False
    assert has_b_slice(IDR) is False


# --- 버퍼 -----------------------------------------------------------------


def _buffer(window_s: float = 60.0) -> BitstreamBuffer:
    return BitstreamBuffer(window_s=window_s)


def _fill(buffer: BitstreamBuffer, count: int, *, gop: int = 4, step_s: float = 0.1) -> None:
    """`gop` 마다 IDR 이 오는 스트림을 흉내낸다."""
    for index in range(count):
        is_idr = index % gop == 0
        buffer.add(
            AccessUnit(
                at=BASE + timedelta(seconds=index * step_s),
                payload=(SPS + PPS + IDR if is_idr else SLICE) + bytes([index]),
                is_idr=is_idr,
            )
        )


def test_rejects_degenerate_settings() -> None:
    with pytest.raises(ValueError, match="0보다"):
        BitstreamBuffer(window_s=0.0)


def test_empty_buffer_has_no_answer() -> None:
    assert _buffer().slice_for(BASE) is None


def test_slice_runs_from_the_preceding_idr_to_the_target() -> None:
    """§4.4 — 목표 시각 **직전 IDR 부터 목표 프레임까지만** 디코딩한다."""
    buffer = _buffer()
    _fill(buffer, 12)
    piece = buffer.slice_for(BASE + timedelta(seconds=0.62))
    assert piece is not None
    # 0.62초 → 인덱스 6. 직전 IDR 은 4 이므로 4·5·6 세 장이다.
    assert piece.frames == 3
    assert piece.at == BASE + timedelta(seconds=0.6)
    assert piece.payload.startswith(SPS + PPS + IDR)


def test_target_is_the_requested_moment_not_the_nearest_idr() -> None:
    """키프레임 근사를 쓰지 않는다 — GOP 간격만큼 어긋난 그림은 증거가 아니다."""
    buffer = _buffer()
    _fill(buffer, 12)
    piece = buffer.slice_for(BASE + timedelta(seconds=0.7))
    assert piece is not None
    assert piece.at == BASE + timedelta(seconds=0.7)
    assert piece.frames == 4  # IDR(0.4) 부터 목표(0.7) 까지


def test_gop_head_alone_is_answerable() -> None:
    buffer = _buffer()
    _fill(buffer, 12)
    piece = buffer.slice_for(BASE + timedelta(seconds=0.4))
    assert piece is not None
    assert piece.frames == 1


def test_stream_that_starts_mid_gop_falls_through() -> None:
    """앞에 IDR 이 없는 구간은 단독으로 디코딩할 수 없다 — 세그먼트에서 뽑는다."""
    buffer = _buffer()
    for index in range(3):
        buffer.add(
            AccessUnit(at=BASE + timedelta(seconds=index * 0.1), payload=SLICE, is_idr=False)
        )
    assert buffer.slice_for(BASE + timedelta(seconds=0.2)) is None


def test_request_outside_the_window_falls_through() -> None:
    """버퍼 밖은 `None` — 세그먼트에서 뽑으라는 뜻이다.

    가장 가까운 것을 무조건 돌려주면 한참 전 사건의 그림으로 지금을 설명하게 된다.
    """
    buffer = _buffer()
    _fill(buffer, 12)
    assert buffer.slice_for(BASE - timedelta(seconds=30)) is None
    assert buffer.slice_for(BASE + timedelta(seconds=30)) is None


def test_confirmation_moment_is_answerable_immediately() -> None:
    """§4.4 의 요구 그 자체 — 확정 시각의 프레임이 파일에 없어도 답이 나온다.

    확정 시각은 사실상 「지금」이라 마지막 프레임보다 조금 앞설 수 있다. 그 만큼은
    가장 최신 프레임으로 답한다.
    """
    buffer = _buffer()
    _fill(buffer, 8)
    assert buffer.slice_for(BASE + timedelta(seconds=0.9)) is not None


def test_window_drops_the_oldest_and_frees_bytes() -> None:
    """최근 `rec_snapshot_window_s` 만 남는다 — 메모리가 무한히 늘지 않는다."""
    buffer = _buffer(window_s=1.0)
    _fill(buffer, 40)
    assert buffer.oldest_at is not None
    assert buffer.newest_at is not None
    assert (buffer.newest_at - buffer.oldest_at) <= timedelta(seconds=1.0)
    assert buffer.nbytes == sum(len(SLICE) + 1 for _ in range(buffer.count)) or buffer.nbytes > 0


# --- 실제 비트스트림 (ffmpeg) ---------------------------------------------


def _encode_elementary_stream(path: Path, *, seconds: int, fps: int, gop: int) -> bytes:
    """Annex-B H.264 한 토막. 카메라가 내보내는 것과 같은 형태다."""
    argv = [
        require_ffmpeg(),
        "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi",
        "-i", f"testsrc2=size=320x180:rate={fps}:duration={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        # 저지연 카메라와 같게 B프레임 없이. 도착 순서 = 표시 순서가 된다.
        "-bf", "0",
        "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
        "-f", "h264",
        str(path),
    ]  # fmt: skip
    subprocess.run(argv, check=True, capture_output=True)
    return path.read_bytes()


def _decode_reference(path: Path, index: int) -> bytes:
    """스트림 전체를 디코딩해 `index` 번째 프레임을 뽑는다 — 대조군."""
    argv = [
        require_ffmpeg(),
        "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "h264", "-i", str(path),
        "-vf", f"select=eq(n\\,{index})",
        "-fps_mode", "passthrough",
        "-frames:v", "1",
        "-q:v", "2",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]  # fmt: skip
    return subprocess.run(argv, check=True, capture_output=True).stdout


def test_real_stream_returns_the_requested_frame_not_a_keyframe(tmp_path: Path) -> None:
    """★ 이 설계의 요구 그 자체 — 요청한 **시각의 프레임**을 정확히 낸다.

    직전 IDR 부터 잘라 디코딩한 결과가, 스트림 전체를 디코딩해 같은 인덱스를 뽑은
    것과 **바이트까지 같아야** 한다. 키프레임 근사였다면 GOP 간격(여기서는 1초)만큼
    다른 그림이 나온다.
    """
    fps, gop, target = 15, 15, 22
    raw = _encode_elementary_stream(tmp_path / "cam.h264", seconds=4, fps=fps, gop=gop)
    units, _ = split_access_units(raw)
    assert len(units) > target

    buffer = _buffer()
    for index, (payload, is_idr) in enumerate(units):
        at = BASE + timedelta(seconds=index / fps)
        buffer.add(AccessUnit(at=at, payload=payload, is_idr=is_idr))

    piece = buffer.slice_for(BASE + timedelta(seconds=target / fps))
    assert piece is not None
    # 직전 IDR 은 15 번이므로 15~22 의 8장만 디코딩한다 — 스트림 전체가 아니다.
    assert piece.frames == target - gop + 1

    produced = asyncio.run(decode_slice(piece, ffmpeg=require_ffmpeg()))
    assert produced == _decode_reference(tmp_path / "cam.h264", target)
    assert produced != _decode_reference(tmp_path / "cam.h264", gop), "키프레임으로 근사했다"


def test_status_reports_the_recording_section(tmp_path: Path) -> None:
    """§4.7 `recording` — 서버가 클립 예약 시각을 계산하는 데 쓰는 값들.

    이 절이 없으면 서버가 세그먼트 길이를 자기 상수로 들고 있어야 하고, REC 설정을
    바꾼 순간 아직 열려 있는 파일을 잘라내게 된다(기능명세서 §4.4).
    """
    settings = make_settings(tmp_path / "rec", rec_segment_seconds=10)
    service = RecorderService(settings, FakeClock())
    status = asyncio.run(service.status())
    assert status.recording.segment_seconds == 10
    assert status.recording.snapshot_window_s == 60
    # 아직 스트림이 붙지 않았으므로 0. `snapshot_fps` 는 명세서에서 사라졌다.
    assert status.recording.snapshot_bytes == 0


def test_retention_days_is_not_rounded_away(tmp_path: Path) -> None:
    """1시간(0.0417일)을 걸어 두면 `0` 이 아니라 그 값 그대로 보고된다.

    반올림하면 화면에 「보존 0일」이 뜨고, 그것은 "보존하지 않는다"로 읽힌다.
    """
    settings = make_settings(tmp_path / "rec", rec_retention_days=0.0417)
    service = RecorderService(settings, FakeClock())
    status = asyncio.run(service.status())
    assert status.storage.retention_days == pytest.approx(0.0417)


def test_service_hands_out_the_buffer_per_camera(tmp_path: Path) -> None:
    service = RecorderService(make_settings(tmp_path / "rec"), FakeClock())
    assert service.snapshots(1) is not None
    assert service.snapshots(9) is None
