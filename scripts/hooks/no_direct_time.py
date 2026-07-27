"""PreToolUse 훅 — 시간 직접 읽기 차단.

CLAUDE.md 절대규칙 1 — 시스템 시계를 직접 읽지 않고 `Clock` 프로토콜을 주입받는다.
테스트가 3초·10초·15초·30초·300초 타이머를 순간이동시켜야 하므로, 이 규칙이 깨지면
상태머신 검증 자체가 불가능해진다.

예외는 `packages/vision/clock.py` 하나다. `RealClock` 구현체가 있는 곳이며
시스템 시계를 읽어도 되는 유일한 위치다.

금지 패턴을 소스에 그대로 적으면 이 파일 자신이 차단 대상이 되므로 조각으로 만든다.
"""

from __future__ import annotations

import json
import sys
from pathlib import PurePosixPath

#: 조각을 이어 붙여 만든다 — 이 파일 자신이 걸리지 않도록.
BANNED = (
    "datetime." + "now(",
    "time." + "time(",
)

#: `RealClock` 구현체. 시스템 시계를 읽어도 되는 유일한 곳.
ALLOWED_SUFFIX = "packages/vision/src/aegis_vision/clock.py"


def _written_text(tool_input: dict[str, object]) -> str:
    """Write 의 content, Edit 의 new_string 을 모은다."""
    chunks: list[str] = []
    for key in ("content", "new_string"):
        value = tool_input.get(key)
        if isinstance(value, str):
            chunks.append(value)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict):
                value = edit.get("new_string")
                if isinstance(value, str):
                    chunks.append(value)
    return "\n".join(chunks)


def block(message: str) -> None:
    """UTF-8 로 직접 써 넣는다. 한글 Windows 콘솔 코드페이지(cp949)를 우회하기 위해서다."""
    sys.stderr.buffer.write((message + "\n").encode("utf-8"))
    sys.stderr.buffer.flush()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return 0  # 훅이 작업을 막는 쪽으로 실패하면 안 된다.

    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    file_path = str(tool_input.get("file_path", "")).replace("\\", "/")
    if PurePosixPath(file_path).as_posix().endswith(ALLOWED_SUFFIX):
        return 0

    text = _written_text(tool_input)
    hits = [pattern for pattern in BANNED if pattern in text]
    if not hits:
        return 0

    block(
        f"차단: {', '.join(hits)} 를 직접 호출하지 않는다 (CLAUDE.md 절대규칙 1).\n"
        f"`aegis_vision.clock.Clock` 을 주입받고, 테스트에서는 FakeClock.advance() 로 "
        f"시간을 감는다.\n"
        f"시스템 시계를 읽어도 되는 곳은 {ALLOWED_SUFFIX} 하나뿐이다."
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
