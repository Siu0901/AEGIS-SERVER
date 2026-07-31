"""`cameras` 테이블에 **개발용** 카메라와 캘리브레이션을 시드한다.

    uv run python -m scripts.seed_cameras            # 없는 카메라만 넣는다 (기본)
    uv run python -m scripts.seed_cameras --force    # 캘리브레이션을 기본값으로 되돌린다

운용 환경의 캘리브레이션은 설정 화면에서 사람이 4점을 찍어 만든다(FN-CFG-01). 여기
있는 것은 `sim/cases/*.yaml` 시나리오와 짝이 맞는 개발용 값이며, **시뮬레이터가 쓰는
것과 같은 상수**다(`sim/edge_sim/scripted.py`) — 엣지와 서버가 서로 다른 좌표계로
계산하면 거리도 구역도 어긋난다.

**행렬을 손으로 적지 않는다.** 실측 4점만 적고 `aegis_vision.Homography` 로 푼다.
설정 API 가 쓰는 것과 같은 코드라, 시드한 좌표계와 화면에서 찍어 만든 좌표계가 같은
방법으로 만들어진다.

4점의 출처: 시나리오가 암묵적으로 쓰던 카메라 기하를 핀홀 모델로 복원해(높이 약 2.2m ·
틸트 약 6° · 수평화각 약 60°) 바닥의 정수 격자 네 점을 투영한 값이다. 그래서 기존
시나리오의 픽셀 경로가 예전 미터값과 거의 같은 위치로 변환된다(`docs/INDEX.md` M6 절).
"""

from __future__ import annotations

import argparse
import io
import sys
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from aegis_vision import Correspondence, Homography
from server.infra.db import Camera, create_db_engine

# `tasks.py migrate` 가 이 모듈을 자식으로 돌리므로 출력이 파이프가 된다.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

__all__ = ["DEV_CALIBRATION", "DEV_CAMERAS", "DEV_REF_HEIGHT", "homography_for", "seed"]

#: 개발용 기준 인물 — `cameras.ref_height`(기능명세서 §6).
#:
#: ★ **스칼라가 아니다.** 기준 높이를 잰 **지면 위치**가 함께 있어야 다른 거리의 기대
#: 높이를 구할 수 있다(같은 사람도 카메라에서 멀수록 화면상 높이가 줄어든다).
#:
#: 지면 (6, 9) m 에 선 사람이 화면 높이의 0.42 를 차지한다 — 위 4점과 같은 평면 위의
#: 값이며, **시뮬레이터가 쓰는 것과 같은 상수**다(`sim/edge_sim/derive.py`). 두 곳이
#: 다른 기준을 쓰면 엣지가 싣는 `height_ratio` 와 서버·화면이 기대하는 값이 갈린다.
#:
#: **모형 시연에서도 실제 작업자 신장(약 1.7m) 기준으로 넣는다**(기능명세서 §4.7).
DEV_REF_HEIGHT: dict[str, Any] = {"height_px": 0.42, "at_m": [6.0, 9.0]}

#: 카메라별 실측 4점 — (화면에서 클릭한 정규화 좌표, 줄자로 잰 지면 좌표 m).
#:
#: 네 점은 바닥의 3m×5m 사각형(x 3~9 · y 7~12)이다. **한 직선 위에 있으면 안 되고**
#: 화면 안에 들어와야 한다(둘 다 `Homography.from_correspondences` 가 검사한다).
DEV_CALIBRATION: dict[int, list[Correspondence]] = {
    1: [
        ((0.1297, 0.8159), (3.0, 7.0)),
        ((0.8696, 0.8159), (9.0, 7.0)),
        ((0.7185, 0.6197), (9.0, 12.0)),
        ((0.2811, 0.6197), (3.0, 12.0)),
    ],
    2: [
        ((0.1332, 0.8080), (3.0, 7.0)),
        ((0.8649, 0.8080), (9.0, 7.0)),
        ((0.7201, 0.6346), (9.0, 12.0)),
        ((0.2788, 0.6346), (3.0, 12.0)),
    ],
}

