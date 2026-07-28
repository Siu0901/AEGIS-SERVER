"""`policies` 테이블에 기본값을 시드한다.

기본값의 원천은 `aegis_contracts.Policies` 이며, 그 값은 API명세서 §4.5 와 1:1이다.
코드에 임계값을 하드코딩하지 않기 위해 런타임은 항상 이 테이블을 읽는다
(CLAUDE.md 절대규칙 6).

    uv run python -m scripts.seed_policies            # 없는 키만 넣는다 (기본)
    uv run python -m scripts.seed_policies --force    # 기존 값을 기본값으로 되돌린다

기본이 upsert-if-absent 인 이유: 현장에서 조정한 임계값을 시드가 조용히
덮어쓰면 안 되기 때문이다.
"""

from __future__ import annotations

import argparse
import io
import sys

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col

from aegis_contracts import Policies
from server.infra.db import Policy, create_db_engine

# 파이프로 넘어갈 때 파이썬은 콘솔 코드페이지가 아니라 로케일 인코딩(한글 Windows 는
# cp949)을 쓴다. `tasks.py migrate` 가 이 모듈을 자식으로 돌리므로 출력이 파이프가 되고,
# 그러면 '—' 하나에 UnicodeEncodeError 로 죽어서 **시드가 끝났는데도 실패로 보고된다.**
# tasks.py · deploy/fake_cams.py 와 같은 처리를 여기에도 둔다.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def seed(*, force: bool) -> int:
    """시드를 적용하고 실제로 반영된 키 개수를 돌려준다.

    드라이버가 영향 행 수를 모르면 `rowcount` 가 `-1` 이다. 그대로 출력하면
    `-1/25 키 신규` 처럼 **사실이 아닌 숫자**가 나온다. 모를 때는 모른다고 하려고
    `-1` 을 그대로 올려보내고, 표시하는 쪽에서 문구를 바꾼다.
    """
    defaults = Policies().model_dump(mode="json")
    rows = [{"key": key, "value": value} for key, value in defaults.items()]

    statement = insert(Policy).values(rows)
    if force:
        statement = statement.on_conflict_do_update(
            index_elements=["key"],
            set_={"value": statement.excluded.value},
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=["key"])

    with create_db_engine().begin() as connection:
        result = connection.execute(statement)
        stale = connection.execute(
            delete(Policy).where(col(Policy.key).notin_(list(defaults))).returning(col(Policy.key))
        ).scalars()
        for key in sorted(stale):
            # 명세서에서 사라진 키다(예: v6 에서 경로별로 갈라진 `overlay_buffer_ms`).
            # 남겨두면 런타임이 읽을 때마다 "계약에 없는 키" 경고가 나고, 사람은 그것을
            # 소음으로 배우게 된다. 조용히 두지 말고 시드가 정리한다.
            print(f"  · 계약에 없는 키 삭제: {key}")

    return int(result.rowcount)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="policies 테이블 기본값 시드")
    parser.add_argument(
        "--force",
        action="store_true",
        help="이미 있는 키도 명세서 기본값으로 되돌린다",
    )
    args = parser.parse_args(argv)

    affected = seed(force=args.force)
    total = len(Policies.model_fields)
    mode = "덮어씀" if args.force else "신규"
    count = f"{affected}/{total} 키" if affected >= 0 else f"{total} 키 중 일부(개수 미보고)"
    print(f"policies 시드 완료 — {count} {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
