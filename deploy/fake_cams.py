#!/usr/bin/env python
"""가짜 IP 카메라 2대를 mediamtx 로 무한 루프 송출한다.

    uv run tasks.py cams                              # testsrc2 테스트 패턴
    uv run tasks.py cams --source a.mp4               # 카메라 1·2 모두 a.mp4
    uv run tasks.py cams --source a.mp4 --source b.mp4  # 카메라별 다른 영상
    uv run tasks.py cams --cams 2                     # 카메라 2만 (한 대만 끊어보려면)
    uv run tasks.py cams-stop                         # 전부 종료

**경로 하나당 ffmpeg 프로세스 하나**, 총 4개를 띄운다.

    cam1/main  1920x1080  H.264  15fps  2.5Mbps   서버 — 라이브 · REC 녹화 원본
    cam1/sub     640x360  H.264  15fps   600kbps  엣지 — 추론
    cam2/main  1920x1080  H.264  15fps  2.5Mbps
    cam2/sub     640x360  H.264  15fps   600kbps

메인 2.5Mbps 는 임의로 고를 수 있는 값이 아니다. 기능명세서 §4.4 의 7일 378GB 용량
산정과 API명세서 §4.7 녹화 규격이 이 숫자에 걸려 있다. 바꾸면 REC 보존 정책 계산이
전부 어긋난다.

**서브는 반드시 16:9다.** 엣지는 서브에서 정규화 좌표를 산출하고 대시보드는 그 좌표를
메인 위에 그린다(API명세서 §1.2). 640x640 같은 정사각으로 두면 좌표가 한쪽 축으로 눌린다.
`require_16_9` 가 기동 전에 막는다.

**타임코드를 화면에 태우는 것은 선택이 아니다.**
영상 지연을 재는 유일한 수단이고, M2 오버레이 시간 정합(±100ms)의 기준선이 된다.
폰트를 찾지 못하면 타임코드 없이 송출하지 않고 오류로 중단한다 — 기준선이 조용히
사라지는 것이 이 도구에서 가장 나쁜 실패다(CLAUDE.md 절대규칙 9).

경로별로 프로세스를 나눈 대가: 파일을 소스로 쓰면 main 과 sub 가 각자 파일을 읽으므로
프레임이 완전히 같지는 않다(기동 시차 수백 ms 수준). 그래서 **두 스트림 모두에 같은
방식으로 벽시계 타임코드를 태운다** — 어긋남을 가정하지 않고 화면에서 읽을 수 있게.

원래 `fake_cams.sh` 였다. 개발 환경이 Windows + PowerShell 이라 bash 를 전제할 수
없으므로 파이썬으로 옮겼다. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from types import FrameType
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
PIDFILE_DIR = ROOT / "media" / "run"
PIDFILE_GLOB = "fake_cams*.json"


def pidfile_for(cam_ids: Sequence[int]) -> Path:
    """송출 중인 카메라 조합마다 다른 PID 파일을 쓴다.

    `--cams 1` 과 `--cams 2` 를 따로 띄워야 **한 대만 끊는 상황**을 만들 수 있고
    (서버의 카메라별 상태 전이를 확인하려면 그게 필요하다), 그때 두 인스턴스가 같은
    파일을 덮어쓰면 `cams-stop` 이 한쪽을 놓친다.
    """
    return PIDFILE_DIR / f"fake_cams_{'-'.join(str(cam) for cam in cam_ids)}.json"


RTSP_BASE = os.environ.get("RTSP_BASE", "rtsp://localhost:8554")
MAIN_SIZE = os.environ.get("MAIN_SIZE", "1920x1080")
SUB_SIZE = os.environ.get("SUB_SIZE", "640x360")
FPS = int(os.environ.get("FPS", "15"))

#: API명세서 §4.7 녹화 규격. 기능명세서 §4.4 의 용량 산정 근거이므로 임의로 바꾸지 않는다.
MAIN_BITRATE = os.environ.get("MAIN_BITRATE", "2500k")
SUB_BITRATE = os.environ.get("SUB_BITRATE", "600k")

#: GOP 2초. 리먹스 세그먼트를 잘라낼 때 키프레임 간격이 곧 절단 정밀도가 된다(FN-REC-03).
GOP = FPS * 2

#: 기본 카메라 집합. `--cams` 로 좁힐 수 있다.
DEFAULT_CAM_IDS = (1, 2)


class CamsError(RuntimeError):
    pass


class Stream(NamedTuple):
    """송출 경로 하나."""

    cam_id: int
    kind: str  # "main" | "sub"
    size: str
    bitrate: str

    @property
    def label(self) -> str:
        return f"cam{self.cam_id}/{self.kind}"

    @property
    def url(self) -> str:
        return f"{RTSP_BASE}/{self.label}"


# ffmpeg 로그와 같은 화면에 섞이므로 인코딩을 UTF-8 로 맞춘다 (tasks.py 와 동일).
# `reconfigure` 는 `TextIOWrapper` 에만 있으므로 isinstance 로 좁힌다.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def say(message: str = "") -> None:
    print(message, flush=True)


def require_16_9(label: str, size: str) -> tuple[int, int]:
    """화면비 검증 (API명세서 §1.2).

    엣지는 서브에서 정규화 좌표를 산출하고, 대시보드는 그 좌표를 메인 위에 그린다.
    두 스트림의 화면비가 다르면 좌표가 한쪽 축으로 눌려 박스가 어긋난다.
    특히 서브를 정사각(640x640)으로 두면 화각이 잘리므로 여기서 막는다.
    """
    width, _, height = size.partition("x")
    if not width.isdigit() or not height.isdigit():
        raise CamsError(f"해상도 형식 오류: {label}={size} (예: 1920x1080)")
    w, h = int(width), int(height)
    if w * 9 != h * 16:
        raise CamsError(
            f"화면비 오류: {label}={size} 는 16:9가 아니다.\n"
            f"  메인과 서브의 화면비가 다르면 정규화 좌표가 어긋난다(API명세서 §1.2)."
        )
    return w, h


#: `drawtext` 에 넘길 폰트 후보. 플랫폼별로 먼저 찾은 것을 쓴다.
FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/consola.ttf"),  # 고정폭 — 밀리초가 흔들리지 않는다
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"),
    Path("/System/Library/Fonts/Supplemental/Menlo.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
)


def drawtext_font() -> str:
    """`drawtext` 용 폰트 경로를 ffmpeg 필터 문법에 맞게 감싸서 돌려준다.

    폰트를 명시하지 않으면 ffmpeg 가 fontconfig 로 기본 폰트를 찾는데, Windows 빌드에는
    fontconfig 설정 파일이 없어 `drawtext` 가 접근 위반으로 죽는다. 그래서 경로를 직접 준다.

    윈도우 드라이브 문자의 ':' 는 **따옴표로 감싸는 것만으로는 부족하고** 이스케이프도
    같이 해야 한다. 셋 중 하나만 빠져도 필터 파싱이 깨진다 (ffmpeg 8.1 확인).

    폰트를 못 찾으면 타임코드를 빼고 계속하지 않는다. 타임코드가 없으면 영상 지연을
    잴 수단이 사라지고, 그 사실이 조용히 묻힌다.
    """
    for path in FONT_CANDIDATES:
        if path.is_file():
            escaped = path.as_posix().replace(":", r"\:")
            return f"'{escaped}'"
    raise CamsError(
        "drawtext 용 폰트를 찾지 못했다. 타임코드 없이 송출하지 않는다.\n"
        "  타임코드는 영상 지연을 재는 유일한 수단이고 M2 오버레이 정합(±100ms)의\n"
        "  기준선이다. 아래 중 하나가 존재해야 한다:\n"
        + "\n".join(f"    {p}" for p in FONT_CANDIDATES)
        + "\n  또는 FONT 환경변수 대신 후보 목록에 경로를 추가해라."
    )


def timecode_filter(stream: Stream, font: str) -> str:
    """벽시계 타임코드를 밀리초까지 소성하는 필터 체인.

    지연 측정이 성립하려면 화면에 찍힌 시각이 **프레임이 만들어진 실제 벽시계 시각**
    이어야 한다. ffmpeg 기동 시각을 파이썬이 미리 재서 넘기는 방식은 ffmpeg 초기화에
    드는 수백 ms 가 그대로 오차로 남으므로 쓰지 않는다.

        realtime                      벽시계 속도로 프레임을 흘린다
        setpts=RTCTIME/(TB*1000000)   pts 를 **에포크 초**로 덮어쓴다
        drawtext                      그 pts 를 그대로 UTC 시각으로 렌더링
        setpts=PTS-STARTPTS           인코딩용으로 0 기준으로 되돌린다

    마지막 되돌림이 필요한 이유: 에포크 pts(1.8e9)를 그대로 먹이면 muxer 마다 취급이
    달라진다. drawtext 가 이미 글자를 그린 뒤이므로 되돌려도 화면은 바뀌지 않는다.

    ffmpeg 필터 문자열 안에서 ':' 와 ',' 는 구분자다. 작은따옴표로 감싸는 것만으로는
    부족해서 이스케이프까지 같이 한다(폰트 경로와 같은 이유).

    시·분·초·밀리초를 **전부 `eif` 산술로** 만든다. `%{pts\\:gmtime\\:0\\:%H\\:%M\\:%S}`
    쪽이 짧지만, strftime 포맷 안의 ':' 가 필터 파서와 drawtext 확장기를 두 번 거치면서
    인자 구분자로 먹혀 `%{pts} requires at most 3 arguments` 로 죽는다(ffmpeg 8.1 확인).
    네 값이 모두 같은 `t` 에서 나오므로 초 경계에서 서로 어긋나지 않는다.

    밀리초는 프레임 간격(15fps → 66.7ms)으로 양자화된다. 그 이상 정밀하게 찍힐 수
    없으므로 지연 실측 분해능도 거기까지다.
    """
    hh = r"%{eif\:mod(trunc(t/3600)\,24)\:d\:2}"
    mm = r"%{eif\:mod(trunc(t/60)\,60)\:d\:2}"
    ss = r"%{eif\:mod(t\,60)\:d\:2}"
    ms = r"%{eif\:trunc(mod(t\,1)*1000)\:d\:3}"
    text = rf"{stream.label} {hh}\:{mm}\:{ss}.{ms} UTC"
    fontsize = 32 if stream.kind == "sub" else 56
    return (
        "realtime,"
        "setpts=RTCTIME/(TB*1000000),"
        f"drawtext=fontfile={font}:text='{text}'"
        f":fontcolor=white:fontsize={fontsize}:box=1:boxcolor=black@0.6:boxborderw=8"
        ":x=24:y=24,"
        "setpts=PTS-STARTPTS"
    )


def input_args(source: str | None) -> list[str]:
    """입력 인자. 파일이 주어지면 무한 루프 재생, 없으면 testsrc2 패턴.

    `-re` 를 쓰지 않는다 — 속도 조절은 필터 체인의 `realtime` 이 맡는다. 둘을 같이
    쓰면 이중으로 조절돼 pts 가 벽시계에서 밀린다.
    """
    if source:
        if not Path(source).is_file():
            raise CamsError(f"영상 파일을 찾을 수 없다: {source}")
        return ["-stream_loop", "-1", "-i", source]
    return ["-f", "lavfi", "-i", f"testsrc2=size={MAIN_SIZE}:rate={FPS}"]


def ffmpeg_argv(ffmpeg: str, stream: Stream, source: str | None, font: str) -> list[str]:
    """경로 하나를 송출하는 ffmpeg 명령."""
    profile = "baseline" if stream.kind == "sub" else "main"
    # 비트레이트를 상한까지 묶어둔다. 평균만 맞추면 순간 피크가 커져 1시간 실측
    # 용량이 §4.4 산정(2채널 2.2GB/시간)에서 벗어난다.
    maxrate = stream.bitrate
    bufsize = f"{int(stream.bitrate.rstrip('k')) * 2}k"
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "warning",
        "-nostdin",
        *input_args(source),
        "-vf", f"scale={stream.size},fps={FPS},{timecode_filter(stream, font)}",
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-profile:v", profile,
        "-pix_fmt", "yuv420p",
        "-b:v", stream.bitrate,
        "-maxrate", maxrate,
        "-bufsize", bufsize,
        "-g", str(GOP),
        "-keyint_min", str(GOP),
        "-sc_threshold", "0",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        stream.url,
    ]  # fmt: skip


def planned_streams(cam_ids: Sequence[int]) -> list[Stream]:
    streams: list[Stream] = []
    for cam_id in cam_ids:
        streams.append(Stream(cam_id, "main", MAIN_SIZE, MAIN_BITRATE))
        streams.append(Stream(cam_id, "sub", SUB_SIZE, SUB_BITRATE))
    return streams


def write_pidfile(path: Path, labels: list[str], processes: list[subprocess.Popen[bytes]]) -> None:
    """`tasks.py cams-stop` 이 읽는다. 부모가 죽어도 자식을 정리할 수 있어야 한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "supervisor": os.getpid(),
        "processes": [
            {"pid": proc.pid, "label": label} for label, proc in zip(labels, processes, strict=True)
        ],
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def stop_all(processes: list[subprocess.Popen[bytes]], pidfile: Path | None = None) -> None:
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
    for proc in processes:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    if pidfile is not None:
        pidfile.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv run tasks.py cams",
        description="가짜 IP 카메라 2대를 RTSP 4경로로 송출한다",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=None,
        metavar="영상파일",
        help=(
            "카메라에 쓸 영상 파일. 두 번 주면 카메라별로 다르게 쓴다. "
            "없으면 testsrc2 테스트 패턴을 송출한다"
        ),
    )
    parser.add_argument(
        "--cams",
        default=",".join(str(cam) for cam in DEFAULT_CAM_IDS),
        metavar="번호목록",
        help=(
            "송출할 카메라 (기본 1,2). 한 대만 끊는 상황을 만들려면 "
            "`--cams 1` 과 `--cams 2` 를 따로 띄운다"
        ),
    )
    return parser


