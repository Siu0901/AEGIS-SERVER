"""구간 추출과 키프레임 (API명세서 §4.7 `POST /clips` · `GET /keyframe`).

가장 조심해야 하는 부분은 **`actual_from` / `actual_to` 를 추정하지 않는 것**이다.

`-c copy` 리먹스는 키프레임에서만 자를 수 있다. 요청이 12.3초 지점에서 시작해도 실제
클립은 그 앞의 키프레임(예: 12.0초)에서 시작한다. 여기에 세그먼트 경계와 녹화 공백이
겹치면 요청 구간과 결과는 얼마든지 달라진다. 그래서 순서를 이렇게 잡는다.

1. 요청에 걸치는 **연속된** 세그먼트 구간을 고른다 (공백을 건너뛰지 않는다)
2. 그 안의 키프레임 목록을 실제로 읽어 절단점을 정한다
3. 잘라낸 다음 **결과 파일을 다시 재서** `actual_from` / `actual_to` 를 보고한다

3번이 핵심이다. 계산값이 아니라 실측값을 돌려줘야 서버가 이벤트 증거로 쓸 수 있다.
"""

from __future__ import annotations

import logging
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aegis_contracts import ClipResponse
from recorder import ffmpeg
from recorder.config import RecSettings
from recorder.segments import Segment, scan_segments, select_overlapping

__all__ = ["CLIP_URL_PREFIX", "ClipError", "clip_path", "extract_clip", "extract_keyframe"]

log = logging.getLogger("recorder.clips")

#: `download_url` 의 접두사. `RECORDER_BASE` 기준 상대 경로다(§4.7).
CLIP_URL_PREFIX = "/clips"

#: 세그먼트 사이가 이보다 벌어지면 녹화 공백으로 본다.
#: 리먹스 절단이 GOP(2초) 단위로 밀리므로 그보다 넉넉히 잡는다.
_GAP_TOLERANCE_S = 3.0

#: 구간을 "전부 확보했다"고 볼 여유. 프레임 간격(15fps → 67ms)보다 크게 잡는다.
_COVERAGE_TOLERANCE_S = 0.5

#: `event_id` 로 파일명을 만들기 때문에 경로 조작이 들어올 자리다.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class ClipError(RuntimeError):
    """요청 자체가 잘못됐다. 녹화가 없는 것(`not_found`)과 구분한다."""


def safe_event_id(event_id: str) -> str:
    """파일명으로 쓸 수 있는 값인지 확인한다.

    `..` 나 구분자가 섞이면 REC_MEDIA_ROOT 밖에 파일을 쓰게 된다. REC 은 서버가
    보내오는 값을 그대로 파일명으로 삼으므로 여기서 막지 않으면 막을 곳이 없다.
    """
    if not _SAFE_ID.match(event_id) or ".." in event_id:
        msg = f"event_id 로 파일명을 만들 수 없다: {event_id!r}"
        raise ClipError(msg)
    return event_id


def clips_dir(settings: RecSettings) -> Path:
    return settings.rec_media_root / "clips"


def clip_path(settings: RecSettings, event_id: str) -> Path:
    return clips_dir(settings) / f"{safe_event_id(event_id)}.mp4"


# ---------------------------------------------------------------------------
# 연속 구간 고르기
# ---------------------------------------------------------------------------


async def _measure(segments: list[Segment]) -> list[tuple[Segment, float]]:
    """세그먼트별 실제 길이를 잰다.

    아직 닫히지 않은 세그먼트는 mp4 의 moov 가 없어 ffprobe 가 실패한다. 그것을
    **조용히 0초로 치지 않고 목록에서 뺀다** — 길이를 모르는 파일을 이어붙이면
    타임라인이 어긋나 `actual_from` 이 거짓말이 된다. (기록 중 세그먼트를 읽을 수
    없다는 것이 FN-REC-03 의 `+ margin(2초)` 예약이 존재하는 이유다.)
    """
    measured: list[tuple[Segment, float]] = []
    for segment in segments:
        try:
            duration = await ffmpeg.probe_duration(segment.path)
        except ffmpeg.FfmpegError:
            log.debug("길이를 읽을 수 없는 세그먼트를 건너뛴다 (기록 중) — %s", segment.path)
            continue
        if duration > 0:
            measured.append((segment, duration))
    return measured


