"""초기 스키마 — 기능명세서 §6 데이터 모델 전량

Revision ID: 0001
Revises:
Create Date: 2026-07-27

`CREATE EXTENSION IF NOT EXISTS vector` 를 먼저 실행한다. `events.embedding` 과
`normal_pool.embedding` 이 pgvector `halfvec(3072)` 이기 때문이다(FN-AI-01).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 3072


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "events",
        sa.Column("event_id", sa.Text(), nullable=False, comment="EV-YYYYMMDD-NNNN"),
        sa.Column("cam_id", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("violation_type", sa.Text(), nullable=False),
        sa.Column("zone_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_sec", sa.Integer(), nullable=True),
        sa.Column("alert_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lost_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reassoc_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prev_track_ids", JSONB(), nullable=False, server_default="[]"),
        sa.Column("min_distance_m", sa.Float(), nullable=True),
        sa.Column("depth_verified", sa.Boolean(), nullable=True),
        sa.Column("posture", sa.Text(), nullable=True),
        sa.Column("stillness_s", sa.Float(), nullable=True),
        sa.Column("helmet_conf", sa.Float(), nullable=True),
        sa.Column("clip_path", sa.Text(), nullable=True),
        sa.Column("keyframe_paths", sa.Text(), nullable=True),
        sa.Column("clip_status", sa.Text(), nullable=True),
        sa.Column("embedding", HALFVEC(EMBEDDING_DIM), nullable=True),
        sa.Column("llm_analysis", sa.Text(), nullable=True),
        sa.Column("regulation_refs", JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_false_positive", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_events_cam_id", "events", ["cam_id"])
    op.create_index("ix_events_track_id", "events", ["track_id"])
    op.create_index("ix_events_violation_type", "events", ["violation_type"])
    op.create_index("ix_events_zone_id", "events", ["zone_id"])
    op.create_index("ix_events_status", "events", ["status"])
    # 지표 집계(§4.8)와 `GET /events` 기간 필터가 항상 이 순서로 훑는다.
    op.create_index("ix_events_detected_at", "events", ["detected_at"])

    op.create_table(
        "zones",
        sa.Column("zone_id", sa.Text(), nullable=False),
        sa.Column("cam_id", sa.Integer(), nullable=False),
        sa.Column("polygon_m", JSONB(), nullable=False, server_default="[]"),
        sa.Column("buffer_m", sa.Float(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("zone_id"),
    )
    op.create_index("ix_zones_cam_id", "zones", ["cam_id"])

    op.create_table(
        "cameras",
        sa.Column("cam_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("rtsp_main", sa.Text(), nullable=False),
        sa.Column("rtsp_sub", sa.Text(), nullable=False),
        sa.Column("homography", JSONB(), nullable=True),
        sa.Column("ref_height_px_at_m", JSONB(), nullable=True),
        sa.Column("calibrated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("cam_id"),
    )

    op.create_table(
        "vehicle_classes",
        sa.Column("class_name", sa.Text(), nullable=False),
        sa.Column("danger_radius_m", sa.Float(), nullable=False, server_default="3.0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("class_name"),
    )

    op.create_table(
        "policies",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "normal_pool",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cam_id", sa.Integer(), nullable=False),
        sa.Column("time_bucket", sa.Text(), nullable=False),
        sa.Column("embedding", HALFVEC(EMBEDDING_DIM), nullable=True),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_normal_pool_cam_id", "normal_pool", ["cam_id"])
    op.create_index("ix_normal_pool_time_bucket", "normal_pool", ["time_bucket"])

    op.create_table(
        "anomalies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cam_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("keyframe_path", sa.Text(), nullable=True),
        sa.Column("llm_note", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_anomalies_cam_id", "anomalies", ["cam_id"])


def downgrade() -> None:
    op.drop_table("anomalies")
    op.drop_table("normal_pool")
    op.drop_table("policies")
    op.drop_table("vehicle_classes")
    op.drop_table("cameras")
    op.drop_table("zones")
    op.drop_table("events")
    # `vector` 확장은 다른 스키마가 쓰고 있을 수 있으므로 되돌리지 않는다.
