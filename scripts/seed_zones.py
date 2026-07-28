"""`zones` 테이블에 **개발용** 기본 금지구역을 시드한다.

    uv run python -m scripts.seed_zones            # 없는 구역만 넣는다 (기본)
    uv run python -m scripts.seed_zones --force    # 기존 값을 기본값으로 되돌린다

운용 환경의 구역은 설정 화면에서 사람이 그린다(FN-CFG-02 · M6). 여기 있는 것은
`sim/cases/*.yaml` 시나리오와 짝이 맞는 개발용 값이다 — 시뮬레이터가 보내는
`in_zone: forklift_lane` 이 실제로 존재하는 구역을 가리켜야 `GET /zones` 로 받은
대시보드 캐시(§5.1)와 오버레이 라벨이 서로 맞는다. 구역 행이 없으면 화면에는
"forklift_lane" 이라는 정체불명의 문자열만 남는다.

**폴리곤은 지면 실좌표(m)다**(기능명세서 §6). 화면 픽셀로 그리려면 호모그래피가
있어야 하고 그건 캘리브레이션(FN-CFG-01 · M6) 이후의 일이다.
"""

from __future__ import annotations

import argparse
import io
import sys

from sqlalchemy.dialects.postgresql import insert

from server.infra.db import Zone, create_db_engine

# `tasks.py migrate` 가 이 모듈을 자식으로 돌리므로 출력이 파이프가 된다.
# 한글 Windows 의 로케일 인코딩(cp949)으로는 '—' 하나에 죽는다.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 개발용 기본 구역. `sim/cases/no_helmet.yaml` 의 경로가 이 사각형을 통과한다.
#:
#: 시안의 건설현장 용어(굴착 구역)가 아니라 제조현장 용어를 쓴다(기능명세서 부록 B).
DEV_ZONES: list[dict[str, object]] = [
    {
        "zone_id": "forklift_lane",
        "cam_id": 1,
        "name": "지게차 통행로",
        "polygon_m": [[2.0, 6.0], [7.0, 6.0], [7.0, 11.0], [2.0, 11.0]],
        "buffer_m": 0.3,
        "active": True,
    },
]


def seed(*, force: bool) -> int:
    statement = insert(Zone).values(DEV_ZONES)
    if force:
        statement = statement.on_conflict_do_update(
            index_elements=["zone_id"],
            set_={
                "cam_id": statement.excluded.cam_id,
                "name": statement.excluded.name,
                "polygon_m": statement.excluded.polygon_m,
                "buffer_m": statement.excluded.buffer_m,
                "active": statement.excluded.active,
            },
        )
    else:
        # 사람이 그린 구역을 시드가 조용히 덮어쓰면 안 된다.
        statement = statement.on_conflict_do_nothing(index_elements=["zone_id"])

    with create_db_engine().begin() as connection:
        result = connection.execute(statement)
    return int(result.rowcount)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="zones 테이블 개발용 기본값 시드")
    parser.add_argument(
        "--force",
        action="store_true",
        help="이미 있는 구역도 개발용 기본값으로 되돌린다",
    )
    args = parser.parse_args(argv)

    affected = seed(force=args.force)
    total = len(DEV_ZONES)
    mode = "덮어씀" if args.force else "신규"
    count = f"{affected}/{total} 구역" if affected >= 0 else f"{total} 구역 중 일부(개수 미보고)"
    print(f"zones 시드 완료 — {count} {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
