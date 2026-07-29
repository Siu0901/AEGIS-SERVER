"""명세서 갱신분 반영 — events.last_alerted_at, events.note

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-30

기능명세서 §6 `events` 갱신분:

- `last_alerted_at` (timestamptz) — **최근** 경고 시각. `alerted_at`(최초)은 변경하지
  않는다. `resolution_sec` 이 `alerted_at → resolved_at` 으로 정의되어 있어(§4.1),
  재경고마다 `alerted_at` 을 덮으면 재경고가 많을수록 소요 시간이 짧아져
  **시정률이 부풀려진다**(API명세서 §5.2).
- `note` (text) — 관리자 메모. `PATCH /events/{id}` 의 `note`(§4.1)를 저장할 자리다.
  없으면 오탐 판단의 근거가 다시 조회했을 때 사라진다.

기존 행의 `last_alerted_at` 은 `alerted_at` 으로 채운다. 정확한 값은 `alert_count = 1`
인 행뿐이지만, 채우지 않으면 재시작 뒤 쿨다운 기준이 통째로 비어 **재경고가 즉시
나가는 쪽**으로 틀린다. 최초 시각으로 채우면 늦게 나가는 쪽으로만 틀린다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("events", sa.Column("note", sa.Text(), nullable=True))
    op.execute("UPDATE events SET last_alerted_at = alerted_at WHERE alerted_at IS NOT NULL")


def downgrade() -> None:
    # `note` 를 지우면 관리자가 남긴 정정 사유가 사라진다. 되돌리기 전에 백업할 것.
    op.drop_column("events", "note")
    op.drop_column("events", "last_alerted_at")
