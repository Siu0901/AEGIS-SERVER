"""§6 갱신 반영 — `events.alert_suppressed` · `events.clip_error` · `alert_sounds` 재정의

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-30

명세서가 세 가지를 확정했다.

1. **`events.alert_suppressed`** (bool) — 경고 일시중지 중에 확정되어 방송이 나가지
   않은 이벤트. §4.8 이 시정률에서 **전량 제외**하고 `suppressed` 로 따로 집계하라고
   정했다. 지표 이름이 「방송 후 시정률」이므로 방송이 없었던 건은 모집단이 아니다.
2. **`events.clip_error`** (text) — 클립 추출 실패 사유. 그때까지 `note` 앞에
   `[클립]` 접두사로 붙이던 임시 처리를 없앤다. 관리자 메모와 한 칸을 쓰면 사람이
   쓴 문장이 기계가 남긴 사유에 덮인다.
3. **`alert_sounds`** — 0005 가 만든 테이블이 §6 에 실렸고 컬럼이 확정됐다.
   `key`·`filename` → `violation_type`·`file_path` 로 바뀌고 `level`·`label` 이 붙는다.

**`alert_sounds` 는 새로 만들지 않고 옮긴다.** 이미 시드된 매핑을 지우면 현장에서
바꿔 둔 음원 지정이 사라진다(FN-CFG-03). `level`·`label` 의 백필값은
`scripts/seed_sounds.py` 의 기본값과 같으며, 그중 **`fall` 만 3**이다(§3 · FN-ALM-02).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 0005 가 시드한 다섯 키의 등급·표시 이름. 원천은 `scripts/seed_sounds.py` 이며
#: 여기서는 **이미 들어 있는 행을 옮기기 위한 백필값**으로만 쓴다.
#:
#: `fall` 만 3인 이유: §3 이 「**`fall` 은 항상 3**(연속 부저)」을 못박았다. 나머지는
#: 같은 「경고」 급인 2다 — 1(주의)은 위반이 아닌 이상 탐지(FN-AI-04)의 자리이고,
#: 이상 탐지는 애초에 경고 방송을 발동하지 않는다.
_BACKFILL: tuple[tuple[str, int, str], ...] = (
    ("no_helmet", 2, "안전모 미착용 안내"),
    ("zone_intrusion", 2, "금지구역 이탈 안내"),
    ("proximity", 2, "지게차 근접 경고"),
    ("fall", 3, "쓰러짐 구조 안내"),
    ("custom_notice", 2, "일반 안내 방송"),
)


def upgrade() -> None:
    op.add_column("events", sa.Column("clip_error", sa.Text(), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "alert_suppressed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.alter_column("alert_sounds", "key", new_column_name="violation_type")
    op.alter_column("alert_sounds", "filename", new_column_name="file_path")
    # `level` 은 값이 반드시 있어야 하므로 server_default 2 로 채운 뒤 아래에서
    # 유형별 값으로 고친다. `label` 은 nullable 이다 — 관리자가 새 음원을 등록하면서
    # 표시 이름을 아직 안 정했을 수 있고, `''` 는 "빈 이름을 지정했다"는 다른 주장이다.
    op.add_column(
        "alert_sounds",
        sa.Column("level", sa.Integer(), nullable=False, server_default=sa.text("2")),
    )
    op.add_column("alert_sounds", sa.Column("label", sa.Text(), nullable=True))

    sounds = sa.table(
        "alert_sounds",
        sa.column("violation_type", sa.Text()),
        sa.column("level", sa.Integer()),
        sa.column("label", sa.Text()),
    )
    for key, level, label in _BACKFILL:
        op.execute(
            sounds.update()
            .where(sounds.c.violation_type == op.inline_literal(key))
            .values(level=level, label=label)
        )


def downgrade() -> None:
    op.drop_column("alert_sounds", "label")
    op.drop_column("alert_sounds", "level")
    op.alter_column("alert_sounds", "file_path", new_column_name="filename")
    op.alter_column("alert_sounds", "violation_type", new_column_name="key")
    op.drop_column("events", "alert_suppressed")
    op.drop_column("events", "clip_error")
