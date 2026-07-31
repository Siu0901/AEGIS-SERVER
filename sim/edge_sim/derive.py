"""시나리오가 적은 **자세와 형상**에서 게이지를 계산한다. FN-DET-08 ~ 11

M6 가 미터에 대해 정한 규칙과 같은 규칙이다 — **결과를 시나리오에 적지 않는다.**
예전에는 `height_ratio` · `axis_angle_deg` · `stillness_s` · `nearby[].dist_m` 을
손으로 적었는데, 그러면 시나리오 작성자가 곧 판정자가 되어 오탐 억제를 검증할 수 없다.
이제 시나리오는 **관측 가능한 것**(bbox · 자세 · 움직임 · 포크 길이)만 적고, 게이지는
`packages/vision` 의 실제 로직이 계산한다.

| 시나리오가 적는 것 | 계산해서 싣는 것 |
|---|---|
| `mask: {posture, motion}` | `height_ratio` · `axis_angle_deg` · `stillness_s` · `posture` |
| `mask: {fork}` (지게차) | 지게차 윤곽 — 최근접 거리의 입력 |
| `nearby: auto` (후보) | `nearby[]` 전량 — 거리 · 방식 · 위험 반경 · `depth_verified` |

**섞어 적으면 오류다.** `mask` 를 적었는데 `height_ratio` 도 적으면 어느 쪽이 진짜인지
알 수 없다. 옛 시나리오(M2~M4)는 `mask` 를 적지 않으므로 손으로 적은 값을 그대로 쓴다 —
새 규칙은 새 시나리오에만 적용된다.

---

★ **판정은 여기서 하지 않는다.** `posture` 는 `aegis_vision.posture.posture_of` 가
세 조건을 보고 정하고, 근접 후보 여부는 서버가 정한다. 이 모듈이 하는 일은 실물 엣지가
모델에서 얻었을 숫자를 **같은 계산으로** 만들어 내는 것뿐이다.

**뎁스 모델이 없다.** `depth_verified` 는 트리거 조건(FN-DET-11)까지는 실제 로직으로
판정하고, 모델 자리에는 결정적인 대역(`_SimProbe`)을 넣는다. M9 에서 이 대역이
`edge/depth.py` 로 교체된다 — 그때 바뀌는 것은 주입되는 객체 하나뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aegis_contracts import Policies
from aegis_vision import (
    Bbox,
    DepthCache,
    DepthResult,
    FallThresholds,
    Homography,
    NearbyReading,
    PointM,
    PointPx,
    ProximityRadii,
    ReferenceHeight,
    StillnessTracker,
    depth_triggers,
    distance_mask_nearest_m,
    height_ratio,
    mask_shape,
    posture_of,
    screen_nearby,
    verify_depth,
    within_radius,
)
from sim.edge_sim.masks import person_mask, vehicle_mask

__all__ = ["DerivedState", "derive_entries"]

#: 판정 임계값의 출처. **서버 `policies` 테이블의 기본값과 같은 값**이다
#: (`aegis_contracts.Policies` — 명세서 §4.5 예시에서 온 값이라 코드 상수가 아니다).
#:
#: 시뮬레이터는 DB 에 접근하지 않으므로 계약 기본값을 쓴다. 현장에서 정책을 바꾸면
#: 서버 판정은 따라가지만 시뮬레이터가 만드는 관측값은 따라가지 않는데, 그것은 실물
#: 엣지도 마찬가지다 — 엣지가 정책을 받아오는 경로는 M9 의 일이다.
_POLICIES = Policies()

#: 기준 인물. `cameras.ref_height_px_at_m`(§4.5 `reference_person`)에 해당한다.
#:
#: **모형 시연에서도 실제 작업자 신장(약 1.7m) 기준으로 입력한다**(기능명세서 §4.7
#: FN-CFG-01). 개발용 카메라 기하에서 지면 (6, 9) m 에 선 사람이 화면 높이 0.42 를
#: 차지하는 값이며, `scripts/seed_cameras.py` 의 격자와 같은 평면 위에 있다.
_REFERENCE = ReferenceHeight(px_height=0.42, at_m=(6.0, 9.0))

#: 정지 판정 임계. 카메라 화각·설치 높이에 따라 달라지는 튜닝값이라 실물에서는
#: `edge/config.yaml` 의 `posture` 절에서 온다(CLAUDE.md 절대규칙 6).
_STILLNESS_MOVE_MAX = 0.02
_STILLNESS_SHAPE_MAX = 0.15

#: 뎁스 캐시 무효화 이동량(m). §6.6 「임계 이상 이동하면 즉시 무효화」.
_DEPTH_MOVE_INVALIDATE_M = 0.5


def _thresholds() -> FallThresholds:
    return FallThresholds(
        height_ratio_max=_POLICIES.fall_height_ratio_max,
        axis_angle_min_deg=_POLICIES.fall_axis_angle_min_deg,
        stillness_s=_POLICIES.fall_stillness_s,
    )


def _radii(danger_m: float) -> ProximityRadii:
    return ProximityRadii(
        screening_m=_POLICIES.screening_radius_m,
        danger_m=danger_m,
        warn_m=_POLICIES.proximity_threshold_m,
    )


class _SimProbe:
    """뎁스 모델 자리의 결정적 대역. **M9 에서 `edge/depth.py` 로 교체된다.**

    실제 모델은 두 영역의 상대 깊이 분포를 비교한다(§6.6). 여기서는 그 결론을 지면
    거리로 흉내낸다 — 지면에서 가까우면 앞뒤로도 가깝다고 본다. 시뮬레이터 안에서는
    원근 착시가 애초에 없으므로 이 대역이 만들어 내는 오답도 없다.

    ★ **거리 수치를 내지 않는다.** `DepthResult` 에는 미터 필드가 없고, 이 대역도
    입력으로 받은 거리를 참/거짓 하나로만 바꾼다(절대규칙 4).
    """

    def __init__(self, *, same_plane: bool) -> None:
        self._same_plane = same_plane

    def measure(self, *, person_bbox: Bbox, vehicle_bbox: Bbox | None) -> DepthResult:
        del person_bbox, vehicle_bbox
        return DepthResult(same_plane=self._same_plane)


@dataclass(slots=True)
class _Track:
    """한 트랙의 이어지는 상태. 정지 지속은 프레임 사이에 이어져야 한다."""

    stillness: StillnessTracker


@dataclass(slots=True)
class DerivedState:
    """한 카메라의 마지막 프레임. 후보의 `nearby: auto` 가 이것을 본다.

    후보 메시지에는 다른 객체가 실리지 않으므로(§2.2), 주변 지게차를 알려면 같은
    순간의 프레임을 봐야 한다. **실물 엣지도 같은 프레임에서 둘을 함께 본다.**
    """

    at_s: float
    persons: dict[int, dict[str, Any]]
    vehicles: dict[int, dict[str, Any]]
    contours: dict[tuple[str, int], list[PointPx]]


def derive_entries(
    entries: list[tuple[float, dict[str, Any]]],
    homography_for: Any,
    default_cam: int,
) -> None:
    """시각 순서로 훑으며 파생 필드를 채운다. **입력을 제자리에서 고친다.**

    시간 순서가 중요하다 — 정지 지속은 앞 프레임과의 차이이고, 후보의 `nearby` 는
    직전 프레임의 지게차 위치를 본다. 정렬된 목록을 받는 것이 이 함수의 전제다.
    """
    tracks: dict[tuple[int, int], _Track] = {}
    frames: dict[int, DerivedState] = {}
    caches: dict[int, DepthCache] = {}

    for at_s, payload in entries:
        kind = str(payload.get("type"))
        cam_id = int(payload.get("cam_id", default_cam))
        if kind == "frame":
            frames[cam_id] = _derive_frame(at_s, payload, homography_for(cam_id), tracks, cam_id)
        elif kind == "candidate" and payload.get("nearby") == "auto":
            cache = caches.setdefault(
                cam_id,
                DepthCache(
                    ttl_s=_POLICIES.depth_cache_ms / 1000.0,
                    move_invalidate_m=_DEPTH_MOVE_INVALIDATE_M,
                ),
            )
            payload["nearby"] = _derive_nearby(
                at_s, payload, frames.get(cam_id), homography_for(cam_id), cache, cam_id
            )


def _derive_frame(
    at_s: float,
    payload: dict[str, Any],
    homography: Homography,
    tracks: dict[tuple[int, int], _Track],
    cam_id: int,
) -> DerivedState:
    """`frame` 한 장의 사람 게이지를 계산하고, 후보가 볼 상태를 남긴다."""
    persons: dict[int, dict[str, Any]] = {}
    vehicles: dict[int, dict[str, Any]] = {}
    contours: dict[tuple[str, int], list[PointPx]] = {}

    for obj in payload.get("objects", []):
        spec = obj.get("mask")
        track_id = int(obj["track_id"])
        if obj.get("class") == "person":
            persons[track_id] = obj
            if spec is None:
                continue
            contour = person_mask(
                _bbox(obj["bbox"]),
                posture=str(spec["posture"]),
                motion=str(spec["motion"]),
                at_s=at_s,
            )
            contours[("person", track_id)] = contour
            _apply_person_gauges(obj, contour, homography, tracks, at_s, cam_id, track_id)
        else:
            vehicles[track_id] = obj
            if spec is not None:
                contours[("vehicle", track_id)] = vehicle_mask(
                    _bbox(obj["bbox"]), fork_ratio=float(spec.get("fork", 0.0))
                )
        obj.pop("mask", None)

    return DerivedState(at_s=at_s, persons=persons, vehicles=vehicles, contours=contours)


def _apply_person_gauges(
    obj: dict[str, Any],
    contour: list[PointPx],
    homography: Homography,
    tracks: dict[tuple[int, int], _Track],
    at_s: float,
    cam_id: int,
    track_id: int,
) -> None:
    """세 게이지와 `posture` 를 싣는다. **판정은 `posture_of` 가 한다.**"""
    for field in ("height_ratio", "axis_angle_deg", "stillness_s", "posture"):
        if field in obj:
            msg = (
                f"시나리오가 {field} 를 직접 적었다 — mask 를 적으면 게이지는 계산된다"
                f" (FN-DET-10). 그 줄을 지워라"
            )
            raise ValueError(msg)

    shape = mask_shape(contour)
    track = tracks.setdefault(
        (cam_id, track_id),
        _Track(
            stillness=StillnessTracker(
                move_max=_STILLNESS_MOVE_MAX,
                shape_change_max=_STILLNESS_SHAPE_MAX,
            )
        ),
    )
    stillness_s = track.stillness.observe(at_s, shape)
    reading = posture_of(
        height_ratio=height_ratio(
            shape,
            foot_point=_point(obj["foot_point"]),
            homography=homography,
            reference=_REFERENCE,
        ),
        axis_angle_deg=shape.angle_deg,
        stillness_s=stillness_s,
        thresholds=_thresholds(),
    )
    obj["height_ratio"] = reading.height_ratio
    obj["axis_angle_deg"] = reading.axis_angle_deg
    obj["stillness_s"] = reading.stillness_s
    obj["posture"] = reading.posture


def _derive_nearby(
    at_s: float,
    payload: dict[str, Any],
    state: DerivedState | None,
    homography: Homography,
    cache: DepthCache,
    cam_id: int,
) -> list[dict[str, Any]]:
    """후보의 `nearby[]` 를 같은 순간의 프레임에서 계산한다(§2.2)."""
    if state is None:
        msg = "nearby: auto 를 쓰려면 그 앞에 같은 카메라의 frame 이 있어야 한다"
        raise ValueError(msg)
    track_id = int(payload["track_id"])
    person_contour = state.contours.get(("person", track_id))
    if person_contour is None:
        msg = f"nearby: auto — 트랙 {track_id} 의 마스크가 없다. frame 에 mask 를 적어라"
        raise ValueError(msg)

    person_anchor = homography.to_ground(_point(payload["foot_point"]))
    readings: list[tuple[NearbyReading, dict[str, Any]]] = []

    for vehicle_id, vehicle in state.vehicles.items():
        contour = state.contours.get(("vehicle", vehicle_id))
        if contour is None:
            continue
        distance = distance_mask_nearest_m(person_contour, contour, homography)
        danger_m = float(vehicle.get("danger_radius_m", _POLICIES.vehicle_danger_radius_m))
        vehicle_m = homography.to_ground(_point(vehicle["anchor"]))
        verified = _depth_verified(
            distance,
            payload=payload,
            vehicle=vehicle,
            cache=cache,
            cam_id=cam_id,
            person_track=track_id,
            vehicle_track=vehicle_id,
            at_s=at_s,
            person_m=person_anchor,
            vehicle_m=vehicle_m,
        )
        reading = NearbyReading(
            track_id=vehicle_id,
            dist_m=round(distance, 2),
            method="mask_nearest",
            moving=bool(vehicle.get("moving", False)),
            within_danger_radius=within_radius(distance, danger_m),
            depth_verified=verified,
        )
        readings.append(
            (
                reading,
                {
                    "class": "vehicle",
                    "track_id": reading.track_id,
                    "dist_m": reading.dist_m,
                    "method": reading.method,
                    "depth_verified": reading.depth_verified,
                    "moving": reading.moving,
                    "within_danger_radius": reading.within_danger_radius,
                },
            )
        )

    # 스크리닝 반경(기본 5m) 밖은 `nearby[]` 에 싣지 않는다(§2.2). 위험 반경은 차량별
    # 값이라 원소마다 이미 반영했고, 여기서 쓰는 것은 스크리닝뿐이다.
    radii = _radii(_POLICIES.vehicle_danger_radius_m)
    kept = screen_nearby([reading for reading, _ in readings], radii)
    by_track = {reading.track_id: body for reading, body in readings}
    return [by_track[reading.track_id] for reading in kept]


def _depth_verified(
    distance: float,
    *,
    payload: dict[str, Any],
    vehicle: dict[str, Any],
    cache: DepthCache,
    cam_id: int,
    person_track: int,
    vehicle_track: int,
    at_s: float,
    person_m: PointM,
    vehicle_m: PointM,
) -> bool:
    """FN-DET-11 — 트리거가 걸릴 때만 1프레임 실행한다.

    트리거 판정은 실제 로직(`depth_triggers`)이고 모델 자리만 대역이다.
    """
    triggers = depth_triggers(
        dist_m=distance,
        person_bbox=_bbox(payload["bbox"]),
        vehicle_bbox=_bbox(vehicle["bbox"]),
        foot_conf=payload.get("foot_conf"),
        min_foot_conf=_POLICIES.min_confidence,
        band_m=tuple(_POLICIES.depth_band_m),  # type: ignore[arg-type]
        fall_candidate=payload.get("violation_type") == "fall",
    )
    result = verify_depth(
        _SimProbe(same_plane=distance <= _POLICIES.vehicle_danger_radius_m),
        cache,
        key=(cam_id, person_track, vehicle_track),
        at_s=at_s,
        person_bbox=_bbox(payload["bbox"]),
        vehicle_bbox=_bbox(vehicle["bbox"]),
        person_m=person_m,
        vehicle_m=vehicle_m,
        triggers=triggers,
    )
    return result.same_plane


def _bbox(value: Any) -> Bbox:
    x1, y1, x2, y2 = (float(item) for item in value)
    return (x1, y1, x2, y2)


def _point(value: Any) -> PointPx:
    return (float(value[0]), float(value[1]))
