"""PreToolUse 훅 — 명세서 3종 보호.

`docs/` 는 SSOT다. 코드와 충돌하면 명세서가 맞고, 명세서를 고쳐야 한다면
**코드를 바꾸기 전에 사람에게 보고**해야 한다(CLAUDE.md 절대규칙 8).
그래서 아래 세 파일은 에이전트가 직접 수정하지 못하게 막는다.

**`docs/` 전체를 막지는 않는다.** `docs/INDEX.md` 는 작업마다 진척을 갱신해야 하므로
반드시 쓰기가 가능해야 한다.

차단은 종료코드 2 + stderr 로 알린다.
"""

from __future__ import annotations

import json
import sys
from pathlib import PurePosixPath

#: 사람 승인 없이는 못 고치는 파일들.
PROTECTED = frozenset(
    {
        "AEGIS_기능명세서.md",
        "AEGIS_API명세서.md",
        "AEGIS_구체화_계획안_최종.md",
    }
)


def is_protected(file_path: str) -> bool:
    if not file_path:
        return False
    parts = PurePosixPath(file_path.replace("\\", "/")).parts
    return "docs" in parts and parts[-1] in PROTECTED


def block(message: str) -> None:
    """UTF-8 로 직접 써 넣는다. 한글 Windows 콘솔 코드페이지(cp949)를 우회하기 위해서다."""
    sys.stderr.buffer.write((message + "\n").encode("utf-8"))
    sys.stderr.buffer.flush()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return 0  # 훅이 작업을 막는 쪽으로 실패하면 안 된다.

    file_path = str(payload.get("tool_input", {}).get("file_path", ""))
    if not is_protected(file_path):
        return 0

    name = PurePosixPath(file_path.replace("\\", "/")).name
    block(
        f"차단: {name} 은 SSOT 명세서다. 에이전트가 직접 고칠 수 없다.\n"
        f"명세서를 바꿔야 한다고 판단되면 코드를 건드리기 전에 사람에게 보고할 것.\n"
        f"(진척 갱신은 docs/INDEX.md 에 하면 된다 — 그쪽은 열려 있다.)"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
