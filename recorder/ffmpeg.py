"""ffmpeg · ffprobe 호출 래퍼.

REC 이 하는 일은 전부 ffmpeg 을 통한다. **녹화는 디코딩 없는 리먹스(`-c copy`)여야
한다** — 디코딩하면 GPU 추론 예산을 갉아먹고, 그것이 녹화를 엣지 SSD 로 분리한 이유
자체를 무너뜨린다(기능명세서 §4.4).

도구를 찾지 못하면 조용히 건너뛰지 않고 오류를 낸다(CLAUDE.md 절대규칙 9).
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

__all__ = [
    "FfmpegError",
    "probe_duration",
    "probe_span",
    "require_ffmpeg",
    "require_ffprobe",
    "run",
    "run_bytes",
]


class FfmpegError(RuntimeError):
    """ffmpeg/ffprobe 를 실행할 수 없거나 0이 아닌 코드로 끝났다."""


def _require(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        msg = (
            f"{name} 을 찾을 수 없다. REC 은 {name} 없이 동작하지 않는다.\n"
            f"  설치해 PATH 에 넣어라 (Windows: winget install Gyan.FFmpeg)."
        )
        raise FfmpegError(msg)
    return found


def require_ffmpeg() -> str:
    return _require("ffmpeg")


def require_ffprobe() -> str:
    return _require("ffprobe")


async def run(argv: list[str], *, timeout_s: float = 120.0) -> str:
    """`run_bytes` 의 텍스트판."""
    return (await run_bytes(argv, timeout_s=timeout_s)).decode("utf-8", "replace")


async def run_bytes(argv: list[str], *, timeout_s: float = 120.0) -> bytes:
    """자식 프로세스를 끝까지 돌리고 stdout 을 돌려준다.

    실패하면 stderr 를 그대로 붙여 올린다. ffmpeg 의 실패 원인은 대부분 stderr 마지막
    몇 줄에만 있고, 그것을 버리면 무엇이 잘못됐는지 알 수 없다.
    """
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except TimeoutError:
        process.kill()
        await process.wait()
        msg = f"{Path(argv[0]).name} 가 {timeout_s}초 안에 끝나지 않았다"
        raise FfmpegError(msg) from None
    if process.returncode != 0:
        detail = stderr.decode("utf-8", "replace").strip().splitlines()[-8:]
        msg = f"{Path(argv[0]).name} 종료코드 {process.returncode}\n" + "\n".join(detail)
        raise FfmpegError(msg)
    return stdout


async def probe_duration(path: Path) -> float:
    """미디어 파일의 실제 길이(초).

    세그먼트 길이를 명목 10초로 가정하지 않기 위한 함수다. `-c copy` 는 키프레임에서만
    자를 수 있어 실제 길이가 명목값과 다르다.
    """
    argv = [
        require_ffprobe(),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]  # fmt: skip
    text = (await run(argv, timeout_s=30.0)).strip()
    try:
        return float(text)
    except ValueError:
        msg = f"길이를 읽지 못했다: {path} (ffprobe 출력 {text!r})"
        raise FfmpegError(msg) from None


async def probe_span(path: Path) -> tuple[float, float]:
    """파일의 (시작 pts, 길이) 초.

    `-copyts` 로 잘라낸 파일에서 이 둘을 읽으면 **실제로 어디서 어디까지 잘렸는지**를
    계산이 아니라 측정으로 얻는다. `POST /clips` 의 `actual_from` / `actual_to` 가
    여기에 걸려 있다 — 추정값을 돌려주면 서버가 엉뚱한 구간을 증거로 기록한다.
    """
    argv = [
        require_ffprobe(),
        "-v", "error",
        "-show_entries", "format=start_time,duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]  # fmt: skip
    lines = (await run(argv, timeout_s=30.0)).split()
    if len(lines) < 2:
        msg = f"시작 시각과 길이를 읽지 못했다: {path} (ffprobe 출력 {lines!r})"
        raise FfmpegError(msg)
    try:
        return float(lines[0]), float(lines[1])
    except ValueError:
        msg = f"시작 시각과 길이를 읽지 못했다: {path} (ffprobe 출력 {lines!r})"
        raise FfmpegError(msg) from None
