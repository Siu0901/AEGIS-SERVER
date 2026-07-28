"""세그먼트 파일 이름 규약과 인덱스.

경로 규약 (API명세서 §4.7):

    {REC_MEDIA_ROOT}/{cam_id}/{YYYY-MM-DD}/{HH-MM-SS}.mp4

**날짜·시각은 UTC 다.** 저장은 UTC, 표시만 KST 라는 §1.2 규약을 파일명에도 그대로
적용한다. ffmpeg 의 `-strftime` 은 로컬 시각을 쓰므로 자식 프로세스 환경에 `TZ=UTC0`
를 심어 UTC 로 찍게 만든다(`capture.py`). 이 파일의 파서는 그 전제 위에 있다.

세그먼트 길이는 명목 10초지만 실제로는 그렇지 않다. `-c copy` 리먹스는 키프레임에서만
자를 수 있어 GOP(2초) 단위로 밀린다. 그래서 **구간이 요청과 얼마나 다른지를 계산할 때
명목값을 믿지 않고** 이웃 세그먼트의 시작 시각이나 ffprobe 실측을 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

__all__ = [
    "SEGMENT_SUFFIX",
    "Segment",
    "day_dir",
    "ffmpeg_output_pattern",
    "parse_segment_path",
    "scan_segments",
    "select_overlapping",
]

SEGMENT_SUFFIX = ".mp4"

_DAY_FORMAT = "%Y-%m-%d"
_TIME_FORMAT = "%H-%M-%S"

#: ffmpeg `segment` muxer 에 넘길 strftime 패턴. 위 규약과 반드시 같은 모양이어야 한다.
_FFMPEG_PATTERN = f"{_DAY_FORMAT}/{_TIME_FORMAT}{SEGMENT_SUFFIX}"


@dataclass(frozen=True, slots=True)
class Segment:
    """닫혔거나 기록 중인 세그먼트 파일 하나."""

    cam_id: int
    path: Path
    start_at: datetime
    """파일명에서 읽은 시작 시각 (UTC aware)."""
    size_bytes: int

    def end_at(self, duration_s: float) -> datetime:
        return self.start_at + timedelta(seconds=duration_s)


def cam_dir(root: Path, cam_id: int) -> Path:
    return root / str(cam_id)


def day_dir(root: Path, cam_id: int, moment: datetime) -> Path:
    """`moment` 가 속한 날짜 디렉토리. `moment` 는 UTC aware 여야 한다."""
    return cam_dir(root, cam_id) / moment.astimezone(UTC).strftime(_DAY_FORMAT)


def ffmpeg_output_pattern(root: Path, cam_id: int) -> str:
    """ffmpeg `-strftime 1` 이 확장할 출력 패턴.

    ffmpeg 8.1 의 `segment` muxer 에는 `strftime_mkdir` 옵션이 없다(hls 에만 있다).
    날짜 디렉토리는 `capture.py` 가 미리 만들어 둔다 — 없으면 ffmpeg 이
    `Failed to open segment` 로 죽고 그 카메라의 녹화가 통째로 멈춘다.
    """
    return (cam_dir(root, cam_id) / _FFMPEG_PATTERN).as_posix()


def parse_segment_path(cam_id: int, path: Path) -> Segment | None:
    """`.../{YYYY-MM-DD}/{HH-MM-SS}.mp4` 를 `Segment` 로 읽는다.

    규약에 맞지 않는 파일은 `None` 을 준다 — 사람이 넣어둔 파일이나 임시 파일을
    세그먼트로 오인해 지우지 않기 위해서다(FN-REC-05 는 파일을 삭제한다).
    """
    if path.suffix != SEGMENT_SUFFIX:
        return None
    # 날짜와 시각이 다른 경로 조각에 나뉘어 있어 한 번에 파싱할 수 없다.
    # `%z` 를 붙일 자리가 없으므로 UTC 를 명시적으로 얹는다 — 파일명은 UTC 다.
    try:
        start_at = datetime.strptime(
            f"{path.parent.name} {path.stem} +0000", f"{_DAY_FORMAT} {_TIME_FORMAT} %z"
        )
    except ValueError:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    return Segment(cam_id=cam_id, path=path, start_at=start_at, size_bytes=size)


def scan_segments(root: Path, cam_id: int) -> list[Segment]:
    """카메라 하나의 세그먼트를 **시작 시각 오름차순**으로 모은다."""
    base = cam_dir(root, cam_id)
    if not base.is_dir():
        return []
    found: list[Segment] = []
    for day in sorted(base.iterdir()):
        if not day.is_dir():
            continue
        for candidate in sorted(day.iterdir()):
            segment = parse_segment_path(cam_id, candidate)
            if segment is not None:
                found.append(segment)
    found.sort(key=lambda item: item.start_at)
    return found


def select_overlapping(
    segments: list[Segment],
    start: datetime,
    end: datetime,
    *,
    nominal_seconds: float,
) -> list[Segment]:
    """`[start, end)` 에 걸치는 세그먼트를 순서대로 고른다.

    각 세그먼트의 끝은 **다음 세그먼트의 시작**으로 본다. 녹화는 끊김 없이 이어지므로
    그 편이 명목 길이보다 정확하다. 마지막(기록 중일 수 있는) 세그먼트만 명목값을 쓴다.

    끝을 실측(ffprobe)하지 않는 이유: 후보를 고르는 단계라 대략적인 경계로 충분하고,
    최종 `actual_from` / `actual_to` 는 만들어진 클립을 다시 재서 보고하기 때문이다.
    """
    picked: list[Segment] = []
    for index, segment in enumerate(segments):
        if index + 1 < len(segments):
            segment_end = segments[index + 1].start_at
        else:
            segment_end = segment.start_at + timedelta(seconds=nominal_seconds)
        if segment_end > start and segment.start_at < end:
            picked.append(segment)
    return picked
