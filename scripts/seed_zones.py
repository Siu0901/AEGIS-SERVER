"""`zones` 테이블에 **개발용** 기본 금지구역을 시드한다.

    uv run python -m scripts.seed_zones            # 없는 구역만 넣는다 (기본)
    uv run python -m scripts.seed_zones --force    # 기존 값을 기본값으로 되돌린다

운용 환경의 구역은 설정 화면에서 사람이 그린다(FN-CFG-02 · M6). 여기 있는 것은
`sim/cases/*.yaml` 시나리오와 짝이 맞는 개발용 값이다 — 시뮬레이터가 보내는
`in_zone: forklift_lane` 이 실제로 존재하는 구역을 가리켜야 `GET /zones` 로 받은
대시보드 캐시(§5.1)와 오버레이 라벨이 서로 맞는다. 구역 행이 없으면 화면에는
"forklift_lane" 이라는 정체불명의 문자열만 남는다.

**두 표현을 모두 심는다**(API명세서 §4.5). 판정은 `polygon_m`(지면 미터)으로 하고,
설정 화면이 구역을 다시 그리려면 `polygon`(정규화 픽셀)이 필요하다. 캘리브레이션이
갱신되면 서버가 **픽셀을 기준으로** 미터를 다시 계산하므로, 픽셀이 비어 있는 구역은
좌표계가 바뀔 때 따라오지 못한다.

여기서는 지면 사각형을 먼저 정하고 개발용 호모그래피로 **픽셀을 역산**한다 — 이
사각형에 시나리오 12종의 `in_zone` 기대값이 걸려 있어서 값을 옮길 수 없기 때문이다.
그 결과 왼쪽 아래 꼭짓점의 x 가 −0.07 로 **화면 왼쪽 밖**에 놓인다. 사람이 그릴 수 없는
모양이지만 좌표로는 성립하며, 이 구역이 화면보다 넓다는 사실을 그대로 보여준다.
"""

from __future__ import annotations

import argparse
import io
import sys
from typing import cast

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from scripts.seed_cameras import homography_for
from server.infra.db import Zone, create_db_engine

# `tasks.py migrate` 가 이 모듈을 자식으로 돌리므로 출력이 파이프가 된다.
# 한글 Windows 의 로케일 인코딩(cp949)으로는 '—' 하나에 죽는다.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 개발용 기본 구역의 지면 사각형. `sim/cases/no_helmet.yaml` 의 경로가 여기를 통과한다.
#:
#: 시안의 건설현장 용어(굴착 구역)가 아니라 제조현장 용어를 쓴다(기능명세서 부록 B).
_DEV_GROUND: list[dict[str, object]] = [
    {
        "zone_id": "forklift_lane",
        "cam_id": 1,
        "name": "지게차 통행로",
        "polygon_m": [[2.0, 6.0], [7.0, 6.0], [7.0, 11.0], [2.0, 11.0]],
        "buffer_m": 0.3,
        "active": True,
    },
]


def _with_pixels(zones: list[dict[str, object]]) -> list[dict[str, object]]:
    """지면 사각형에서 픽셀 폴리곤을 역산해 붙인다.

    **DB 시드와 시뮬레이터가 같은 호모그래피를 쓴다**(`scripts/seed_cameras.py`).
    다른 값을 쓰면 서버가 계산하는 구역과 엣지가 보내는 좌표가 다른 평면 위에 놓인다.
    """
    seeded: list[dict[str, object]] = []
    for zone in zones:
        homography = homography_for(cast("int", zone["cam_id"]))
        polygon_m = cast("list[list[float]]", zone["polygon_m"])
        pixels = [homography.to_pixel((point[0], point[1])) for point in polygon_m]
        seeded.append(zone | {"polygon": [[round(x, 4), round(y, 4)] for x, y in pixels]})
    return seeded


DEV_ZONES: list[dict[str, object]] = _with_pixels(_DEV_GROUND)


def seed(*, force: bool) -> int:
    statement = insert(Zone).values(DEV_ZONES)
    if force:
        statement = statement.on_conflict_do_update(
            index_elements=["zone_id"],
            set_={
                "cam_id": statement.excluded.cam_id,
                "name": statement.excluded.name,
                "polygon_m": statement.excluded.polygon_m,
                "polygon": statement.excluded.polygon,
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


def warn_if_unseeded() -> None:
    """픽셀 폴리곤이 빈 구역을 알린다. **조용히 넘기지 않는다**(절대규칙 9).

    기본 시드는 기존 행을 건드리지 않으므로 마이그레이션 `0007` 이 추가한 `polygon`
    (정규화 픽셀)은 빈 배열로 남는다. 그 상태에서는 설정 화면이 구역을 되그릴 때
    미터 역변환 경로를 타고, 캘리브레이션을 다시 하면 **도형이 따라오지 못한다** —
    사용자가 그린 위치가 원본인데 그 원본이 없기 때문이다.
    """
    with Session(create_db_engine()) as session:
        empty = [row.zone_id for row in session.exec(select(Zone)) if not row.polygon]
    if not empty:
        return
    print(f"  ! 픽셀 폴리곤이 빈 구역이 있다: {', '.join(sorted(empty))}")
    print("    개발용 기본값으로 채우려면: uv run python -m scripts.seed_zones --force")
    print("    사람이 그린 구역이라면 설정 화면에서 다시 그려야 한다(역변환으로 지어내지 않는다).")


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
    warn_if_unseeded()
    return 0


if __name__ == "__main__":
    sys.exit(main())
