"""ref_height_px_at_m → ref_height (기능명세서 §6 갱신분)

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-01

기능명세서 §6 `cameras` 가 컬럼 이름과 JSON 키를 함께 바꿨다.

    ref_height_px_at_m  { "px_height": 0.42, "at_m": [...] }
    ref_height          { "height_px": 0.42, "at_m": [4.0, 7.0] }

**기준 높이는 스칼라가 아니다.** 높이 비율(FN-DET-10 조건 ①)을 거리로 정규화하려면
그 기준 높이를 **어느 지면 위치에서 쟀는지**가 필요하다. 같은 사람이라도 카메라에서
멀수록 화면상 픽셀 높이가 줄어들므로, 위치 없는 스칼라만으로는 다른 거리에서의 기대
높이를 구할 수 없다.

DB 는 이전부터 JSONB 로 두 값을 함께 들고 있었다(`0001`). 바뀐 것은 **이름**이다 —
컬럼 이름이 `_px_at_m` 이라 스칼라처럼 읽혔고, 실제로 `GET /cameras` 응답이 높이
하나만 내보내고 있었다. 이름과 API 를 §6 에 맞춘다.

기존 행의 값은 **키만 바꿔 옮긴다.** 지어내는 값이 없으므로 안전하다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("cameras", "ref_height_px_at_m", new_column_name="ref_height")
    # JSON 키 `px_height` → `height_px`. `at_m` 은 그대로 둔다.
    op.execute(
        sa.text(
            """
            UPDATE cameras
               SET ref_height = jsonb_build_object(
                       'height_px', ref_height -> 'px_height',
                       'at_m',      ref_height -> 'at_m')
             WHERE ref_height ? 'px_height'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE cameras
               SET ref_height = jsonb_build_object(
                       'px_height', ref_height -> 'height_px',
                       'at_m',      ref_height -> 'at_m')
             WHERE ref_height ? 'height_px'
            """
        )
    )
    op.alter_column("cameras", "ref_height", new_column_name="ref_height_px_at_m")
