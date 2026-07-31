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
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONT = ROOT / "front"
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


# ---------------------------------------------------------------------------
# 포트 선점 감시 (dev)
# ---------------------------------------------------------------------------
# ★ **경고가 아니라 중단이다.**
#
# 이전 세션의 서버·REC 가 살아 있으면 새 프로세스는 포트를 못 잡고 죽는데, 그동안
# **옛 프로세스가 옛 코드로 정상 응답한다.** 화면도 API 도 멀쩡해 보이므로 새 코드를
# 확인한 줄 알고 옛 코드를 보게 된다 — M7 에서 실제로 겪었고, 이틀 된 프로세스가
# 사라진 컬럼을 그대로 내려주고 있었다(`docs/INDEX.md` M7 절).
#
# 경고로 두면 화면이 스크롤되어 지나가고, 정작 확인해야 할 순간에는 이미 위로 밀려 있다.

#: `dev` 가 직접 띄우는 것들이 잡는 포트. docker compose 가 관리하는 포트(postgres ·
#: redis · mosquitto · mediamtx)는 여기 없다 — 그쪽은 compose 가 스스로 재사용한다.
DEV_PORTS: tuple[tuple[int, str], ...] = (
    (8000, "server (uvicorn)"),
    (9100, "rec (recorder)"),
    (5173, "front (vite)"),
)


