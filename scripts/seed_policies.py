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
import sys

from sqlalchemy.dialects.postgresql import insert

from aegis_contracts import Policies
from server.infra.db import Policy, create_db_engine


def seed(*, force: bool) -> int:
    """시드를 적용하고 실제로 반영된 키 개수를 돌려준다."""
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

    return int(result.rowcount or 0)


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
    print(f"policies 시드 완료 — {affected}/{total} 키 {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
