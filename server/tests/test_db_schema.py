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

#: ⚠ **§6 에 없는데 서버가 만든 테이블.** 명세서가 요구하는 기능(FN-CFG-03 경고 음원
#: 매핑 · P0)을 담을 자리가 데이터 모델에 정의되지 않아 추가한 것들이다.
#:
#: 이 집합을 비워 두는 것이 목표다. 명세서 §6 에 반영되면 위 `SPEC_TABLES` 로 옮긴다.
#: 여기 적지 않고 `SPEC_TABLES` 에 슬쩍 넣으면 "명세서에 있다"는 거짓이 된다
#: (`docs/INDEX.md` 「명세서 확인 필요」 참조).
EXTRA_TABLES = {
    "alert_sounds",
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
    "last_alerted_at",
    "resolved_at",
    "resolution_sec",
    "alert_count",
    "lost_at",
    "expired_at",
    "dropped_at",
    "reassoc_count",
    "prev_track_ids",
    "min_distance_m",
    "depth_verified",
    "posture",
    "stillness_s",
    "helmet_conf",
    "height_ratio",
    "nearby_snapshot",
    "similar_incidents",
    "clip_path",
    "keyframe_paths",
    "clip_status",
    "embedding",
    "llm_analysis",
    "regulation_refs",
    "is_false_positive",
    "note",
}

#: 기능명세서 §6 `zones` 컬럼 전량.
SPEC_ZONE_COLUMNS = {"zone_id", "cam_id", "name", "polygon_m", "buffer_m", "active"}


def test_all_spec_tables_exist() -> None:
    assert set(SQLModel.metadata.tables) == SPEC_TABLES | EXTRA_TABLES


def test_events_columns_match_spec_exactly() -> None:
    columns = set(SQLModel.metadata.tables["events"].columns.keys())
    assert columns == SPEC_EVENT_COLUMNS


def test_zones_columns_match_spec_exactly() -> None:
    columns = set(SQLModel.metadata.tables["zones"].columns.keys())
    assert columns == SPEC_ZONE_COLUMNS


def test_height_ratio_is_real() -> None:
    """§6이 이 컬럼만 `real` 로 명시한다. 마이그레이션과 타입이 어긋나면 안 된다."""
    kind = SQLModel.metadata.tables["events"].columns["height_ratio"].type
    assert type(kind).__name__ == "REAL"


@pytest.mark.parametrize(
    "column",
    ["keyframe_paths", "nearby_snapshot", "similar_incidents", "regulation_refs", "prev_track_ids"],
)
def test_list_valued_columns_are_jsonb(column: str) -> None:
    """복수 값을 담는 컬럼은 text 가 아니라 jsonb 다.

    `keyframe_paths` 는 키프레임 2~3장을 담고 `GET /events/{id}` 가 `keyframe_urls`
    **배열**로 반환하므로 text 로는 성립하지 않는다.
    """
    kind = SQLModel.metadata.tables["events"].columns[column].type
    assert type(kind).__name__ == "JSONB"


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
        "last_alerted_at",
        "resolved_at",
        "lost_at",
        "expired_at",
        "dropped_at",
    )
    for name in stamped:
        assert events.columns[name].type.timezone is True, name  # type: ignore[attr-defined]


def test_models_module_exports_every_table() -> None:
    exported = {name for name in db_models.__all__ if name != "EMBEDDING_DIM"}
    assert len(exported) == len(SPEC_TABLES) + len(EXTRA_TABLES)