def parse_cam_ids(text: str) -> list[int]:
    try:
        cam_ids = [int(part) for part in text.split(",") if part.strip()]
    except ValueError:
        raise CamsError(f"--cams 형식 오류: {text!r} (예: 1,2)") from None
    if not cam_ids:
        raise CamsError("--cams 가 비어 있다")
    return cam_ids


def sources_for_cams(sources: list[str] | None, cam_ids: Sequence[int]) -> dict[int, str | None]:
    """`--source` 인자를 카메라별로 배분한다. 하나만 주면 두 대가 같이 쓴다."""
    if not sources:
        return dict.fromkeys(cam_ids)
    return {cam_id: sources[min(index, len(sources) - 1)] for index, cam_id in enumerate(cam_ids)}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    processes: list[subprocess.Popen[bytes]] = []
    labels: list[str] = []
    pidfile: Path | None = None
    try:
        cam_ids = parse_cam_ids(args.cams)
        pidfile = pidfile_for(cam_ids)
        require_16_9("MAIN_SIZE", MAIN_SIZE)
        require_16_9("SUB_SIZE", SUB_SIZE)

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise CamsError(
                "ffmpeg 를 찾을 수 없다.\n"
                "  설치해 PATH 에 넣어라 (Windows: winget install Gyan.FFmpeg)."
            )

        font = drawtext_font()
        per_cam = sources_for_cams(args.source, cam_ids)
        if not args.source:
            say("[fake_cams] --source 없음 - testsrc2 테스트 패턴을 송출한다")

        for stream in planned_streams(cam_ids):
            say(
                f"[fake_cams] {stream.label:<10} {stream.size}@{FPS} "
                f"{stream.bitrate:>6}  ->  {stream.url}"
            )
            processes.append(
                subprocess.Popen(ffmpeg_argv(ffmpeg, stream, per_cam[stream.cam_id], font))
            )
            labels.append(stream.label)
    except CamsError as exc:
        stop_all(processes, pidfile)
        say(f"[fake_cams] {exc}")
        return 1

    write_pidfile(pidfile, labels, processes)

    def on_signal(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_signal)

    say("[fake_cams] 송출 중. Ctrl+C 또는 `uv run tasks.py cams-stop` 으로 종료한다.")
    exit_code = 0
    try:
        # 하나라도 죽으면 전부 내린다. 경로가 조용히 사라지면 그 뒤 실측이 전부 거짓이 된다.
        while True:
            dead = [(i, p) for i, p in enumerate(processes) if p.poll() is not None]
            if dead:
                # `cams-stop` 은 PID 파일을 지우고 자식을 죽인다. 파일이 사라졌으면
                # 의도된 종료이므로 실패로 보고하지 않는다.
                requested = not pidfile.exists()
                for index, proc in dead:
                    say(f"[fake_cams] {labels[index]} ffmpeg 종료 (코드 {proc.returncode})")
                if requested:
                    say("[fake_cams] cams-stop 요청에 따른 종료다.")
                # ffmpeg 의 원래 코드를 그대로 넘기지 않는다. Windows 상태코드
                # (0xC0000005 등)는 8비트 종료코드에 담기지 않아 값이 오염된다.
                exit_code = 0 if requested else 1
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        say()
        say("[fake_cams] 종료 중...")
    finally:
        stop_all(processes, pidfile)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
