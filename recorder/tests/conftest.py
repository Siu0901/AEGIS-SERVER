"""REC 테스트 공용 도구 — 가짜 세그먼트를 진짜 mp4 로 만들어 둔다.

세그먼트를 빈 파일로 흉내 내면 `POST /clips` 검증이 통째로 무의미해진다. 이 기능의
어려운 부분은 파일 개수를 세는 것이 아니라 **키프레임 경계에서 잘린 실제 구간을
정확히 보고하는 것**이라, ffprobe 가 읽을 수 있는 진짜 영상이어야 한다.

ffmpeg 이 없으면 건너뛰지 않고 실패한다. REC 은 ffmpeg 없이는 아무것도 하지 못하므로
"도구가 없어 통과"는 통과가 아니다(CLAUDE.md 절대규칙 9).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from recorder.config import RecSettings
from recorder.ffmpeg import require_ffmpeg
from recorder.segments import day_dir

#: 테스트 세그먼트 격자. 실제(10초)보다 짧게 잡아 테스트가 빨리 끝나게 한다.
SEGMENT_SECONDS = 4

#: 키프레임 간격 1초. 절단 정밀도가 이 값에 걸리므로 검증에서 여유를 이만큼 잡는다.
TEST_GOP = 15

#: 결정적인 기준 시각. `FakeClock` 의 기본값과 같은 날로 맞춰 둔다.
BASE_AT = datetime(2026, 8, 14, 5, 30, 0, tzinfo=UTC)


def make_settings(root: Path, **overrides: object) -> RecSettings:
    """테스트용 설정. **개발자의 `.env` 를 읽지 않는다.**

    `.env` 를 그대로 두면 각자의 로컬 값(보존 기간을 잠깐 줄여둔 상태 등)에 따라
    테스트 결과가 달라진다. 그건 테스트가 아니라 그날의 환경을 재는 것이다.
    """
    fields: dict[str, object] = {
        "rec_media_root": root,
        "rec_cam_ids": [1, 2],
        "rec_segment_seconds": SEGMENT_SECONDS,
        "rec_retention_days": 7.0,
        "rec_max_disk_gb": 1.0,
        **overrides,
    }
    return RecSettings(_env_file=None, **fields)  # type: ignore[arg-type]


@pytest.fixture
def rec_settings(tmp_path: Path) -> RecSettings:
    return make_settings(tmp_path / "rec")


def write_segment(root: Path, cam_id: int, start_at: datetime, *, seconds: int) -> Path:
    """`{root}/{cam_id}/{YYYY-MM-DD}/{HH-MM-SS}.mp4` 에 진짜 영상을 만든다."""
    directory = day_dir(root, cam_id, start_at)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{start_at.astimezone(UTC).strftime('%H-%M-%S')}.mp4"
    argv = [
        require_ffmpeg(),
        "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi",
        "-i", f"testsrc2=size=320x180:rate=15:duration={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-g", str(TEST_GOP), "-keyint_min", str(TEST_GOP), "-sc_threshold", "0",
        str(path),
    ]  # fmt: skip
    subprocess.run(argv, check=True, capture_output=True)
    return path


def write_run(root: Path, cam_id: int, start_at: datetime, count: int) -> list[Path]:
    """끊김 없이 이어지는 세그먼트 `count` 개."""
    return [
        write_segment(
            root,
            cam_id,
            start_at + timedelta(seconds=SEGMENT_SECONDS * index),
            seconds=SEGMENT_SECONDS,
        )
        for index in range(count)
    ]
