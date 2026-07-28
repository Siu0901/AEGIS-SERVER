#!/usr/bin/env python
"""AEGIS 태스크 러너.

    uv run tasks.py <태스크> [옵션]

`make` 를 대체한다. Windows 에는 make 가 기본 설치되어 있지 않고, 젯슨(리눅스)에서도
같은 명령이 동작해야 하므로 OS 의존 명령과 셸 문법을 쓰지 않는다.

**설계 원칙 — 없는 명령은 통과가 아니라 오류다.**
이전 `make verify` 는 `command -v npm || skip` 처럼 도구가 없으면 조용히 건너뛰었고,
Windows 에는 make 자체가 없어 한 번도 실행되지 않은 채 "통과"로 보고됐다.
여기서는 실행 파일을 찾지 못하면 즉시 `TaskError` 로 중단한다. 검증되지 않은 것을
검증됐다고 말하지 않는 것이 이 파일의 유일한 존재 이유다.

`subprocess` 는 항상 `shell=False` 로 인자 리스트를 넘긴다. `&&` · 글롭 · 리다이렉션
같은 셸 전용 문법은 플랫폼마다 해석이 달라 쓰지 않는다.
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

ROOT = Path(__file__).resolve().parent
FRONT = ROOT / "front"
DEPLOY = ROOT / "deploy"
ALEMBIC_INI = ROOT / "server" / "infra" / "db" / "alembic.ini"

#: `cams` 가 띄운 ffmpeg PID 를 적어두는 곳. `cams-stop` 이 읽는다.
#: `--cams` 로 카메라를 나눠 띄우면 파일이 여러 개가 되므로 글롭으로 훑는다.
#: `media/` 는 런타임 저장소이고 git 에서 제외된다.
CAMS_PIDFILE_DIR = ROOT / "media" / "run"
CAMS_PIDFILE_GLOB = "fake_cams*.json"


class TaskError(RuntimeError):
    """태스크를 계속할 수 없는 상황. main 에서 잡아 exit 1 로 나간다."""


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
# 파이프로 넘어갈 때 파이썬은 콘솔 코드페이지가 아니라 로케일 인코딩(한글 Windows 는
# cp949)을 쓴다. ruff·mypy·pytest 는 항상 UTF-8 로 쓰므로 여기서도 UTF-8 로 맞춘다.
# 맞추지 않으면 같은 화면에서 한쪽만 깨진다. 장식 문자는 ASCII 만 쓴다.


def force_utf8(stream: object) -> None:
    """`reconfigure` 는 `TextIOWrapper` 에만 있다.

    `sys.stdout` 이 항상 그것이라는 보장은 없다 — pytest 의 캡처 스트림처럼
    교체된 경우가 있고, 그때 `reconfigure` 를 부르면 죽는다. isinstance 로 좁힌다.
    """
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(encoding="utf-8", errors="replace")


force_utf8(sys.stdout)
force_utf8(sys.stderr)


def say(message: str = "") -> None:
    print(message, flush=True)


def shell_repr(argv: Sequence[str]) -> str:
    """사람이 손으로 다시 칠 수 있게 명령을 한 줄로 보여준다. 실행에는 쓰지 않는다."""
    return " ".join(part if " " not in part else f'"{part}"' for part in argv)


# ---------------------------------------------------------------------------
# 프로세스 실행
# ---------------------------------------------------------------------------


def executable(name: str) -> str:
    """PATH 에서 실행 파일을 찾는다. 없으면 건너뛰지 않고 오류를 낸다.

    Windows 에서 `npm` 은 `npm.cmd` 다. `shutil.which` 가 PATHEXT 를 보고 확장자까지
    붙여 돌려주므로, 그 전체 경로를 그대로 넘기면 `shell=True` 없이 실행된다.
    """
    found = shutil.which(name)
    if found is None:
        raise TaskError(
            f"실행 파일을 찾을 수 없다: {name}\n"
            f"  이 단계는 건너뛰지 않는다. {name} 을 설치해 PATH 에 넣고 다시 실행해라."
        )
    return found


def run(argv: Sequence[str], *, cwd: Path | None = None, echo: bool = True) -> None:
    """자식 프로세스를 실행하고, 0이 아닌 종료코드면 TaskError 로 중단한다."""
    exe = executable(argv[0])
    if echo:
        say(f"      $ {shell_repr(argv)}")
    code = subprocess.call([exe, *argv[1:]], cwd=str(cwd or ROOT))
    if code != 0:
        raise TaskError(f"종료코드 {code} — {shell_repr(argv)}")


def capture(argv: Sequence[str], *, cwd: Path | None = None, echo: bool = True) -> str:
    """출력을 삼켜야 하는 명령용. 실패하면 삼킨 출력을 다시 뱉고 중단한다."""
    exe = executable(argv[0])
    if echo:
        say(f"      $ {shell_repr(argv)}")
    proc = subprocess.run(
        [exe, *argv[1:]],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        say(proc.stdout.rstrip())
        say(proc.stderr.rstrip())
        raise TaskError(f"종료코드 {proc.returncode} — {shell_repr(argv)}")
    return proc.stdout


def uv(*args: str) -> list[str]:
    return ["uv", "run", *args]


def alembic(*args: str) -> list[str]:
    return uv("alembic", "-c", str(ALEMBIC_INI.relative_to(ROOT).as_posix()), *args)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


class Progress:
    """단계 번호와 '대상 없음' 목록을 들고 다닌다."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.index = 0
        self.empty: list[str] = []

    def start(self, name: str) -> None:
        self.index += 1
        say()
        say(f"[{self.index}/{self.total}] {name}")

    def ok(self, note: str = "") -> None:
        say(f"      OK{f'  ({note})' if note else ''}")

    def nothing_to_do(self, name: str, why: str) -> None:
        """검사 대상이 아직 없는 단계. 통과가 아니라 '대상 없음'으로 따로 센다."""
        self.start(name)
        say(f"      대상 없음 - {why}")
        self.empty.append(f"{name} - {why}")


