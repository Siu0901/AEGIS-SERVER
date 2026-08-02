"""normal_pool.embedding_model 추가 (기능명세서 §6 갱신분 · FN-AI-04)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-02

벡터는 **모델마다 다른 공간에 산다.** 모델을 교체하면 이전 벡터가 그대로 남아 새 모델의
초기 샘플이 전부 「평소와 다름」으로 잡힌다 — 실측으로 4회 연속 오탐이 났다(k=5 이므로
풀이 새 벡터로 채워질 때까지 이어진다).

지금까지는 사람이 `DELETE FROM normal_pool` 로 비웠다. 그건 **아무 데도 적혀 있지 않은
운영 절차**라 모델을 바꾼 사람이 그 사실을 모르면 이상 탐지가 며칠간 조용히 망가진다.
행이 자기 모델을 들고 있으면 서버가 스스로 가른다.

기존 행 처리 — **비운다.** 어느 모델이 만든 벡터인지 알 방법이 없고, 모르는 채로 이름을
붙이면 그 거짓말이 그대로 판정 근거가 된다. 정상 풀은 몇 주기면 다시 차므로(기본 5분
간격) 버리는 비용이 오판보다 싸다. `anomalies` 는 지우지 않는다 — 그건 관측 기록이다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 어느 모델의 벡터인지 모르는 행을 남기면 그 행이 곧 오판의 근거가 된다.
    op.execute("DELETE FROM normal_pool")
    op.add_column("normal_pool", sa.Column("embedding_model", sa.String(), nullable=False))
    op.create_index("ix_normal_pool_embedding_model", "normal_pool", ["embedding_model"])


def downgrade() -> None:
    op.drop_index("ix_normal_pool_embedding_model", table_name="normal_pool")
    op.drop_column("normal_pool", "embedding_model")
