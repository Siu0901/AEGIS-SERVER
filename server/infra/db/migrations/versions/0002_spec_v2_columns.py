"""명세서 갱신분 반영 — zones.name, events 확정 시점 근거 컬럼, keyframe_paths 배열화

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-27

기능명세서 §6 갱신분:
- `zones.name` — `GET /zones` 가 표시 이름을 반환하는데 저장할 자리가 없었다
- `events.height_ratio` — 쓰러짐 판정 근거 ① (확정 시점 값)
- `events.nearby_snapshot` — 확정 시점 주변 차량 목록
- `events.similar_incidents` — 확정 시 1회 계산해 저장
- `events.keyframe_paths` — text → jsonb (키프레임은 2~3장이라 배열이다)

`keyframe_paths` 는 기존 값이 있으면 단일 원소 배열로 감싸 보존한다. 비어 있으면 `[]`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("zones", sa.Column("name", sa.Text(), nullable=False, server_default=""))

    op.add_column("events", sa.Column("height_ratio", sa.REAL(), nullable=True))
    op.add_column(
        "events",
        sa.Column("nearby_snapshot", JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "events",
        sa.Column("similar_incidents", JSONB(), nullable=False, server_default="[]"),
    )

    # text → jsonb. NULL·빈 문자열은 [], 그 외 기존 경로는 원소 하나짜리 배열로 감싼다.
    op.execute(
        """
        ALTER TABLE events
        ALTER COLUMN keyframe_paths TYPE jsonb
        USING CASE
            WHEN keyframe_paths IS NULL OR keyframe_paths = '' THEN '[]'::jsonb
            ELSE jsonb_build_array(keyframe_paths)
        END
        """
    )
    op.alter_column(
        "events",
        "keyframe_paths",
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )


def downgrade() -> None:
    # 배열의 첫 원소만 남는다. 2장 이상이면 되돌릴 때 유실되므로 주의한다.
    op.alter_column("events", "keyframe_paths", nullable=True, server_default=None)
    op.execute(
        """
        ALTER TABLE events
        ALTER COLUMN keyframe_paths TYPE text
        USING CASE
            WHEN jsonb_array_length(keyframe_paths) = 0 THEN NULL
            ELSE keyframe_paths ->> 0
        END
        """
    )

    op.drop_column("events", "similar_incidents")
    op.drop_column("events", "nearby_snapshot")
    op.drop_column("events", "height_ratio")
    op.drop_column("zones", "name")
