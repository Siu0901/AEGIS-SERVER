"""`alert_sounds` 테이블을 시드하고, 없는 wav 를 무음으로 만들어 둔다. FN-ALM-01

    uv run python -m scripts.seed_sounds            # 없는 키만 넣는다 (기본)
    uv run python -m scripts.seed_sounds --force    # 기존 매핑을 기본값으로 되돌린다

기능명세서 §4.3 이 정한 음원은 넷이다.

| 키 | 파일 | 안내 문구 |
|---|---|---|
| `no_helmet` | `no_helmet.wav` | "안전모를 착용해 주십시오" |
| `zone_intrusion` | `zone_intrusion.wav` | "위험구역입니다. 즉시 이탈하십시오" |
| `proximity` | `proximity.wav` | "중장비 작업 반경입니다. 물러나 주십시오" |
| `fall` | `fall.wav` | 구조 안내 (**시정 유도 문구가 아니다** — §4.1) |

`custom_notice` 는 수동 방송(FN-ALM-04 · §4.5 `sound`)의 예시 키다.

**무음 wav 를 만드는 이유.** 실제 녹음은 사람이 나중에 넣는다. 그때까지 파일이 없으면
경로·매핑·재생 백엔드가 전부 미검증으로 남고, 녹음을 넣는 순간 처음 돌려보게 된다.
길이가 있는 무음을 깔아 두면 **재생 경로 전체가 지금 동작하고**, 파일을 덮어쓰는 것만
남는다. 이미 있는 파일은 건드리지 않는다 — 녹음을 무음으로 덮어쓰는 사고를 막는다.

`wave` 는 표준 라이브러리다. 음원 하나를 만들자고 의존성을 늘리지 않는다.
"""

from __future__ import annotations

import argparse
import io
import sys
import wave
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from server.infra.db import create_db_engine
from server.infra.db.models import AlertSound

if isinstance(sys.stdout, io.TextIOWrapper):
    # `tasks.py migrate` 가 자식으로 돌리면 출력이 파이프가 되고, 그때 한글 Windows 는
    # cp949 를 쓴다 — '—' 하나에 죽어 **시드가 끝났는데 실패로 보고된다.**
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 음원 파일이 사는 곳. `assets/` 는 사람이 관리하는 자산 디렉토리다(CLAUDE.md 디렉토리 표).
AUDIO_DIR = Path(__file__).resolve().parent.parent / "assets" / "audio"

#: 기본 매핑. 기능명세서 §4.3 「음원 예」 그대로다.
DEFAULT_SOUNDS: dict[str, str] = {
    "no_helmet": "no_helmet.wav",
    "zone_intrusion": "zone_intrusion.wav",
    "proximity": "proximity.wav",
    "fall": "fall.wav",
    "custom_notice": "custom_notice.wav",
}

#: 자리를 채우는 무음의 길이(초). 실제 안내 음성이 대략 이 정도다.
PLACEHOLDER_SECONDS = 2.0

#: 무음 wav 규격. 16kHz · 16bit · 모노 — 안내 음성에 충분하고 어느 재생기나 연다.
_SAMPLE_RATE = 16_000
_SAMPLE_WIDTH = 2
_CHANNELS = 1


def ensure_files(directory: Path = AUDIO_DIR) -> list[str]:
    """없는 음원 파일을 무음으로 만든다. **있는 파일은 덮어쓰지 않는다.**"""
    directory.mkdir(parents=True, exist_ok=True)
    made: list[str] = []
    for filename in sorted(set(DEFAULT_SOUNDS.values())):
        path = directory / filename
        if path.exists():
            continue
        with wave.open(str(path), "wb") as out:
            out.setnchannels(_CHANNELS)
            out.setsampwidth(_SAMPLE_WIDTH)
            out.setframerate(_SAMPLE_RATE)
            out.writeframes(b"\x00" * int(_SAMPLE_RATE * PLACEHOLDER_SECONDS) * _SAMPLE_WIDTH)
        made.append(filename)
    return made


def seed(*, force: bool) -> int:
    """매핑을 시드하고 반영된 행 수를 돌려준다(드라이버가 모르면 `-1`)."""
    rows = [
        {"key": key, "filename": filename, "active": True}
        for key, filename in DEFAULT_SOUNDS.items()
    ]
    statement = insert(AlertSound).values(rows)
    if force:
        statement = statement.on_conflict_do_update(
            index_elements=["key"],
            set_={"filename": statement.excluded.filename, "active": statement.excluded.active},
        )
    else:
        # 현장에서 바꾼 매핑을 시드가 조용히 되돌리지 않는다(FN-CFG-03).
        statement = statement.on_conflict_do_nothing(index_elements=["key"])

    with create_db_engine().begin() as connection:
        return int(connection.execute(statement).rowcount)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="alert_sounds 시드 + 무음 wav 생성")
    parser.add_argument("--force", action="store_true", help="이미 있는 키도 기본값으로 되돌린다")
    parser.add_argument(
        "--files-only",
        action="store_true",
        help="DB 를 건드리지 않고 없는 wav 만 만든다 (DB 없이 재생 경로만 볼 때)",
    )
    args = parser.parse_args(argv)

    made = ensure_files()
    for filename in made:
        print(f"  · 무음 wav 생성: assets/audio/{filename}  (실제 녹음으로 덮어쓸 것)")
    if not made:
        print("  · 음원 파일은 모두 있다")

    if args.files_only:
        return 0

    affected = seed(force=args.force)
    mode = "덮어씀" if args.force else "신규"
    count = (
        f"{affected}/{len(DEFAULT_SOUNDS)} 키"
        if affected >= 0
        else f"{len(DEFAULT_SOUNDS)} 키 중 일부(개수 미보고)"
    )
    print(f"alert_sounds 시드 완료 — {count} {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
