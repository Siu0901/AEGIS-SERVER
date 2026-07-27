"""DB 스키마가 기능명세서 §6 과 일치하는지 검증한다. DB 연결은 필요 없다."""

from __future__ import annotations

import pytest
from sqlmodel import SQLModel

from server.infra.db import EMBEDDING_DIM
from server.infra.db import models as db_models

#: 기능명세서 §6 에 정의된 테이블 전량.
SPEC_TABLES = {
    "events",
    "zones",
    "cameras",
    "vehicle_classes",
    "policies",
    "normal_pool",
    "anomalies",
}

#: 기능명세서 §6 `events` 컬럼 전량.
SPEC_EVENT_COLUMNS = {
    "event_id",
    "cam_id",
    "track_id",
    "violation_type",
    "zone_id",
    "status",
    "detected_at",
    "confirmed_at",
    "alerted_at",
    "resolved_at",
    "resolution_sec",
    "alert_count",
    "lost_at",
    "expired_at",
    "reassoc_count",
    "prev_track_ids",
    "min_distance_m",
    "depth_verified",
    "posture",
    "stillness_s",
    "helmet_conf",
    "clip_path",
    "keyframe_paths",
    "clip_status",
    "embedding",
    "llm_analysis",
    "regulation_refs",
    "is_false_positive",
}


def test_all_spec_tables_exist() -> None:
    assert set(SQLModel.metadata.tables) == SPEC_TABLES


def test_events_columns_match_spec_exactly() -> None:
    columns = set(SQLModel.metadata.tables["events"].columns.keys())
    assert columns == SPEC_EVENT_COLUMNS


@pytest.mark.parametrize("table", ["events", "normal_pool"])
def test_embedding_is_halfvec_3072(table: str) -> None:
    """FN-AI-01 — Gemini Embedding 2, pgvector `halfvec(3072)`."""
    column = SQLModel.metadata.tables[table].columns["embedding"]
    assert type(column.type).__name__ == "HALFVEC"
    assert column.type.dim == EMBEDDING_DIM  # type: ignore[attr-defined]


def test_timestamps_are_timezone_aware() -> None:
    """API명세서 §1.2 — 저장 UTC. naive timestamp 는 클립 구간을 어긋나게 한다."""
    events = SQLModel.metadata.tables["events"]
    stamped = (
        "detected_at",
        "confirmed_at",
        "alerted_at",
        "resolved_at",
        "lost_at",
        "expired_at",
    )
    for name in stamped:
        assert events.columns[name].type.timezone is True, name  # type: ignore[attr-defined]


def test_models_module_exports_every_table() -> None:
    exported = {name for name in db_models.__all__ if name != "EMBEDDING_DIM"}
    assert len(exported) == len(SPEC_TABLES)
