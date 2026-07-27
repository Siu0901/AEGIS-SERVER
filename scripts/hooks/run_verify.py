"""Stop 훅 — `uv run tasks.py verify` 를 돌리고 실패하면 차단한다.

**보고 전용이 아니다.** 이전 버전은 실패해도 종료코드 0이었고, 그 위에
`bash 또는 scripts/verify.sh 없음` 이면 조용히 건너뛰기까지 했다. Windows 에는
make 도 verify.sh 실행 경로도 없었으므로 M0 내내 검증이 한 번도 돌지 않은 채
"통과"로 보고됐다. 그 두 구멍을 여기서 막는다.

종료코드 규약:

* 0  — verify 통과.
* 2  — verify 실패. Claude Code 는 Stop 훅의 **2번만 차단으로 해석**하므로,
       verify 의 원래 종료코드(보통 1)를 그대로 내보내면 차단되지 않는다.
       실제 종료코드는 메시지에 적어 남긴다.

`stop_hook_active` 가 참이면 이미 이 훅 때문에 한 번 되돌려진 상태다. 여기서 또
차단하면 무한 루프가 되므로 실패 사실을 크게 남기고 통과시킨다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = ROOT / "tasks.py"

#: Claude Code Stop 훅에서 차단을 뜻하는 종료코드.
BLOCK = 2


def report(message: str) -> None:
    """UTF-8 로 직접 써 넣는다. 한글 Windows 콘솔 코드페이지(cp949)를 우회하기 위해서다."""
    sys.stderr.buffer.write((message + "\n").encode("utf-8"))
    sys.stderr.buffer.flush()


def stop_hook_active() -> bool:
    # `utf-8-sig` — BOM 이 붙어 오는 경로가 있다(PowerShell 파이프). `utf-8` 로 읽으면
    # json 이 던지고, 그 예외를 삼키면 루프 가드가 조용히 꺼진다.
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
    except (ValueError, UnicodeDecodeError):
        return False
    return bool(payload.get("stop_hook_active", False))


def main() -> int:
    looping = stop_hook_active()

    uv = shutil.which("uv")
    if uv is None:
        report("[verify] uv 를 찾을 수 없다. 건너뛰지 않는다 — 설치해 PATH 에 넣어라.")
        return 0 if looping else BLOCK
    if not TASKS.exists():
        report(f"[verify] {TASKS} 가 없다. 건너뛰지 않는다.")
        return 0 if looping else BLOCK

    result = subprocess.run(
        [uv, "run", str(TASKS), "verify"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if result.returncode == 0:
        report("[verify] 통과")
        return 0

    # 실패했을 때만 전문을 남긴다. 원인 한 줄만 보여주면 다시 돌려보게 되고,
    # 그 왕복이 검증을 건너뛰고 싶어지는 이유가 된다.
    report(f"[verify] 실패 (tasks.py verify 종료코드 {result.returncode})")
    report(result.stdout.rstrip())
    if result.stderr.strip():
        report("--- stderr ---")
        report(result.stderr.rstrip())

    if looping:
        report("[verify] stop_hook_active — 무한 루프를 막기 위해 이번에는 차단하지 않는다.")
        return 0
    return BLOCK


if __name__ == "__main__":
    sys.exit(main())