def listeners_on(port: int) -> list[tuple[int, str]]:
    """그 포트를 **듣고 있는** 프로세스들의 (PID, 이름). 없으면 빈 목록.

    `psutil` 을 새로 넣지 않고 표준 라이브러리와 OS 도구만 쓴다. 실패하면 조용히 빈
    목록을 돌려주지 않고 예외를 올린다 — "확인할 수 없었다"를 "비어 있다"로 바꾸면
    이 가드가 있으나 마나가 된다(절대규칙 9).
    """
    argv = ["netstat", "-ano", "-p", "TCP"] if _IS_WINDOWS else ["ss", "-ltnp"]
    exe = shutil.which(argv[0])
    if exe is None:
        raise TaskError(
            f"포트 점유를 확인할 도구가 없다: {argv[0]}\n"
            "  이 확인은 건너뛰지 않는다. 옛 프로세스가 포트를 쥔 채로 dev 를 띄우면\n"
            "  새 코드를 확인한 줄 알고 옛 코드를 보게 된다."
        )
    proc = subprocess.run(
        [exe, *argv[1:]], capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        raise TaskError(f"포트 점유 확인 실패 ({argv[0]}): {proc.stderr.strip()}")

    pids: set[int] = set()
    for line in proc.stdout.splitlines():
        if f":{port}" not in line:
            continue
        if _IS_WINDOWS:
            parts = line.split()
            # PROTO  LOCAL  FOREIGN  STATE  PID  — LISTENING 만 본다. 나가는 연결이
            # 우연히 같은 번호를 원격 포트로 쓰면 여기 걸리는데, 그건 선점이 아니다.
            if len(parts) < 5 or parts[3] != "LISTENING":
                continue
            if not parts[1].endswith(f":{port}"):
                continue
            pids.add(int(parts[4]))
        else:
            for token in line.split():
                if token.startswith("users:"):
                    pids.update(int(value) for value in _PID_RE.findall(token))
    return sorted((pid, process_name(pid)) for pid in pids)


#: `ss -ltnp` 의 `users:(("uvicorn",pid=1234,fd=7))` 에서 PID 만 뽑는다.
_PID_RE = re.compile(r"pid=(\d+)")

#: 지금 윈도우인가. **`sys.platform` 을 직접 비교하지 않는다** — 타입 검사기가 그것을
#: 상수로 좁혀 반대편 분기를 「도달 불가」로 지워 버리고, 그러면 젯슨(리눅스) 경로가
#: 검사에서 통째로 빠진다. 같은 명령이 두 OS 에서 다 돌아야 하는 파일이다.
_IS_WINDOWS = os.name == "nt"


def process_name(pid: int) -> str:
    """PID 의 실행 파일 이름. 알 수 없으면 `?`.

    이름이 있어야 사람이 "내가 띄운 uvicorn 이구나"를 알고 안심하고 죽일 수 있다.
    번호만 주면 그 프로세스가 무엇인지 다시 찾아봐야 한다.
    """
    argv = (
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
        if _IS_WINDOWS
        else ["ps", "-p", str(pid), "-o", "comm="]
    )
    exe = shutil.which(argv[0])
    if exe is None:
        return "?"
    proc = subprocess.run(
        [exe, *argv[1:]], capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
    )  # fmt: skip
    output = proc.stdout.strip()
    if not output:
        return "?"
    if _IS_WINDOWS:
        return output.split(",")[0].strip('"') or "?"
    return output.splitlines()[0].strip() or "?"


def ensure_ports_free(ports: Sequence[tuple[int, str]] = DEV_PORTS) -> None:
    """포트를 쥔 프로세스가 있으면 **PID 와 함께 알리고 중단한다.**"""
    held: list[str] = []
    for port, who in ports:
        for pid, name in listeners_on(port):
            held.append(f"  {port:>5}  {who:<18} PID {pid} ({name})")
    if not held:
        return

    kill = "taskkill /PID <PID> /F" if _IS_WINDOWS else "kill <PID>"
    raise TaskError(
        "포트가 이미 잡혀 있다 — dev 를 띄우지 않는다.\n"
        + "\n".join(held)
        + "\n\n  이전 세션의 프로세스가 살아 있으면 새 프로세스는 포트를 못 잡고 죽는데,\n"
        "  그동안 **옛 프로세스가 옛 코드로 정상 응답한다.** 화면도 API 도 멀쩡해 보여서\n"
        "  새 코드를 확인한 줄 알고 옛 코드를 보게 된다.\n"
        f"\n  정리: {kill}"
    )


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

    step.start("front 단위 테스트 (vitest)")
    # `overlayBuffer.ts` 의 보간·부호·낡음 판정과 `formatRate` 의 null 처리가 여기 걸린다.
    # M2 에서는 스크래치에서 손으로 확인했고, 그것은 다음 사람이 반복할 수 없는 검증이다.
    run(["npm", "run", "test"], cwd=FRONT)
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
    step = Progress(total=11)

    # 프론트 타입 생성물이 계약과 맞는지 **먼저** 본다. 낡은 타입 위에서 돈 타입체크는
    # 통과해도 의미가 없다 — 계약이 넓어진 것을 프론트가 모르는 상태 그대로 통과한다.
    step.start("contracts -> front 타입 정합 (재생성 후 대조)")
    run(uv("python", "-m", "scripts.gen_types", "--check"))
    step.ok()

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
    # FN-CFG-01 — 구역보다 카메라가 먼저다. `zones.polygon_m` 은 지면 좌표라
    # 캘리브레이션 없이는 화면에 그릴 수도 없다.
    say("[migrate] cameras 개발용 캘리브레이션 시드")
    run(uv("python", "-m", "scripts.seed_cameras"))
    say("[migrate] zones 개발용 기본값 시드")
    run(uv("python", "-m", "scripts.seed_zones"))
    # FN-ALM-01 · FN-CFG-03 — 음원 매핑은 코드가 아니라 DB 에서 읽는다. 파일이 없으면
    # 무음 wav 를 깔아 경로를 맞춘다(실제 녹음은 사람이 나중에 덮어쓴다).
    say("[migrate] alert_sounds 시드 + 무음 wav 확인")
    run(uv("python", "-m", "scripts.seed_sounds"))
    return 0


# 카메라를 1·2 로 나눠 띄우는 이유: 한 대만 껐다 켜서 재연결을 확인하려면 프로세스가
# 나뉘어 있어야 한다. 하나로 묶으면 cam2 를 끄는 순간 cam1 까지 같이 내려간다.
def dev_services() -> tuple[tuple[str, list[str]], ...]:
    """`dev` 가 한 터미널에서 함께 띄우는 것들.

    상수가 아니라 함수인 이유: 카메라 명령이 `cams_argv`(기본 `--copy`)에서 나오므로
    그 함수보다 먼저 평가될 수 없다. 여기서 한 번 더 적으면 `cams` 와 `dev` 의 기본
    동작이 갈릴 수 있고, 그러면 "cams 로는 가벼운데 dev 로는 무겁다"가 된다.
    """
    return (
    ("cam1", cams_argv(cams="1")),
    ("cam2", cams_argv(cams="2")),
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
    # ★ 무엇을 띄우기 **전에** 확인한다. compose 를 올리고 마이그레이션을 돌린 뒤에
    #   막히면, 그 사이의 출력이 "정상 기동"처럼 보여 더 헷갈린다.
    say("[dev] 포트 점유 확인")
    ensure_ports_free()
    say("      8000 · 9100 · 5173 모두 비어 있다")

    say("[dev] docker compose up -d")
    run(["docker", "compose", "up", "-d"])
    say("      postgres/redis/mosquitto/mediamtx 기동")
    task_migrate()

    say()
    say("[dev] 프로세스 기동")
    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    try:
        for name, argv in dev_services():
            exe = executable(argv[0])
            say(f"      {name:<7} {shell_repr(argv)}")
            processes.append((name, subprocess.Popen([exe, *argv[1:]], cwd=str(ROOT))))
    except TaskError:
        _stop_dev(processes)
        raise

    say()
    say("[dev] 실시간 관제  http://127.0.0.1:5173/live")
    say("      API 문서     http://127.0.0.1:8000/docs")
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


def cams_argv(
    sources: Sequence[str] = (),
    cams: str | None = None,
    *,
    marker: bool = False,
    timecode: bool = False,
) -> list[str]:
    """가짜 카메라 송출 명령. **기본은 `--copy`(재인코딩 없음)다.**

    기본을 바꾼 이유는 실측이다 — 타임코드 모드는 네 경로가 이 노트북에서 CPU 405%
    (논리 12코어 중 4개)를 먹고, 그러면 인코더가 실시간을 못 따라가 mediamtx 가
    프레임을 버린다(`reader is too slow`). 평상시 개발·시연에서 그 대가를 치를 이유가
    없다. 실물 카메라도 이미 h264 를 뱉으므로 `--copy` 가 그 상태에 더 가깝다.

    **`--marker` 는 타임코드 모드를 강제한다.** marker 는 매 프레임 사각형을 다시
    그리므로 재인코딩이 필요하다 — 조용히 한쪽을 무시하면 정합을 재는 줄 알고 아무
    표시 없는 영상을 본다.

    **파일 경로가 아니라 모듈로 띄운다.** 파일 경로로 실행하면 `sys.path[0]` 이
    `deploy/` 가 되어 `deploy.marker_path`(marker 궤적 공유 정의)를 import 할 수 없다.
    """
    argv = [sys.executable, "-m", "deploy.fake_cams"]
    for source in sources:
        argv += ["--source", source]
    if cams:
        argv += ["--cams", cams]
    if marker:
        argv += ["--marker"]
    elif not timecode:
        argv += ["--copy"]
    return argv


def task_cams(
    sources: Sequence[str],
    cams: str | None,
    marker: bool = False,
    timecode: bool = False,
) -> int:
    say("[cams] 가짜 RTSP 송출 (카메라당 main·sub 2경로)")
    if marker or timecode:
        say("      타임코드 모드 — 실시간 재인코딩이다. CPU 를 많이 먹는다(실측 405%).")
    run(cams_argv(sources, cams, marker=marker, timecode=timecode))
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


def task_cases(case: str | None) -> int:
    """시나리오 기대값 자동 대조 (FN-EVT-02~07 · FN-SYS-04/05).

    `uv run tasks.py verify` 의 pytest 단계에도 같은 검사가 들어 있다. 이 태스크는
    시정률·판정 불가율을 **표로** 보기 위한 것이다 — 시나리오를 고칠 때 어느 숫자가
    움직였는지 한눈에 보려면 pass/fail 만으로는 부족하다.
    """
    say("[cases] 시나리오 기대값 대조 — 서버·DB 없이 상태머신에 직접 태운다")
    argv = uv("python", "-m", "sim.case_check")
    if case:
        argv += ["--case", case]
    run(argv)
    return 0


def task_marker() -> int:
    """오버레이 시간 정합(±100ms)을 화면으로 재는 방법을 안내한다.

    영상에 태운 사각형과 시뮬레이터가 보내는 좌표가 **같은 수식**(`deploy/marker_path.py`)
    에서 나온다. 화면에서 두 박스가 겹치면 정합이 맞는 것이고, 벌어진 거리가 곧 오차다.

    실행 자체를 여기서 대신 하지 않는 이유: 카메라는 계속 떠 있어야 하고 시뮬레이터는
    반복해서 돌리게 되므로, 두 프로세스의 수명이 다르다.
    """
    say("[marker] 오버레이 정합 검증 — 터미널 두 개가 필요하다")
    say()
    say("  1) 카메라를 marker 모드로 다시 띄운다 (기존 송출은 먼저 내린다)")
    say("       uv run tasks.py cams-stop")
    say("       uv run tasks.py cams --marker")
    say()
    say("  2) 같은 궤적의 좌표를 보낸다")
    say("       uv run tasks.py sim --mode marker")
    say()
    say("  3) 화면을 연다 (정합 진단 표시를 켠 채로)")
    say("       http://127.0.0.1:5173/live?debug=1")
    say()
    say("  볼 것: 영상 속 **자홍색 사각형**과 오버레이 **청록색 박스**가 겹치는가.")
    say("  가로로 벌어진 거리가 시간 오차다 — 정규화 0.01 = 약 55ms (1920px 기준 19px).")
    say("  궤적 정의는 deploy/marker_path.py 한 곳에만 있다.")
    return 0


def task_mcu(extra: Sequence[str]) -> int:
    say("[mcu] 가짜 ESP32")
    run(uv("python", "-m", "sim.mcu_sim.main", *extra))
    return 0


def task_types(check: bool = False) -> int:
    """contracts -> front TypeScript 타입 생성 (Pydantic -> JSON Schema -> TS).

    스키마의 원본은 `packages/contracts` 하나다(절대규칙 5). 프론트가 그것을 손으로
    옮겨 두면 계약이 바뀔 때 아무도 잡아주지 않으므로 생성물로 대체한다.
    """
    say("[types] contracts -> front/src/types/contracts.ts")
    argv = uv("python", "-m", "scripts.gen_types")
    if check:
        argv += ["--check"]
    run(argv)
    return 0


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
    types = sub.add_parser("types", help="contracts -> front TypeScript 타입 생성")
    types.add_argument(
        "--check",
        action="store_true",
        help="쓰지 않고 생성물이 최신인지만 확인한다 (verify 가 쓰는 방식)",
    )

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
    cams.add_argument(
        "--marker",
        action="store_true",
        help="궤적이 결정적인 사각형을 영상에 태운다 (오버레이 정합 검증 · uv run tasks.py marker)",
    )
    cams.add_argument(
        "--timecode",
        action="store_true",
        help=(
            "영상에 벽시계 타임코드를 소성한다. 실시간 재인코딩이라 CPU 를 많이 먹는다"
            " (실측 405%%). 기본은 재인코딩 없는 --copy 다"
        ),
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

    cases = sub.add_parser("cases", help="시나리오 기대값 자동 대조 (지표를 표로 확인)")
    cases.add_argument("--case", default=None, help="이 시나리오만 검사 (기본: 전부)")

    sub.add_parser("marker", help="오버레이 정합 검증 실행 방법 (marker 궤적 대조)")

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
            return task_types(args.check)
        case "cams":
            return task_cams(args.source, args.cams, args.marker, args.timecode)
        case "cams-stop":
            return task_cams_stop(args.cams)
        case "rec":
            return task_rec(args.extra)
        case "cases":
            return task_cases(args.case)
        case "marker":
            return task_marker()
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
