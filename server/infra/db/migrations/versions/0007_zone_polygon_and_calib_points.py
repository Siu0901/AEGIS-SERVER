"""명세서 갱신분 반영 — zones.polygon · cameras.calib_points · cameras.reproj_error_m

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-31

API명세서 §4.5 갱신분:

- `zones.polygon` (jsonb) — 사용자가 화면에서 그린 **정규화 픽셀** 폴리곤.
- `cameras.calib_points` (jsonb) — 캘리브레이션에 쓴 대응점 원본.
- `cameras.reproj_error_m` (float) — 재투영 오차 RMS.

**픽셀 폴리곤이 원본이다.** 판정은 `polygon_m` 으로 하지만 설정 화면이 구역을 다시
그리려면 픽셀이 필요하고, 매번 역변환하면 캘리브레이션이 바뀔 때마다 화면의 도형이
미세하게 움직인다. 반대로 **캘리브레이션이 갱신되면 `polygon` 을 기준으로 `polygon_m`
을 다시 계산**한다 — 사용자가 그린 위치가 진실이기 때문이다.

기존 구역의 `polygon` 은 **역변환해서 채운다.** 여기서는 빈 배열로 두고
`scripts/seed_zones.py` 가 픽셀 폴리곤으로 다시 심는다 — 마이그레이션 안에서
호모그래피를 풀면 DDL 이 `packages/vision` 에 의존하게 되고, 캘리브레이션이 없는
카메라에서는 채울 값 자체가 없다.

`calib_points` · `reproj_error_m` 은 기존 행을 채우지 않는다. 지나간 캘리브레이션의
대응점은 어디에도 남아 있지 않으므로 지어내면 화면이 **찍은 적 없는 점**을 보여준다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "zones",
        sa.Column(
            "polygon",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "cameras",
        sa.Column("calib_points", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("cameras", sa.Column("reproj_error_m", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("cameras", "reproj_error_m")
    op.drop_column("cameras", "calib_points")
    op.drop_column("zones", "polygon")