def check_migrations(step: Progress) -> None:
    """마이그레이션 정합 — DB 없이 확인할 수 있는 것까지.

    1. head 가 정확히 하나인가. 브랜치가 갈리면 `upgrade head` 가 모호해진다.
    2. 오프라인 렌더링(`--sql`)이 끝까지 도는가. 리비전 체인이 끊기거나 SQL 생성이
       깨지면 여기서 잡힌다.

    모델(`server/infra/db/models.py`)과 마이그레이션의 실제 드리프트는 alembic
    autogenerate 가 살아있는 DB 연결을 요구하므로 여기서 볼 수 없다. 스키마가
    명세서 §6 과 맞는지는 `server/tests/test_db_schema.py` 가 메타데이터 수준에서 본다.
    """
    step.start("alembic 마이그레이션 정합")

    heads = [line for line in capture(alembic("heads")).splitlines() if line.strip()]
    if len(heads) != 1:
        raise TaskError(
            f"alembic head 가 {len(heads)}개다. 정확히 하나여야 한다:\n"
            + "\n".join(f"  {line}" for line in heads)
        )

    sql = capture(alembic("upgrade", "head", "--sql"))
    if not sql.strip():
        raise TaskError("alembic 오프라인 렌더링 결과가 비어 있다. 마이그레이션이 없다.")

    step.ok(f"head 1개 · SQL {len(sql.splitlines())}줄 렌더링")


def check_front(step: Progress) -> None:
    """프론트 타입체크와 빌드. npm 이 없으면 건너뛰지 않고 실패한다."""
    package_json = FRONT / "package.json"
    if not package_json.exists():
        raise TaskError(f"{package_json} 가 없다. 프론트 검증을 건너뛰지 않는다.")

    if not (FRONT / "node_modules").exists():
        step.start("front 의존성 설치")
        run(["npm", "ci"], cwd=FRONT)
        step.ok()
    else:
        step.start("front 의존성 설치")
        say("      node_modules 있음 - npm ci 생략")
        step.ok()

    step.start("front 타입체크 (tsc --noEmit)")
    run(["npm", "run", "typecheck"], cwd=FRONT)
    step.ok()

    step.start("front 빌드 (vite build)")
    run(["npm", "run", "build"], cwd=FRONT)
    step.ok()


