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

    ★ **OS 를 묻지 않고 있는 도구를 쓴다.** `ss` 는 리눅스(iproute2)에만 있고 macOS 에는
    `lsof` 가 있다. `sys.platform` 으로 가르면 타입 검사기가 그것을 상수로 좁혀 반대편
    분기를 도달 불가로 지운다 — 세 OS(윈도우 개발기 · macOS 개발기 · 젯슨)에서 같은
    명령이 돌아야 하는 파일이라 그 방식을 쓸 수 없다.
    """
    if _IS_WINDOWS:
        return _listeners_netstat(port)
    if shutil.which("ss") is not None:
        return _listeners_ss(port)
    if shutil.which("lsof") is not None:
        return _listeners_lsof(port)
    raise TaskError(
        "포트 점유를 확인할 도구가 없다: ss · lsof 둘 다 없다\n"
        "  이 확인은 건너뛰지 않는다. 옛 프로세스가 포트를 쥔 채로 dev 를 띄우면\n"
        "  새 코드를 확인한 줄 알고 옛 코드를 보게 된다."
    )


def _probe(argv: Sequence[str], *, allow_empty_failure: bool = False) -> str:
    """도구를 돌려 표준출력을 돌려준다. 없거나 실패하면 예외다."""
    exe = shutil.which(argv[0])
    if exe is None:
        raise TaskError(f"포트 점유를 확인할 도구가 없다: {argv[0]}")
    proc = subprocess.run(
        [exe, *argv[1:]], capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
    )  # fmt: skip
    # `lsof` 는 **찾은 것이 없으면 1** 로 끝난다. 그것은 실패가 아니라 「아무도 안 듣는다」다.
    if proc.returncode != 0 and not (allow_empty_failure and not proc.stdout.strip()):
        raise TaskError(f"포트 점유 확인 실패 ({argv[0]}): {proc.stderr.strip()}")
    return proc.stdout


def _named(pids: set[int]) -> list[tuple[int, str]]:
    return sorted((pid, process_name(pid)) for pid in pids)


def _listeners_netstat(port: int) -> list[tuple[int, str]]:
    """윈도우. `netstat -ano` 의 `PROTO LOCAL FOREIGN STATE PID`."""
    pids: set[int] = set()
    for line in _probe(["netstat", "-ano", "-p", "TCP"]).splitlines():
        if f":{port}" not in line:
            continue
        parts = line.split()
        # LISTENING 만 본다. 나가는 연결이 우연히 같은 번호를 원격 포트로 쓰면 여기
        # 걸리는데, 그건 선점이 아니다.
        if len(parts) < 5 or parts[3] != "LISTENING":
            continue
        if not parts[1].endswith(f":{port}"):
            continue
        pids.add(int(parts[4]))
    return _named(pids)


def _listeners_ss(port: int) -> list[tuple[int, str]]:
    """리눅스·젯슨. `ss -ltnp` 의 `users:(("uvicorn",pid=1234,fd=7))`."""
    pids: set[int] = set()
    for line in _probe(["ss", "-ltnp"]).splitlines():
        if f":{port}" not in line:
            continue
        for token in line.split():
            if token.startswith("users:"):
                pids.update(int(value) for value in _PID_RE.findall(token))
    return _named(pids)


def _listeners_lsof(port: int) -> list[tuple[int, str]]:
    """macOS. `-t` 로 PID 만 받으므로 파싱이 없다 — 형식이 바뀌어 깨질 여지도 없다.

    `-sTCP:LISTEN` 이 듣는 소켓만 고르고 `-nP` 가 이름 해석을 끈다(느려지고, 포트가
    서비스 이름으로 바뀌어 대조가 어긋난다).
    """
    argv = ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"]
    output = _probe(argv, allow_empty_failure=True)
    return _named({int(line) for line in output.split() if line.isdigit()})


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
    # ★ **구역은 시드하지 않는다.** 금지구역은 사람이 설정 화면에서 그리는 것이고
    #   (FN-CFG-02), 여기서 자동으로 넣으면 지워도 다음 기동에 되살아난다 — 실제로
    #   `forklift_lane` 이 매번 다시 생겼다. 「내가 그린 것만 있어야 한다」가 맞다.
    #
    #   시드가 필요한 경우는 하나뿐이다: `sim/edge_sim` 시나리오를 돌릴 때. 그 메시지의
    #   `in_zone: forklift_lane` 이 가리킬 행이 없으면 화면에 정체불명의 문자열만 남는다.
    #   그때는 아래 명령을 직접 부른다.
    say("[migrate] zones 시드는 건너뛴다 — 금지구역은 설정 화면에서 그린다")
    say("           시뮬레이터 시나리오를 쓸 때만: uv run python -m scripts.seed_zones")
    # FN-ALM-01 · FN-CFG-03 — 음원 매핑은 코드가 아니라 DB 에서 읽는다. 파일이 없으면
    # 무음 wav 를 깔아 경로를 맞춘다(실제 녹음은 사람이 나중에 덮어쓴다).
    say("[migrate] alert_sounds 시드 + 무음 wav 확인")
    run(uv("python", "-m", "scripts.seed_sounds"))
    # FN-CFG-05 — API 에 생성 경로가 없다(`GET`·`PATCH` 뿐). 이 행이 없으면 설정
    # 화면의 위험 반경 표가 비어 있고 `PATCH` 가 404 를 내, 현장에서 값을 조정할
    # 수단이 사라진다(기능명세서 §6 `vehicle_classes`).
    say("[migrate] vehicle_classes 위험 반경 시드")
    run(uv("python", "-m", "scripts.seed_vehicles"))
    return 0


# 카메라를 1·2 로 나눠 띄우는 이유: 한 대만 껐다 켜서 재연결을 확인하려면 프로세스가
# 나뉘어 있어야 한다. 하나로 묶으면 cam2 를 끄는 순간 cam1 까지 같이 내려간다.
def dev_services(
    sources: Sequence[str] = (),
    *,
    rec: bool = True,
    cams: bool = True,
    host: str = "127.0.0.1",
) -> tuple[tuple[str, list[str]], ...]:
    """`dev` 가 한 터미널에서 함께 띄우는 것들.

    상수가 아니라 함수인 이유: 카메라 명령이 `cams_argv`(기본 `--copy`)에서 나오므로
    그 함수보다 먼저 평가될 수 없다. 여기서 한 번 더 적으면 `cams` 와 `dev` 의 기본
    동작이 갈릴 수 있고, 그러면 "cams 로는 가벼운데 dev 로는 무겁다"가 된다.

    `sources` 는 `cams --source` 와 같은 값이다 — `dev` 로 띄울 때도 테스트 패턴 대신
    실제 영상을 보려면 필요하다. `rec=False` 는 녹화 컴포넌트를 빼고 띄운다.
    """
    services: list[tuple[str, list[str]]] = []
    if cams:
        services += [
    ("cam1", cams_argv(sources, cams="1")),
    ("cam2", cams_argv(sources, cams="2")),
        ]  # fmt: skip
    if rec:
        services.append(("rec", ["uv", "run", "python", "-m", "recorder.main"]))
    services += [
    ("server", [*uv("uvicorn", "server.app.main:app"), "--host", host, "--port", "8000"]),
    ("front", ["npm", "--prefix", str(FRONT), "run", "dev"]),
    ]  # fmt: skip
    return tuple(services)


def task_dev(
    sources: Sequence[str] = (),
    *,
    rec: bool = True,
    cams: bool = True,
    host: str = "127.0.0.1",
) -> int:
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
    if not cams:
        # 실물 카메라를 쓸 때다. mediamtx 가 카메라에서 직접 당겨오므로 송출할 것이
        # 없다 — 그 사실을 적어 둔다. 가짜 카메라가 안 떴는데 화면이 검으면 원인을
        # 여기서 찾을 수 있어야 한다.
        say("      cam     --no-cams: 가짜 RTSP 를 송출하지 않는다")
        say("              deploy/mediamtx.yml 의 source 가 실물 카메라를 가리켜야 한다")
    if not rec:
        # 조용히 빠지면 안 된다 — 녹화가 없으면 7일 링버퍼도, 이벤트 클립 추출(FN-REC-03)도
        # 없다. 화면은 정상으로 보이는데 클립만 안 나오는 상태를 만들지 않는다.
        say("      rec     --no-rec: 녹화 컴포넌트를 띄우지 않는다")
        say("              7일 녹화와 이벤트 클립 추출이 동작하지 않는다")
    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    try:
        for name, argv in dev_services(sources, rec=rec, cams=cams, host=host):
            exe = executable(argv[0])
            say(f"      {name:<7} {shell_repr(argv)}")
            processes.append((name, subprocess.Popen([exe, *argv[1:]], cwd=str(ROOT))))
    except TaskError:
        _stop_dev(processes)
        raise

    say()
    if host != "127.0.0.1":
        # 루프백 밖으로 나가는 것은 조용히 넘길 일이 아니다 — 같은 네트워크의 누구나
        # API 와 영상에 닿는다. 젯슨을 붙이려면 필요하지만, 그 사실은 보이게 적는다.
        say(f"[dev] 서버가 {host}:8000 에 열려 있다 — 같은 네트워크에서 접근 가능하다")
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


# ---------------------------------------------------------------------------
# relay — 실물 카메라를 mediamtx 로 밀어넣는다
# ---------------------------------------------------------------------------


def env_values() -> dict[str, str]:
    """`.env` 를 읽는다. **새 의존성을 넣지 않으려고 직접 판다.**

    compose · 서버 · REC 이 이미 이 파일 하나를 보므로 태스크도 같은 것을 본다
    (`.env.example` 머리말). 값을 두 곳에 적어 어긋나는 일이 없어야 한다.
    """
    path = ROOT / ".env"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # 값 뒤 주석(`REDIS_PORT=6380   # ...`)을 잘라낸다. 주소에는 `#` 이 없다.
        values[key.strip()] = value.split("#")[0].strip().strip('"').strip("'")
    return values


#: 규격 변환에 쓸 인코더 후보. 앞에 있는 것부터 쓴다.
#:
#: `h264_videotoolbox` 는 애플 실리콘의 하드웨어 인코더다 — 1440p30 을 1080p15 로 줄이는
#: 일을 CPU 거의 없이 해낸다. 없는 기계(젯슨·윈도우)에서는 libx264 로 떨어진다.
_RELAY_ENCODERS: tuple[str, ...] = ("h264_videotoolbox", "libx264")


def relay_encoder(ffmpeg: str) -> str:
    """이 기계에서 쓸 수 있는 인코더. 없으면 오류다 — 조용히 원본을 흘리지 않는다."""
    listed = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )  # fmt: skip
    for name in _RELAY_ENCODERS:
        if name in listed.stdout:
            return name
    raise TaskError(
        "H.264 인코더를 찾을 수 없다 (h264_videotoolbox · libx264)\n"
        "  --no-transcode 로 원본을 그대로 흘릴 수는 있지만, 카메라가 baseline 이 아니면\n"
        "  브라우저 WebRTC 가 그림을 만들지 못해 화면이 검게 남는다."
    )


def relay_argv(
    ffmpeg: str,
    source: str,
    path: str,
    base: str,
    *,
    encoder: str | None = None,
) -> list[str]:
    """카메라 스트림 하나를 `{base}/{path}` 로 재송출한다.

    ★ **`path` 를 받는 이유는 서브도 밀어야 하기 때문이다.** 엣지는 서브(640×360)만
      받아 추론하는데(`edge/config.yaml` 의 `rtsp_sub`), 서브가 없으면 감지가 통째로
      돌지 않는다. 메인만 밀던 시절에는 라이브 화면이 멀쩡해서 그 사실이 화면에
      드러나지 않았다 — 카메라는 잘 보이는데 박스만 안 그려진다.

    ★ **재인코딩하지 않는다**(`-c:v copy`). 카메라가 이미 H.264 를 뱉으므로 다시 굽는
      것은 낭비이고, 노트북에서는 그 비용이 송출을 굶겨 프레임을 떨어뜨린다
      (`cams_argv` 주석의 실측 405% 참고).

    ★ **오디오를 버린다**(`-an`). 이 시스템은 소리를 쓰지 않고(경고 방송은 서버가
      로컬 wav 로 낸다), 녹화 용량만 늘린다.

    ★ **입력도 출력도 TCP 다.** UDP 는 프레임이 조용히 깨져 들어와 원인 추적이
      어렵다 — 실물 카메라에서 특히 그렇다.
    """
    # ★ **지연을 만드는 것은 대부분 버퍼다.** ffmpeg 의 기본값은 처리량을 위해 입력을
    #   모아 두는데, 관제 화면은 지금 무슨 일이 일어나는지를 보는 것이므로 반대가 맞다.
    #
    #     nobuffer          입력을 모으지 않는다
    #     low_delay         디코더가 프레임을 쥐고 있지 않는다
    #     reorder_queue_size 0   RTSP 재정렬 버퍼(기본 500패킷)를 끈다. TCP 라 순서가
    #                            보장되므로 재정렬할 이유가 없다
    #     max_delay 0       디먹서 지연 상한
    #     muxdelay/muxpreload 0  출력 쪽도 모으지 않는다
    #
    #   오버레이 정합(`overlay_buffer_webrtc_ms`)은 **이 지연에 맞춰 잡는 값**이다.
    #   영상이 늦어지는데 버퍼를 그대로 두면 박스가 영상보다 먼저 그려진다(§5.4).
    head = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "warning",
        "-nostdin",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-max_delay", "0",
        "-reorder_queue_size", "0",
        "-rtsp_transport", "tcp",
        "-i", source,
        "-an",
    ]  # fmt: skip
    tail = [
        "-muxdelay", "0",
        "-muxpreload", "0",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        f"{base}/{path}",
    ]  # fmt: skip
    if encoder is None:
        return [*head, "-c:v", "copy", *tail]
    # ★ **baseline 이 협상 가능한 유일한 프로파일이다.** 브라우저 WebRTC 는 보통
    #   Constrained Baseline(`42e01f`) 하나만 협상한다. High 로 보내면 세션은 열리고
    #   RTP 도 흐르는데 디코더가 그림을 만들지 못해 화면이 검게 남고, 콘솔에는
    #   「프레임 미도착」만 찍힌다 — mediamtx 로그에도 오류가 없어 원인을 찾기 어렵다
    #   (`deploy/fake_cams.py` 가 같은 이유로 baseline 으로 굽는다).
    return [
        *head,
        "-vf", f"scale={MAIN_W}:{MAIN_H},fps={MAIN_FPS}",
        "-c:v", encoder,
        "-profile:v", "baseline",
        # VideoToolbox 의 실시간 모드. 인코더가 프레임을 모아 두지 않는다.
        # libx264 로 떨어졌을 때는 무시되므로 그쪽에는 zerolatency 를 따로 준다.
        *(["-realtime", "1"] if encoder == "h264_videotoolbox" else
          ["-tune", "zerolatency", "-preset", "veryfast"]),
        "-b:v", MAIN_BITRATE,
        "-maxrate", MAIN_BITRATE,
        "-bufsize", "5000k",
        # GOP 2초 — 클립·키프레임 추출 정밀도가 여기 걸려 있다(FN-REC-03).
        "-g", str(MAIN_FPS * 2),
        "-keyint_min", str(MAIN_FPS * 2),
        *tail,
    ]  # fmt: skip


#: 메인 스트림 규격(API명세서 §1.2). 카메라가 다른 값을 뱉으면 relay 가 여기 맞춘다.
MAIN_W, MAIN_H, MAIN_FPS = 1920, 1080, 15
MAIN_BITRATE = "2500k"


def task_relay(cams: str | None, *, transcode: bool = True) -> int:
    """실물 IP 카메라 → mediamtx (FN-DET-01 · API명세서 §1.2).

    **왜 mediamtx 가 직접 당겨오지 않는가.** 맥의 도커 컨테이너는 별도 VM 안에서 돌고
    바깥 통신이 호스트의 기본 경로로 나간다. 카메라가 기본 경로가 아닌 인터페이스
    (USB 랜)에만 있으면 컨테이너는 닿지 못한다 — 실측으로
    `dial tcp 192.168.0.60:554: connect: connection refused` 였다. 호스트에서 읽어
    밀어넣으면 그 문제가 사라진다.

    **주소는 `.env` 의 `CAM{N}_RTSP_MAIN` 에서 읽는다.** 계정·비밀번호가 들어가므로
    커밋되는 파일에 두지 않는다.
    """
    ffmpeg = executable("ffmpeg")
    encoder = relay_encoder(ffmpeg) if transcode else None
    env = env_values()
    base = env.get("RTSP_BASE", "rtsp://127.0.0.1:8554")
    wanted = [int(item) for item in cams.split(",")] if cams else [1, 2]

    # ★ **메인과 서브를 둘 다 민다.** 메인(1920×1080)은 서버가 라이브·녹화·클립에
    #   쓰고, 서브(640×360)는 엣지가 추론에 쓴다(`edge/config.yaml` 의 `rtsp_sub`).
    #   서브를 빠뜨리면 라이브 화면은 멀쩡한데 감지만 통째로 안 돈다.
    #
    #   서브는 **재인코딩하지 않는다**(`encoder=None`). baseline 으로 굽는 것은 브라우저
    #   WebRTC 협상 때문인데 서브를 보는 것은 엣지의 ffmpeg 디코더뿐이라 프로파일을
    #   가리지 않는다. 굽지 않으면 노트북 CPU 도 그만큼 덜 쓴다.
    targets: list[tuple[str, str, str | None]] = []
    for cam_id in wanted:
        main = env.get(f"CAM{cam_id}_RTSP_MAIN", "")
        if main:
            targets.append((f"cam{cam_id}/main", main, encoder))
        else:
            # 조용히 넘어가지 않는다 — 카메라가 안 뜬 이유가 설정에 있다는 것을 알려야
            # 한다. 화면이 검은 채로 원인을 찾게 두지 않는다(절대규칙 9).
            say(f"      cam{cam_id}    .env 의 CAM{cam_id}_RTSP_MAIN 이 비어 있다 - 건너뛴다")
        sub = env.get(f"CAM{cam_id}_RTSP_SUB", "")
        if sub:
            targets.append((f"cam{cam_id}/sub", sub, None))
        else:
            # 서브가 없으면 **감지가 통째로 없다.** 라이브 화면은 정상으로 보이므로
            # 여기서 말하지 않으면 「왜 박스가 안 그려지지」로 한참 헤매게 된다.
            say(f"      cam{cam_id}    .env 의 CAM{cam_id}_RTSP_SUB 가 비어 있다")
            say("              서브가 없으면 엣지가 받을 영상이 없어 감지가 돌지 않는다")
    if not targets:
        raise TaskError(
            ".env 에 CAM1_RTSP_MAIN 이 비어 있다 - 재송출할 카메라가 없다\n"
            "  실물 카메라 주소를 넣거나, 가짜 카메라를 쓰려면 uv run tasks.py cams 를 쓴다."
        )

    if encoder is None:
        say("[relay] 실물 카메라 -> mediamtx (원본 그대로)")
        say("      --no-transcode: 카메라가 baseline 이 아니면 화면이 검게 남는다")
    else:
        say(f"[relay] 실물 카메라 -> mediamtx ({MAIN_W}x{MAIN_H}@{MAIN_FPS} baseline · {encoder})")
    for path, source, enc in targets:
        note = "원본 그대로" if enc is None else f"{MAIN_W}x{MAIN_H}@{MAIN_FPS} baseline"
        say(f"      {path:<10} {_hide_secret(source)}  ->  {base}/{path}  ({note})")

    procs: list[tuple[str, subprocess.Popen[bytes]]] = []
    for path, source, enc in targets:
        argv = relay_argv(ffmpeg, source, path, base, encoder=enc)
        procs.append((path, subprocess.Popen([argv[0], *argv[1:]], cwd=str(ROOT))))
    say("      송출 중. Ctrl+C 로 종료한다.")

    # 카메라는 끊긴다 — 전원·네트워크·동시접속 제한. 끊긴 채로 두면 화면만 검어지므로
    # 다시 붙인다. 끊겼다는 사실은 매번 로그로 남긴다.
    try:
        while True:
            sources = {path: (source, enc) for path, source, enc in targets}
            for index, (path, proc) in enumerate(procs):
                if proc.poll() is None:
                    continue
                say(f"[relay] {path} 송출이 끊겼다 (코드 {proc.returncode}) - 3초 뒤 재시도")
                time.sleep(3.0)
                source, enc = sources[path]
                argv = relay_argv(ffmpeg, source, path, base, encoder=enc)
                procs[index] = (path, subprocess.Popen([argv[0], *argv[1:]], cwd=str(ROOT)))
            time.sleep(0.5)
    except KeyboardInterrupt:
        say()
        say("[relay] 종료 중...")
    finally:
        for _, proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for path, proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                say(f"      {path} 응답 없음 - 강제 종료")
                proc.kill()
    return 0


def _hide_secret(url: str) -> str:
    """로그에 비밀번호를 찍지 않는다. `rtsp://user:pw@host` 의 pw 만 가린다."""
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:****@", url)


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


def task_edge(cams: Sequence[int] | None, extra: Sequence[str]) -> int:
    """실물 엣지 러너. `sim` 과 달리 **영상에서 직접** 후보를 만든다.

    영상은 RTSP 로만 받으므로 먼저 카메라가 떠 있어야 한다:

        uv run tasks.py cams --source media/lego_sample_1.mp4

    호모그래피가 없으면 좌표를 낼 수 없어 프레임을 건너뛴다 — 설정 화면에서 4점을
    먼저 찍어야 한다(FN-CFG-01).
    """
    say("[edge] 엣지 러너 — 모델 추론 → /ws/edge")
    selected = [item for cam in cams or () for item in ("--cam", str(cam))]
    run(uv("python", "-m", "edge.main", *selected, *extra))
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
    dev = sub.add_parser("dev", help="docker-compose + 마이그레이션 + 실행 안내")
    dev.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="영상파일",
        help="카메라에 쓸 영상 파일 (cams --source 와 같다). 두 번 주면 카메라별로 다르게 쓴다",
    )
    dev.add_argument(
        "--host",
        default="127.0.0.1",
        metavar="주소",
        help="서버 바인드 주소. 젯슨 등 다른 기계에서 붙으려면 0.0.0.0 (기본: 루프백만)",
    )
    dev.add_argument(
        "--no-cams",
        dest="cams",
        action="store_false",
        help="가짜 RTSP 송출을 빼고 띄운다. 실물 카메라를 mediamtx 에 연결했을 때 쓴다",
    )
    dev.add_argument(
        "--no-rec",
        dest="rec",
        action="store_false",
        help="녹화 컴포넌트(REC)를 빼고 띄운다. 7일 녹화와 이벤트 클립 추출이 없어진다",
    )
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

    relay = sub.add_parser("relay", help="실물 IP 카메라 -> mediamtx 재송출 (재인코딩 없음)")
    relay.add_argument(
        "--cams",
        default=None,
        metavar="번호목록",
        help="재송출할 카메라 (기본 1,2). 주소는 .env 의 CAM{N}_RTSP_MAIN 에서 읽는다",
    )
    relay.add_argument(
        "--no-transcode",
        dest="transcode",
        action="store_false",
        help="원본을 그대로 흘린다. 카메라가 이미 1920x1080@15 baseline 일 때만 쓴다",
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

    edge = sub.add_parser("edge", help="실물 엣지 러너 (모델 추론 → /ws/edge)")
    # `--cam` 을 여기 선언한다. `extra`(REMAINDER)만 두면 argparse 가 서브커맨드 **뒤에
    # 바로 오는 옵션**을 상위 파서 것으로 보고 거부한다 — `sim --case` 와 같은 처리다.
    edge.add_argument(
        "--cam",
        type=int,
        action="append",
        help="이 카메라만 실행 (여러 번 지정 가능 · 기본: config.yaml 전부)",
    )
    edge.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="edge 에 그대로 넘길 인자 (--config · --log-level)",
    )

    return parser


def dispatch(args: argparse.Namespace) -> int:
    match args.task:
        case "verify":
            return task_verify()
        case "fmt":
            return task_fmt()
        case "dev":
            return task_dev(args.source, rec=args.rec, cams=args.cams, host=args.host)
        case "migrate":
            return task_migrate()
        case "types":
            return task_types(args.check)
        case "cams":
            return task_cams(args.source, args.cams, args.marker, args.timecode)
        case "cams-stop":
            return task_cams_stop(args.cams)
        case "relay":
            return task_relay(args.cams, transcode=args.transcode)
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
        case "edge":
            return task_edge(args.cam, args.extra)
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
