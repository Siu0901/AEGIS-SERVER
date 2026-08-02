"""`vehicle_classes` 테이블에 위험 반경 기본 행을 시드한다. FN-CFG-05

    uv run python -m scripts.seed_vehicles            # 없으면 넣는다 (기본)
    uv run python -m scripts.seed_vehicles --force    # 기존 값을 기본값으로 되돌린다

★ **행은 `vehicle` 하나뿐이다.** 감지 클래스가 `person`·`vehicle` 2종 고정이므로
지게차·트럭·파렛트트럭을 나누고 싶어도 감지 모델이 구분하지 못한다(기능명세서 부록 A-1).

★ **이 시드가 없으면 FN-CFG-05 가 도달 불가가 된다.** API 에는 `GET` 과 `PATCH` 만 있고
생성 경로가 없다 — 행이 없으면 설정 화면의 위험 반경 표가 비어 있고 `PATCH` 는 404 를
반환한다. 그러면 현장에서 값을 조정할 수단이 사라지고 코드 폴백값(`Policies.
vehicle_danger_radius_m`)으로 고정되어, 「임계값을 코드에 하드코딩하지 않는다」는
절대규칙 6 의 취지에 어긋난다.

위험 반경은 **장비를 따라다니는 동적 영역**이고, 즉시 경고 기준인 `proximity_threshold_m`
(기본 2.0m)와 2단계로 동작한다 — 둘은 다른 값이다(API명세서 §4.5).
"""

from __future__ import annotations

import argparse
import io
import sys

from sqlalchemy.dialects.postgresql import insert

from server.infra.db import VehicleClassRow, create_db_engine

# `tasks.py migrate` 가 이 모듈을 자식으로 돌리므로 출력이 파이프가 된다.
# 한글 Windows 의 로케일 인코딩(cp949)으로는 '—' 하나에 죽는다.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 기능명세서 §6 `vehicle_classes` — 지게차 기본 3.0m(제조현장 실내 통행 기준).
DEV_CLASSES: list[dict[str, object]] = [
    {"class_name": "vehicle", "danger_radius_m": 3.0, "active": True},
]


def seed(*, force: bool) -> int:
    statement = insert(VehicleClassRow).values(DEV_CLASSES)
    if force:
        statement = statement.on_conflict_do_update(
            index_elements=["class_name"],
            set_={
                "danger_radius_m": statement.excluded.danger_radius_m,
                "active": statement.excluded.active,
            },
        )
    else:
        # 현장에서 조정한 반경을 시드가 조용히 되돌리면 안 된다 — 그 값은 통로 폭과
        # 운용 속도를 보고 사람이 정한 것이다.
        statement = statement.on_conflict_do_nothing(index_elements=["class_name"])

    with create_db_engine().begin() as connection:
        result = connection.execute(statement)
    return int(result.rowcount)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="vehicle_classes 위험 반경 기본값 시드")
    parser.add_argument(
        "--force",
        action="store_true",
        help="이미 있는 클래스도 기본값(3.0m)으로 되돌린다",
    )
    args = parser.parse_args(argv)

    affected = seed(force=args.force)
    total = len(DEV_CLASSES)
    mode = "덮어씀" if args.force else "신규"
    count = f"{affected}/{total} 클래스" if affected >= 0 else f"{total} 클래스 중 일부"
    print(f"vehicle_classes 시드 완료 — {count} {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