def task_verify() -> int:
    """lint + typecheck + pytest + 마이그레이션 + 스모크 + 프론트 빌드.

    한 단계라도 실패하면 즉시 멈춘다. 뒤 단계의 결과는 앞 단계가 성립할 때만
    의미가 있고, 실패 목록을 길게 늘어놓는 것보다 첫 원인을 보는 편이 빠르다.
    """
    say("===== uv run tasks.py verify =====")
    step = Progress(total=10)

    step.start("ruff check")
    run(uv("ruff", "check", "."))
    step.ok()

    step.start("ruff format --check")
    run(uv("ruff", "format", "--check", "."))
    step.ok()

    step.start("mypy (strict)")
    run(uv("mypy"))
    step.ok()

    step.start("pytest")
    run(uv("pytest"))
    step.ok()

    check_migrations(step)

    step.start("서버 부팅 스모크")
    run(
        uv(
            "python",
            "-c",
            'from server.app.main import app; assert app.title == "AEGIS"',
        )
    )
    step.ok()

    check_front(step)

    step.nothing_to_do(
        "contracts -> front 타입 정합",
        "생성기가 아직 없다 (M5). front/src/types/system.ts 는 §4.6·§5.3 을 손으로 옮긴 것이라"
        " contracts 와 어긋나도 지금은 아무도 잡아주지 않는다",
    )

    say()
    say("==================================")
    say(f"verify 통과 - {step.index - len(step.empty)}단계 실행, {len(step.empty)}단계 대상 없음")
    for note in step.empty:
        say(f"  · {note}")
    return 0


# ---------------------------------------------------------------------------
# 나머지 태스크
# ---------------------------------------------------------------------------


def task_fmt() -> int:
    say("[fmt] 포매팅과 자동 수정")
    run(uv("ruff", "format", "."))
    run(uv("ruff", "check", "--fix", "."))
    return 0


def task_migrate() -> int:
    say("[migrate] alembic upgrade head")
    run(alembic("upgrade", "head"))
    say("[migrate] policies 기본값 시드")
    run(uv("python", "-m", "scripts.seed_policies"))
    return 0


#: `dev` 가 한 터미널에서 함께 띄우는 것들.
#:
#: 카메라를 1·2 로 나눠 띄우는 이유: 한 대만 껐다 켜서 재연결을 확인하려면 프로세스가
#: 나뉘어 있어야 한다. 하나로 묶으면 cam2 를 끄는 순간 cam1 까지 같이 내려간다.
DEV_SERVICES: tuple[tuple[str, list[str]], ...] = (
    ("cam1", [sys.executable, str(DEPLOY / "fake_cams.py"), "--cams", "1"]),
    ("cam2", [sys.executable, str(DEPLOY / "fake_cams.py"), "--cams", "2"]),
    ("rec", ["uv", "run", "python", "-m", "recorder.main"]),
    ("server", [*uv("uvicorn", "server.app.main:app"), "--host", "127.0.0.1", "--port", "8000"]),
    ("front", ["npm", "--prefix", str(FRONT), "run", "dev"]),
)  # fmt: skip


def task_dev() -> int:
    """개발 스택 전체를 한 터미널에서 띄운다. Ctrl+C 로 전부 내린다.

    따로따로 띄우면 터미널이 다섯 개 필요하고, 그중 하나가 조용히 죽어도 알아채기
    어렵다. 실제로 카메라만 죽은 채 화면을 보면 "전부 끊김"으로 보이는데 원인이
    어디인지 바로 드러나지 않는다.
    """
    say("[dev] docker compose up -d")
    run(["docker", "compose", "up", "-d"])
    say("      postgres/redis/mosquitto/mediamtx 기동")
    task_migrate()

    say()
    say("[dev] 프로세스 기동")
    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    try:
        for name, argv in DEV_SERVICES:
            exe = executable(argv[0])
            say(f"      {name:<7} {shell_repr(argv)}")
            processes.append((name, subprocess.Popen([exe, *argv[1:]], cwd=str(ROOT))))
    except TaskError:
        _stop_dev(processes)
        raise

    say()
    say("[dev] 실시간 관제  http://localhost:5173/live")
    say("      API 문서     http://localhost:8000/docs")
    say("      Ctrl+C 로 전부 내린다.")
    say()

    exit_code = 0
    watched = list(processes)
    try:
        while True:
            dead = [(name, proc) for name, proc in watched if proc.poll() is not None]
            for name, proc in dead:
                watched.remove((name, proc))
                if proc.returncode == 0:
                    # 사람이 일부러 내린 것이다 (예: `cams-stop --cams 2` 로 한 대만
                    # 끊어 재연결을 확인하는 중). 나머지를 같이 내리면 그 확인 자체가
                    # 불가능해진다. 다시 켤 명령을 알려주고 계속 돈다.
                    say(f"[dev] {name} 이(가) 정상 종료됐다 (외부에서 내린 것으로 본다)")
                    if name.startswith("cam"):
                        say(f"       다시 켜기: uv run tasks.py cams --cams {name[3:]}")
                else:
                    # 예기치 않게 죽었다. 반쯤 살아 있는 스택은 화면상 "전부 끊김"과
                    # 구분되지 않아 더 헷갈리므로 전부 내린다.
                    say(f"[dev] {name} 이(가) 코드 {proc.returncode} 로 죽었다 - 스택을 내린다")
                    exit_code = 1
            if exit_code or not watched:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        say()
        say("[dev] 종료 중...")
    finally:
        _stop_dev(processes)
    return exit_code


