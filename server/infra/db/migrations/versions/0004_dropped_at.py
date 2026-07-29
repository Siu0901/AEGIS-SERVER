"""명세서 갱신분 반영 — events.dropped_at

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-30

기능명세서 §6 `events` 갱신분:

- `dropped_at` (timestamptz) — 확정 전(`candidate`) 상태에서 조건이 사라져 소멸한 시각.

세 종결 상태(`resolved` · `expired` · `dropped`) 중 `dropped` 만 시각 컬럼이 없어서
§4.1 `timeline` 에 나오지 않았고, `dropped / (dropped + 확정)`(= `confirm_duration_s`
튜닝의 근거) 진단도 `detected_at` 으로만 기간을 끊을 수 있었다. 후보가 언제 시작했는지와
언제 사라졌는지는 다른 사실이므로 그 둘로는 소멸까지의 시간을 알 수 없다.

기존 행은 채우지 않는다. 지나간 `dropped` 이벤트의 소멸 시각은 어디에도 기록되어
있지 않으므로, `detected_at` 으로 채우면 **관측하지 않은 값을 지어내는 것**이 된다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("dropped_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("events", "dropped_at")