def _contiguous_runs(
    measured: list[tuple[Segment, float]],
) -> list[list[tuple[Segment, float]]]:
    """녹화가 끊기지 않고 이어진 묶음으로 자른다.

    공백을 무시하고 이어붙이면 concat 타임라인이 실제 시간보다 짧아져 절단 위치가
    통째로 밀린다. 공백 앞뒤는 다른 묶음으로 다룬다.

    **앞으로 벌어진 것만 공백으로 본다.** RTSP 연결 직후 몇 초 동안은 mp4 에 기록된
    길이가 파일명 간격보다 길게 나오는 일이 있다(관측: 시작 03-13-51 · 길이 14초인데
    다음 파일이 03-14-00). 그건 녹화가 끊긴 게 아니라 초기 타임스탬프가 아직 자리를
    못 잡은 것이라, 겹침을 공백으로 오인해 묶음을 쪼개면 멀쩡한 구간을 `partial` 로
    돌려주게 된다. 정상 구간에서는 파일명 간격과 길이가 정확히 10초로 일치한다.
    """
    runs: list[list[tuple[Segment, float]]] = []
    current: list[tuple[Segment, float]] = []
    for item in measured:
        if current:
            previous, previous_duration = current[-1]
            expected = previous.start_at + timedelta(seconds=previous_duration)
            behind = (item[0].start_at - expected).total_seconds()
            if behind > _GAP_TOLERANCE_S:
                runs.append(current)
                current = []
        current.append(item)
    if current:
        runs.append(current)
    return runs


def _run_bounds(run: list[tuple[Segment, float]]) -> tuple[datetime, datetime]:
    start = run[0][0].start_at
    end = run[-1][0].start_at + timedelta(seconds=run[-1][1])
    return start, end


def _best_run(
    runs: list[list[tuple[Segment, float]]],
    start: datetime,
    end: datetime,
) -> list[tuple[Segment, float]] | None:
    """요청 구간과 가장 많이 겹치는 묶음.

    공백으로 갈라진 경우 "가장 많이 담고 있는 쪽"을 준다. 양쪽을 억지로 이어붙이면
    존재하지 않는 시간이 클립 안에 생긴다.
    """
    best: list[tuple[Segment, float]] | None = None
    best_overlap = 0.0
    for run in runs:
        run_start, run_end = _run_bounds(run)
        overlap = (min(end, run_end) - max(start, run_start)).total_seconds()
        if overlap > best_overlap:
            best, best_overlap = run, overlap
    return best


# ---------------------------------------------------------------------------
# POST /clips
# ---------------------------------------------------------------------------


async def extract_clip(
    settings: RecSettings,
    *,
    cam_id: int,
    start: datetime,
    end: datetime,
    event_id: str,
) -> ClipResponse:
    """요청 구간을 잘라 파일로 만들고 §4.7 응답을 돌려준다."""
    if end <= start:
        msg = f"to 가 from 보다 뒤여야 한다 (from={start.isoformat()}, to={end.isoformat()})"
        raise ClipError(msg)
    destination = clip_path(settings, event_id)

    segments = scan_segments(settings.rec_media_root, cam_id)
    candidates = select_overlapping(
        segments,
        start,
        end,
        nominal_seconds=float(settings.rec_segment_seconds),
    )
    run = _best_run(_contiguous_runs(await _measure(candidates)), start, end)
    if run is None:
        # 보존 기간이 지났거나 그 시각에 녹화가 없었다.
        log.info("cam%d %s~%s 구간에 세그먼트가 없다", cam_id, start.isoformat(), end.isoformat())
        return ClipResponse(status="not_found")

    run_start, run_end = _run_bounds(run)
    # 이어붙인 타임라인의 0초 = run_start.
    want_from = max((start - run_start).total_seconds(), 0.0)
    want_to = min((end - run_start).total_seconds(), (run_end - run_start).total_seconds())

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aegis-rec-") as tmp:
        offset, duration = await _cut(Path(tmp), run, want_from, want_to, destination)

    actual_from = run_start + timedelta(seconds=offset)
    actual_to = actual_from + timedelta(seconds=duration)

    covered = actual_from <= start + timedelta(
        seconds=_COVERAGE_TOLERANCE_S
    ) and actual_to >= end - timedelta(seconds=_COVERAGE_TOLERANCE_S)
    return ClipResponse(
        status="ready" if covered else "partial",
        size_bytes=destination.stat().st_size,
        download_url=f"{CLIP_URL_PREFIX}/{destination.name}",
        actual_from=actual_from.astimezone(UTC),
        actual_to=actual_to.astimezone(UTC),
    )


