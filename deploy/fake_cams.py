#!/usr/bin/env python
"""가짜 IP 카메라 2대를 mediamtx 로 무한 루프 송출한다.

    uv run tasks.py cams                    # 컬러바 테스트 패턴
    uv run tasks.py cams a.mp4              # 카메라 1·2 모두 a.mp4
    uv run tasks.py cams a.mp4 b.mp4        # 카메라별 다른 영상
    uv run tasks.py cams-stop               # 종료

카메라 1대당 ffmpeg 1개를 띄우고, 그 안에서 main/sub 두 출력을 동시에 낸다.
코덱·해상도·fps 는 실제 IP 카메라와 같게 맞춘다 — 여기서 어긋나면 엣지 추론
예산(기능명세서 §5)과 오버레이 정합(±100ms) 실측이 의미를 잃는다.

    main  1920x1080  H.264  15fps  서버용 (라이브 · 7일 녹화 · 클립 원본)
    sub    640x360   H.264  15fps  엣지용 (추론)

원래 `fake_cams.sh` 였다. 개발 환경이 Windows + PowerShell 이라 bash 가 전제될 수
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
from pathlib import Path
from types import FrameType

ROOT = Path(__file__).resolve().parent.parent
PIDFILE = ROOT / "media" / "run" / "fake_cams.json"

RTSP_BASE = os.environ.get("RTSP_BASE", "rtsp://localhost:8554")
MAIN_SIZE = os.environ.get("MAIN_SIZE", "1920x1080")
SUB_SIZE = os.environ.get("SUB_SIZE", "640x360")
FPS = int(os.environ.get("FPS", "15"))
MAIN_BITRATE = os.environ.get("MAIN_BITRATE", "4000k")
SUB_BITRATE = os.environ.get("SUB_BITRATE", "600k")

#: GOP 2초. 링버퍼에서 클립을 잘라낼 때 키프레임 간격이 곧 절단 정밀도가 된다(FN-REC-03).
GOP = FPS * 2


class CamsError(RuntimeError):
    pass


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
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
)


def drawtext_font() -> str | None:
    """`drawtext` 용 폰트 경로를 ffmpeg 필터 문법에 맞게 감싸서 돌려준다.

    폰트를 명시하지 않으면 ffmpeg 가 fontconfig 로 기본 폰트를 찾는데, Windows 빌드에는
    fontconfig 설정 파일이 없어 `drawtext` 가 접근 위반으로 죽는다. 그러면 카메라가
    통째로 뜨지 않으므로 경로를 직접 준다.

    윈도우 드라이브 문자의 ':' 는 **따옴표로 감싸는 것만으로는 부족하고** 이스케이프도
    같이 해야 한다. 셋 중 하나만 빠져도 필터 파싱이 깨진다 (ffmpeg 8.1 확인).
    """
    for path in FONT_CANDIDATES:
        if path.is_file():
            escaped = path.as_posix().replace(":", r"\:")
            return f"'{escaped}'"
    return None


def input_args(cam: int, video: str | None) -> list[str]:
    """입력 인자. 파일이 주어지면 무한 루프 재생, 없으면 컬러바 + 흐르는 타임코드."""
    if video:
        if not Path(video).is_file():
            raise CamsError(f"영상 파일을 찾을 수 없다: {video}")
        return ["-stream_loop", "-1", "-re", "-i", video]

    # 흐르는 타임코드는 오버레이 시간 정합(±100ms)을 눈으로 확인할 때 쓴다.
    source = f"smptebars=size={MAIN_SIZE}:rate={FPS}"
    font = drawtext_font()
    if font is None:
        say("[fake_cams] 경고: 폰트를 찾지 못했다. 타임코드 오버레이 없이 송출한다.")
    else:
        source += (
            f",drawtext=fontfile={font}:text='CAM{cam} %{{pts\\:hms}}'"
            f":fontcolor=white:fontsize=48:x=40:y=40"
        )
    return ["-re", "-f", "lavfi", "-i", source]


def ffmpeg_argv(ffmpeg: str, cam: int, video: str | None) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        *input_args(cam, video),
        "-filter_complex",
        (
            f"[0:v]split=2[main][sub];"
            f"[main]scale={MAIN_SIZE},fps={FPS}[mainout];"
            f"[sub]scale={SUB_SIZE},fps={FPS}[subout]"
        ),
        # main — 서버용
        "-map", "[mainout]",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-profile:v", "main", "-pix_fmt", "yuv420p", "-b:v", MAIN_BITRATE,
        "-g", str(GOP), "-keyint_min", str(GOP), "-sc_threshold", "0",
        "-f", "rtsp", "-rtsp_transport", "tcp", f"{RTSP_BASE}/cam{cam}/main",
        # sub — 엣지용
        "-map", "[subout]",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-b:v", SUB_BITRATE,
        "-g", str(GOP), "-keyint_min", str(GOP), "-sc_threshold", "0",
        "-f", "rtsp", "-rtsp_transport", "tcp", f"{RTSP_BASE}/cam{cam}/sub",
    ]  # fmt: skip


def write_pidfile(processes: list[subprocess.Popen[bytes]]) -> None:
    """`tasks.py cams-stop` 이 읽는다. 부모가 죽어도 자식을 정리할 수 있어야 한다."""
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "supervisor": os.getpid(),
        "processes": [
            {"pid": proc.pid, "label": f"cam{index + 1}"} for index, proc in enumerate(processes)
        ],
    }
    PIDFILE.write_text(json.dumps(record, indent=2), encoding="utf-8")


def stop_all(processes: list[subprocess.Popen[bytes]]) -> None:
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
    for proc in processes:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    PIDFILE.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="uv run tasks.py cams",
        description="가짜 IP 카메라 2대를 RTSP 로 송출한다",
    )
    parser.add_argument(
        "video",
        nargs="*",
        help="카메라 1·2 에 쓸 영상 파일. 없으면 컬러바 테스트 패턴",
    )
    args = parser.parse_args(argv)

    try:
        require_16_9("MAIN_SIZE", MAIN_SIZE)
        require_16_9("SUB_SIZE", SUB_SIZE)

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise CamsError("ffmpeg 를 찾을 수 없다. 설치해 PATH 에 넣어라.")

        cam1 = args.video[0] if args.video else None
        cam2 = args.video[1] if len(args.video) > 1 else cam1
        if cam1 is None:
            say("[fake_cams] 영상 파일 인자가 없다 - 컬러바 테스트 패턴을 송출한다")

        processes: list[subprocess.Popen[bytes]] = []
        for cam, video in ((1, cam1), (2, cam2)):
            say(
                f"[fake_cams] cam{cam}  "
                f"main={RTSP_BASE}/cam{cam}/main ({MAIN_SIZE}@{FPS})  "
                f"sub={RTSP_BASE}/cam{cam}/sub ({SUB_SIZE}@{FPS})"
            )
            processes.append(subprocess.Popen(ffmpeg_argv(ffmpeg, cam, video)))
    except CamsError as exc:
        say(f"[fake_cams] {exc}")
        return 1

    write_pidfile(processes)

    def on_signal(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_signal)

    say("[fake_cams] 송출 중. Ctrl+C 또는 `uv run tasks.py cams-stop` 으로 종료한다.")
    exit_code = 0
    try:
        # 하나라도 죽으면 전부 내린다. 카메라가 조용히 사라지면 그 뒤 실측이 전부 거짓이 된다.
        while True:
            dead = [(i, p) for i, p in enumerate(processes) if p.poll() is not None]
            if dead:
                # `cams-stop` 은 PID 파일을 지우고 자식을 죽인다. 파일이 사라졌으면
                # 의도된 종료이므로 실패로 보고하지 않는다.
                requested = not PIDFILE.exists()
                for index, proc in dead:
                    say(f"[fake_cams] cam{index + 1} ffmpeg 가 종료했다 (코드 {proc.returncode})")
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
        stop_all(processes)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
