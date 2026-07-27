"""Stop 훅 — `make verify` 를 돌리고 결과를 보고한다.

**지금은 실패해도 종료코드 0이다(보고 전용).** 차단 모드 전환은 M2에서 테스트가
쌓인 뒤에 한다. 초기부터 차단하면 에이전트가 재시도 루프에 빠진다.

차단으로 바꿀 때는 `_BLOCKING = True` 로 두면 된다 — 실패 시 종료코드 2로 나간다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

#: M2 에서 True 로 바꾼다.
_BLOCKING = False

VERIFY = Path("scripts/verify.sh")


def report(message: str) -> None:
    """UTF-8 로 직접 써 넣는다. 한글 Windows 콘솔 코드페이지(cp949)를 우회하기 위해서다."""
    sys.stdout.buffer.write((message + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def main() -> int:
    bash = shutil.which("bash")
    if bash is None or not VERIFY.exists():
        report("[verify] 건너뜀 — bash 또는 scripts/verify.sh 없음")
        return 0

    result = subprocess.run(
        [bash, str(VERIFY)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    # 단계 표시줄과 마지막 요약만 남긴다. 전체 로그는 `make verify` 로 직접 본다.
    summary = [line for line in lines if line.lstrip().startswith(("✔", "✘", "—", "·"))]
    report("[verify] " + ("통과" if result.returncode == 0 else "실패"))
    for line in summary[-14:]:
        report("  " + line.strip())
    if result.returncode != 0 and result.stderr.strip():
        report("  stderr: " + result.stderr.strip().splitlines()[-1])

    if _BLOCKING and result.returncode != 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