#: 개발용 카메라. RTSP 주소는 `deploy/` 의 가짜 카메라와 같은 규칙을 쓴다.
DEV_CAMERAS: list[dict[str, Any]] = [
    {
        "cam_id": 1,
        "name": "1번 카메라 · 조립 라인",
        "rtsp_main": "rtsp://127.0.0.1:8554/cam1/main",
        "rtsp_sub": "rtsp://127.0.0.1:8554/cam1/sub",
    },
    {
        "cam_id": 2,
        "name": "2번 카메라 · 자재 통로",
        "rtsp_main": "rtsp://127.0.0.1:8554/cam2/main",
        "rtsp_sub": "rtsp://127.0.0.1:8554/cam2/sub",
    },
]


def homography_for(cam_id: int) -> Homography:
    """개발용 캘리브레이션 4점으로 푼 호모그래피. 시뮬레이터와 시드가 함께 쓴다."""
    points = DEV_CALIBRATION.get(cam_id)
    if points is None:
        msg = f"개발용 캘리브레이션이 없는 카메라다: {cam_id} (있는 것: {sorted(DEV_CALIBRATION)})"
        raise KeyError(msg)
    return Homography.from_correspondences(points)


def _rows() -> list[dict[str, Any]]:
    """행렬과 함께 **대응점 원본과 재투영 오차도** 심는다(API명세서 §4.5 `calib_points`).

    행렬만 남기면 설정 화면이 어느 점을 찍었는지 복원할 수 없어, 개발용 캘리브레이션을
    화면에서 확인하거나 한 점만 고칠 수 없다.
    """
    rows: list[dict[str, Any]] = []
    for camera in DEV_CAMERAS:
        cam_id = int(camera["cam_id"])
        points = DEV_CALIBRATION[cam_id]
        homography = homography_for(cam_id)
        rows.append(
            camera
            | {
                "homography": homography.to_rows(),
                "calib_points": [{"px": list(px), "m": list(m)} for px, m in points],
                "reproj_error_m": round(homography.reprojection_error_m(points), 4),
                "ref_height": dict(DEV_REF_HEIGHT),
            }
        )
    return rows


def seed(*, force: bool) -> int:
    statement = insert(Camera).values(_rows())
    if force:
        statement = statement.on_conflict_do_update(
            index_elements=["cam_id"],
            set_={
                "name": statement.excluded.name,
                "rtsp_main": statement.excluded.rtsp_main,
                "rtsp_sub": statement.excluded.rtsp_sub,
                "homography": statement.excluded.homography,
                "calib_points": statement.excluded.calib_points,
                "reproj_error_m": statement.excluded.reproj_error_m,
                "ref_height": statement.excluded.ref_height,
            },
        )
    else:
        # 현장에서 찍은 캘리브레이션을 시드가 조용히 덮어쓰면 안 된다. 카메라를 옮긴
        # 뒤 다시 찍은 4점이 사라지면 그 순간부터 모든 거리 판정이 틀린다.
        statement = statement.on_conflict_do_nothing(index_elements=["cam_id"])

    with create_db_engine().begin() as connection:
        result = connection.execute(statement)
    return int(result.rowcount)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="cameras 테이블 개발용 기본값 시드")
    parser.add_argument(
        "--force",
        action="store_true",
        help="이미 있는 카메라의 캘리브레이션도 개발용 기본값으로 되돌린다",
    )
    args = parser.parse_args(argv)

    affected = seed(force=args.force)
    mode = "덮어씀" if args.force else "신규"
    count = (
        f"{affected}/{len(DEV_CAMERAS)} 카메라"
        if affected >= 0
        else f"{len(DEV_CAMERAS)} 카메라 중 일부(개수 미보고)"
    )
    for camera in DEV_CAMERAS:
        cam_id = int(camera["cam_id"])
        points = DEV_CALIBRATION[cam_id]
        error = homography_for(cam_id).reprojection_error_m(points)
        print(f"  cam{cam_id} 재투영 오차 {error:.4f} m (실측점 {len(points)}개)")
    print(f"cameras 시드 완료 — {count} {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