async def _cut(
    workspace: Path,
    run: list[tuple[Segment, float]],
    want_from: float,
    want_to: float,
    destination: Path,
) -> tuple[float, float]:
    """세그먼트 묶음에서 `[want_from, want_to]` 를 잘라 `destination` 에 쓴다.

    실제로 잘린 (시작 오프셋, 길이)를 **측정해서** 돌려준다. 세 번에 나눠 도는 이유가
    각각 있다.

    1. **먼저 하나로 합친다.** concat demuxer 위에서 직접 `-ss` 로 seek 하면 엉뚱한
       위치로 간다 — `-ss 5` 를 줘도 1.0초로 되감기는 것을 확인했다(ffmpeg 8.1).
       단일 mp4 로 합쳐두면 seek 이 키프레임에 정확히 떨어진다.
    2. **`-copyts` 로 자른다.** 타임스탬프를 원래 타임라인 그대로 남겨야 결과 파일에서
       "어디서 어디까지 잘렸는지"를 읽어낼 수 있다. 여기서 얻은 값이 `actual_from` /
       `actual_to` 다. 계산으로 맞히려 하면 키프레임 위치를 틀리는 순간 거짓말이 된다.
    3. **0 기준으로 되돌린다.** 시작 pts 가 남아 있는 파일은 브라우저에서 재생 위치가
       어긋나 보인다. 이 단계는 화면용이고, 보고할 숫자는 2번에서 이미 확보했다.

    전부 `-c copy` 라 30초 남짓 구간에서는 각 단계가 수십 ms 다.
    """
    listing = workspace / "concat.txt"
    listing.write_text(_concat_listing(run), encoding="utf-8")
    joined = workspace / "joined.mp4"
    stamped = workspace / "stamped.mp4"
    ffmpeg_bin = ffmpeg.require_ffmpeg()
    common = ["-hide_banner", "-loglevel", "error", "-nostdin", "-y"]

    join_argv = [
        ffmpeg_bin, *common,
        "-f", "concat", "-safe", "0", "-i", listing.as_posix(),
        "-c", "copy",
        str(joined),
    ]  # fmt: skip
    await ffmpeg.run(join_argv)

    cut_argv = [
        ffmpeg_bin, *common,
        # `-ss` 는 `-i` 앞(입력 seek). 뒤에 두면 `-c copy` 에서 첫 키프레임 이전
        # 패킷이 남아 재생 시작이 깨진다.
        "-ss", f"{want_from:.3f}",
        "-i", str(joined),
        "-to", f"{want_to:.3f}",
        "-c", "copy",
        "-copyts",
        str(stamped),
    ]  # fmt: skip
    await ffmpeg.run(cut_argv)
    offset, duration = await ffmpeg.probe_span(stamped)

    normalize_argv = [
        ffmpeg_bin, *common,
        "-i", str(stamped),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        str(destination),
    ]  # fmt: skip
    await ffmpeg.run(normalize_argv)
    return offset, duration


def _concat_listing(run: list[tuple[Segment, float]]) -> str:
    """concat demuxer 용 목록.

    **경로를 반드시 절대경로로 적는다.** 목록 파일은 임시 디렉토리에 만들어지고
    concat demuxer 는 상대경로를 목록 파일 기준으로 풀기 때문에, 상대경로를 적으면
    `%TEMP%/aegis-rec-xxxx/media/rec/...` 를 찾다가 실패한다(실제로 겪었다).
    `RecSettings` 가 루트를 절대경로로 굳히지만 여기서도 한 번 더 보장한다 —
    이 함수만 보고도 규칙을 알 수 있어야 한다.
    """
    lines = ["ffconcat version 1.0"]
    for segment, _ in run:
        escaped = segment.path.resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# GET /keyframe
# ---------------------------------------------------------------------------


async def extract_keyframe(settings: RecSettings, *, cam_id: int, at: datetime) -> bytes:
    """단일 프레임 JPEG. 이벤트 확정 시 즉시 호출된다(§4.7).

    클립과 달리 사후 구간을 기다릴 필요가 없어 지연 없이 응답해야 한다. 그래서
    구간을 이어붙이지 않고 그 시각이 들어 있는 세그먼트 하나만 연다.
    """
    segments = scan_segments(settings.rec_media_root, cam_id)
    candidates = select_overlapping(
        segments,
        at,
        at + timedelta(milliseconds=1),
        nominal_seconds=float(settings.rec_segment_seconds),
    )
    measured = await _measure(candidates)
    if not measured:
        msg = f"cam{cam_id} {at.isoformat()} 시점의 세그먼트가 없다"
        raise ClipError(msg)

    segment, duration = measured[0]
    offset = min(max((at - segment.start_at).total_seconds(), 0.0), max(duration - 0.05, 0.0))
    argv = [
        ffmpeg.require_ffmpeg(),
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        # 입력 seek + 디코딩이므로 키프레임까지 되감았다가 정확한 프레임까지
        # 디코딩해 온다. 클립과 달리 여기서는 프레임 정확도를 얻을 수 있다.
        "-ss", f"{offset:.3f}",
        "-i", str(segment.path),
        "-frames:v", "1",
        "-q:v", "2",
        "-f", "mjpeg",
        "pipe:1",
    ]  # fmt: skip
    return await ffmpeg.run_bytes(argv, timeout_s=30.0)
