"""레고 모형 시연용 정책값 — **거리 임계를 보드 cm 좌표계로 환산한다.**

    uv run python -m scripts.seed_lego_policies --dry-run   # 계산만 보여준다
    uv run python -m scripts.seed_lego_policies             # DB 에 적용
    uv run python -m scripts.seed_lego_policies --restore   # 명세서 기본값으로 되돌린다

★ **호모그래피는 단위를 모른다.** 캘리브레이션 4점을 미터로 넣으면 좌표계가 미터가
되고, 보드 cm 로 넣으면 cm 가 된다. 그래서 실측을 cm 로 넣기로 했다면 거리 임계값도
**같은 단위로 바꿔야 한다** — 안 바꾸면 `vehicle_danger_radius_m = 3.0` 이 「보드 위
3cm」로 해석되어 지게차 근접이 거의 걸리지 않는다.

**축척은 미니피겨 키로 잡는다.** 보드 치수가 아니라 사람 크기가 기준이어야, 실제
현장의 「사람으로부터 3m」가 모형에서 같은 의미를 갖는다.

**시간 임계는 건드리지 않는다.** 확정 3초·해소 10초·쿨다운 30초는 사람의 반응 시간에서
나온 값이라 축척과 무관하다. 정규화 픽셀 단위인 `stillness_move_px` 도 마찬가지다.

**여기 있는 값은 명세서 기본값을 대체하지 않는다.** `scripts/seed_policies.py` 가 여전히
원천이고(§4.5), 이 스크립트는 모형 시연 동안만 덮어쓰는 프로파일이다. 실물 현장으로
옮길 때는 `--restore` 로 되돌린 뒤 캘리브레이션만 다시 한다.
"""

from __future__ import annotations

import argparse
import io
import sys
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from aegis_contracts import Policies
from server.infra.db import Policy, VehicleClassRow, create_db_engine

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

__all__ = ["lego_policies", "main", "scale_factor"]

#: 미니피겨 키(cm). 사람이 자로 잰 값이다.
MINIFIG_HEIGHT_CM = 4.0

#: 기준 작업자 신장(m). 기능명세서 §4.7 — 모형 시연에서도 실제 작업자 기준으로 넣는다.
REAL_PERSON_HEIGHT_M = 1.7

#: 사람 박스의 실측 높이 범위(서브 640×360 기준, `media/lego_sample_1.mp4`).
#:
#: ★ **명세서 기본값 64px 로는 안전모 분류가 한 번도 돌지 않는다.** 이 영상에서
#: 미니피겨는 20~50px 이고, 실제로 파이프라인을 태웠을 때 80회 전량이 크기 게이트에
#: 걸렸다(`cls_gated_small=80, cls_calls=0`). 카메라가 명세서의 설치 지침(사람이 프레임
#: 높이의 약 18%)을 만족하지 못하는 상황이며, 값을 낮추는 것은 **분류 신뢰도를 낮추는
#: 대가를 치르는 선택**이다. 근본 해결은 카메라를 더 가까이 두는 것이다.
LEGO_CLS_MIN_CROP_PX = 20


def scale_factor() -> float:
    """보드 cm 당 실제 미터. 1 보드cm ≈ 0.425 m."""
    return REAL_PERSON_HEIGHT_M / (MINIFIG_HEIGHT_CM / 100.0) / 100.0


def board_cm(real_m: float) -> float:
    """실제 미터를 보드 cm 로."""
    return round(real_m / scale_factor(), 2)


def lego_policies() -> dict[str, Any]:
    """덮어쓸 키만 돌려준다. **거리·속도 키만 바꾼다.**"""
    base = Policies()
    low, high = base.depth_band_m
    return {
        "vehicle_danger_radius_m": board_cm(base.vehicle_danger_radius_m),
        "proximity_threshold_m": board_cm(base.proximity_threshold_m),
        "reassoc_max_speed_ms": board_cm(base.reassoc_max_speed_ms),
        "reassoc_radius_cap_m": board_cm(base.reassoc_radius_cap_m),
        "screening_radius_m": board_cm(base.screening_radius_m),
        "depth_band_m": [board_cm(low), board_cm(high)],
        "cls_min_crop_px": LEGO_CLS_MIN_CROP_PX,
    }


def _apply(values: dict[str, Any], danger_radius: float) -> None:
    """정책과 **클래스별 위험 반경을 함께** 바꾼다.

    ★ 둘을 따로 두면 안 된다. 실제로 정책만 바꿨을 때 `proximity_threshold_m` 는
    보드 cm(4.71)인데 `vehicle_classes.danger_radius_m` 는 미터(3.0)로 남아
    「근접 임계 > 위험 반경」이 되었고, `aegis_vision.ProximityRadii` 가 그 모순을
    거부하며 엣지가 죽었다(FN-CFG-05 · §4.5). 좌표계를 바꾸는 것은 한 번의 결정이므로
    한 번의 적용이어야 한다.
    """
    rows = [{"key": key, "value": value} for key, value in values.items()]
    policies = insert(Policy).values(rows)
    policies = policies.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": policies.excluded.value},
    )
    vehicles = insert(VehicleClassRow).values(
        [{"class_name": "vehicle", "danger_radius_m": danger_radius, "active": True}]
    )
    vehicles = vehicles.on_conflict_do_update(
        index_elements=["class_name"],
        set_={"danger_radius_m": vehicles.excluded.danger_radius_m},
    )
    with create_db_engine().begin() as connection:
        connection.execute(policies)
        connection.execute(vehicles)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="레고 모형 시연용 정책값(보드 cm 좌표계)")
    parser.add_argument("--dry-run", action="store_true", help="계산만 보여주고 쓰지 않는다")
    parser.add_argument(
        "--restore",
        action="store_true",
        help="명세서 기본값(미터 좌표계)으로 되돌린다",
    )
    args = parser.parse_args(argv)

    base = Policies().model_dump(mode="json")
    if args.restore:
        values = {key: base[key] for key in lego_policies()}
        label = "명세서 기본값 복원"
    else:
        values = lego_policies()
        label = (
            f"레고 프로파일 (미니피겨 {MINIFIG_HEIGHT_CM}cm · 1 보드cm = {scale_factor():.3f} m)"
        )

    # `vehicle_classes` 의 위험 반경도 같은 좌표계여야 한다 — 정책만 바꾸면
    # 「근접 임계 > 위험 반경」이 되어 `ProximityRadii` 가 거부한다.
    danger_radius = float(values["vehicle_danger_radius_m"])

    print(label)
    for key, value in values.items():
        print(f"  {key:26} {base[key]!r:>14}  →  {value!r}")
    print(f"  {'vehicle_classes.vehicle':26} {'3.0':>14}  →  {danger_radius!r}")

    if args.dry_run:
        print("\n--dry-run 이라 쓰지 않았다.")
        return 0

    _apply(values, danger_radius)
    print(f"\npolicies {len(values)}건 + 위험 반경 적용 — 엣지는 다음 조회(최대 30초)에 반영한다.")
    if not args.restore:
        print("캘리브레이션 4점도 보드 cm 로 넣어야 한다 — 단위가 섞이면 전부 어긋난다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