def _stop_dev(processes: Sequence[tuple[str, subprocess.Popen[bytes]]]) -> None:
    for _, proc in processes:
        if proc.poll() is None:
            proc.terminate()
    for name, proc in processes:
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            say(f"      {name} 응답 없음 - 강제 종료")
            proc.kill()
    # 감독자가 강제 종료되면 ffmpeg 손자 프로세스가 남을 수 있다.
    task_cams_stop()


def task_cams(sources: Sequence[str], cams: str | None) -> int:
    say("[cams] 가짜 RTSP 송출 (카메라당 main·sub 2경로)")
    argv = [sys.executable, str(DEPLOY / "fake_cams.py")]
    for source in sources:
        argv += ["--source", source]
    if cams:
        argv += ["--cams", cams]
    run(argv)
    return 0


def task_rec(extra: Sequence[str]) -> int:
    """REC — 녹화 컴포넌트 (API명세서 §4.7).

    별도 프로세스로 띄운다. 서버와 같은 기계에서 돌더라도 **HTTP 로만** 통신하므로,
    M9 에 젯슨으로 옮길 때 `RECORDER_BASE` 만 바꾸면 된다.
    """
    say("[rec] 녹화 컴포넌트 — 메인 스트림 세그먼트 녹화 + 구간 추출")
    run(uv("python", "-m", "recorder.main", *extra))
    return 0


def task_cams_stop(cams: str | None = None) -> int:
    """`cams` 가 띄운 ffmpeg 를 정리한다.

    `--cams 2` 를 주면 **그 카메라만** 내린다. 재연결 확인(카메라 한 대만 끊고
    복구되는지)을 하려면 나머지는 살아 있어야 하는데, PID 를 직접 찾아 죽이게 하면
    실수로 다른 카메라까지 내리기 쉽다.

    인자가 없으면 전부 내린다. `--cams` 로 나눠 띄웠으면 PID 파일이 여러 개이므로
    전부 훑는다 — 하나만 지우면 남은 송출이 계속 돌면서 다음 실측을 오염시킨다.

    `os.kill(pid, SIGTERM)` 은 Windows 에서 TerminateProcess 로 매핑되므로 양쪽에서
    동작한다. PID 재사용 가능성은 남지만 개발용 도구이므로 여기까지만 한다.
    """
    if cams:
        say(f"[cams-stop] 카메라 {cams} 송출만 종료")
        wanted = [part.strip() for part in cams.split(",") if part.strip()]
        pidfiles = [CAMS_PIDFILE_DIR / f"fake_cams_{'-'.join(wanted)}.json"]
        pidfiles = [path for path in pidfiles if path.exists()]
        if not pidfiles:
            say(f"      카메라 {cams} 로 띄운 송출이 없다.")
            say("      `uv run tasks.py dev` 는 카메라를 1·2 로 나눠 띄우므로")
            say("      `uv run tasks.py cams-stop --cams 2` 처럼 한 대씩 지정한다.")
            return 0
    else:
        say("[cams-stop] 가짜 RTSP 송출 전부 종료")
        pidfiles = sorted(CAMS_PIDFILE_DIR.glob(CAMS_PIDFILE_GLOB))
    if not pidfiles:
        say(f"      기록된 프로세스가 없다 ({CAMS_PIDFILE_DIR.relative_to(ROOT).as_posix()})")
        return 0

    stopped = 0
    for pidfile in pidfiles:
        record = json.loads(pidfile.read_text(encoding="utf-8"))
        for entry in record.get("processes", []):
            pid = int(entry["pid"])
            label = entry.get("label", "?")
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as exc:  # ProcessLookupError · PermissionError 포함
                say(f"      pid {pid} ({label}) - 이미 없음 ({exc.__class__.__name__})")
            else:
                say(f"      pid {pid} ({label}) 종료")
                stopped += 1
        pidfile.unlink(missing_ok=True)

    say(f"      {stopped}개 종료")
    return 0


