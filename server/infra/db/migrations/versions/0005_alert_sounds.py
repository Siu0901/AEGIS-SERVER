"""경고 음원 매핑 테이블 — FN-ALM-01 · FN-CFG-03

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-30

⚠ **기능명세서 §6 에 없는 테이블이다.** 명세서는 FN-CFG-03(경고 음원 매핑 · P0)과
§4.3 "위반 유형에 **사전 매핑된** 음원 파일"을 요구하면서 그 매핑을 둘 자리를 정의하지
않았다. 코드에 파일명을 박으면 절대규칙 6(하드코딩 금지)이 깨지고, 설정 화면(FN-CFG-03 ·
M6)에서 바꿀 수도 없다. `docs/INDEX.md` 「명세서 확인 필요」에 올려 두었다.

행은 여기서 넣지 않는다. 기본값의 원천은 `scripts/seed_sounds.py` 이며, 같은 스크립트가
`assets/audio/` 에 파일이 없으면 **무음 wav 를 만들어 경로를 맞춘다** — 실제 녹음이
들어오기 전에도 경로·매핑·재생 경로 전체가 동작해야 하기 때문이다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_sounds",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_table("alert_sounds")