def task_sim(case: str, extra: Sequence[str]) -> int:
    say(f"[sim] 가짜 엣지 - case={case}")
    run(uv("python", "-m", "sim.edge_sim.main", "--case", case, *extra))
    return 0


def task_mcu(extra: Sequence[str]) -> int:
    say("[mcu] 가짜 ESP32")
    run(uv("python", "-m", "sim.mcu_sim.main", *extra))
    return 0


def task_types() -> int:
    """contracts -> front TypeScript 타입 생성. M5 에서 구현한다.

    구현 전까지 0을 돌려주지 않는다. 하지 않은 일을 했다고 보고하는 것이 이 러너를
    새로 쓰게 된 원인이다.
    """
    raise TaskError(
        "types 생성기가 아직 없다 (M5 에서 구현한다).\n"
        "  도구 문제가 아니라 미구현이다. 구현 전까지 이 태스크는 성공하지 않는다."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv run tasks.py",
        description="AEGIS 태스크 러너 (make 대체)",
    )
    sub = parser.add_subparsers(dest="task", required=True, metavar="<태스크>")

    sub.add_parser("verify", help="lint + typecheck + pytest + 마이그레이션 + 스모크 + 프론트 빌드")
    sub.add_parser("fmt", help="포매팅과 자동 수정")
    sub.add_parser("dev", help="docker-compose + 마이그레이션 + 실행 안내")
    sub.add_parser("migrate", help="alembic upgrade head + policies 시드")
    sub.add_parser("types", help="contracts -> front TypeScript 타입 생성 (M5)")

    cams = sub.add_parser("cams", help="가짜 RTSP 4경로 송출 (cam1·cam2 × main·sub)")
    cams.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="영상파일",
        help="카메라에 쓸 영상 파일. 두 번 주면 카메라별로 다르게 쓴다. 없으면 testsrc2",
    )
    cams.add_argument(
        "--cams",
        default=None,
        metavar="번호목록",
        help="송출할 카메라 (기본 1,2). 한 대만 끊어보려면 --cams 1 과 --cams 2 를 따로 띄운다",
    )
    cams_stop = sub.add_parser("cams-stop", help="cams 가 띄운 ffmpeg 종료")
    cams_stop.add_argument(
        "--cams",
        default=None,
        metavar="번호목록",
        help="이 카메라만 종료 (예: --cams 2). 없으면 전부 종료",
    )

    rec = sub.add_parser("rec", help="REC — 녹화 컴포넌트 (API명세서 §4.7)")
    rec.add_argument("extra", nargs=argparse.REMAINDER, help="recorder 에 그대로 넘길 인자")

    sim = sub.add_parser("sim", help="가짜 엣지 실행")
    sim.add_argument("--case", default="no_helmet_resolved", help="sim/cases/ 의 시나리오 이름")
    sim.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="edge_sim 에 그대로 넘길 인자 (--url · --mode · --speed)",
    )

    mcu = sub.add_parser("mcu", help="가짜 ESP32 실행")
    mcu.add_argument("extra", nargs=argparse.REMAINDER, help="mcu_sim 에 그대로 넘길 인자")

    return parser


def dispatch(args: argparse.Namespace) -> int:
    match args.task:
        case "verify":
            return task_verify()
        case "fmt":
            return task_fmt()
        case "dev":
            return task_dev()
        case "migrate":
            return task_migrate()
        case "types":
            return task_types()
        case "cams":
            return task_cams(args.source, args.cams)
        case "cams-stop":
            return task_cams_stop(args.cams)
        case "rec":
            return task_rec(args.extra)
        case "sim":
            return task_sim(args.case, args.extra)
        case "mcu":
            return task_mcu(args.extra)
        case _:  # argparse 가 막아주므로 도달하지 않는다.
            raise TaskError(f"알 수 없는 태스크: {args.task}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except TaskError as exc:
        say()
        say(f"실패: {exc}")
        return 1
    except KeyboardInterrupt:
        say()
        say("중단")
        return 130


if __name__ == "__main__":
    sys.exit(main())
