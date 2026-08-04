"""프레임 한 장 → `frame` · `candidate` · `track_lost`. FN-DET-06 ~ 11

**엣지는 판단하지 않는다**(CLAUDE.md 절대규칙 3). 여기서 하는 일은 모델 출력을
게이지로 바꾸고 **규칙에 걸린 것을 후보로 올리는 것**까지다. 확정(3초)·경고·해소(10초)·
재결합·시정률은 전부 서버가 한다. 이 파일에 "3초 지났으니 확정" 같은 코드가 들어가면
그 순간 서버 상태머신 검증이 무의미해진다.

계산은 전부 `packages/vision` 이 한다. `sim/edge_sim/derive.py` 가 시나리오에서 만든
게이지와 **같은 함수**를 부르므로, 서버 입장에서 실물 엣지와 시뮬레이터는 구분되지
않는다 — 다른 것은 숫자의 출처(모델 대 시나리오)뿐이다.

★ **마스크는 밖으로 나가지 않는다.** 윤곽은 접지점·자세·최근접 거리를 구하는 데만
쓰이고, 계약에는 마스크 필드가 없다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import numpy.typing as npt

from aegis_contracts import Policies
from aegis_contracts.edge import (
    CandidateMsg,
    DetectedObject,
    DetectedPerson,
    DetectedVehicle,
    FrameMsg,
    TrackLostMsg,
)
from aegis_contracts.enums import HelmetState, Posture, ViolationType
from aegis_vision import (
    Bbox,
    CalibrationError,
    DepthCache,
    FallThresholds,
    Homography,
    NearbyReading,
    PointM,
    PointPx,
    ProximityRadii,
    StillnessTracker,
    depth_triggers,
    distance_mask_nearest_m,
    foot_point_from_mask,
    height_ratio,
    mask_foot_point,
    mask_shape,
    posture_of,
    proximity_candidate,
    screen_nearby,
    verify_depth,
    within_radius,
    zone_state,
)

from .classify import HelmetClassifier, HelmetReading
from .client import CameraSetup, Setup
from .config import EdgeConfig
from .depth import DepthEstimator
from .detect import Detection, Detector
from .letterbox import Letterbox
from .track import LostTrack, Tracker

__all__ = ["CameraPipeline", "FrameOutput"]

log = logging.getLogger(__name__)

#: 뎁스 캐시 무효화 이동량(지면 단위). §6.6 「임계 이상 이동하면 즉시 무효화」.
#: `sim/edge_sim/derive.py` 와 같은 값이며, 미터 좌표계 기준이다.
_DEPTH_MOVE_INVALIDATE_M = 0.5


@dataclass(frozen=True, slots=True)
class FrameOutput:
    """한 프레임이 만들어 낸 메시지들. 순서대로 보낸다."""

    frame: FrameMsg | None
    candidates: tuple[CandidateMsg, ...]
    lost: tuple[TrackLostMsg, ...]


@dataclass(frozen=True, slots=True)
class PipelineStats:
    """`heartbeat`(§2.4)가 읽는 계측값."""

    cls_calls: int
    cls_cache_hit_rate: float
    cls_gated_small: int
    """크기 게이트에 걸려 안전모 판정을 못 한 횟수. **드러나야 하는 수치다** —
    카메라가 멀면 판정이 통째로 사라지는데 그 사실이 조용하면 「위반 없음」으로 읽힌다."""
    depth_calls: int


@dataclass(slots=True)
class _PersonState:
    """사람 한 트랙의 이어지는 상태. 프레임 사이에 남아야 하는 것만 둔다."""

    stillness: StillnessTracker
    in_zone: bool = False
    helmet: HelmetState | None = None
    """마지막으로 **채택된** 판정. 게이트 미통과 시 이 값을 유지한다(§6.3)."""


class CameraPipeline:
    """카메라 한 대의 처리 루프. 모델과 추적기를 소유한다."""

    def __init__(
        self,
        *,
        cam_id: int,
        config: EdgeConfig,
        letterbox: Letterbox,
        detector: Detector,
        classifier: HelmetClassifier,
        depth: DepthEstimator | None,
    ) -> None:
        self._cam_id = cam_id
        self._config = config
        self._letterbox = letterbox
        self._detector = detector
        self._classifier = classifier
        self._depth = depth
        self._tracker = Tracker(
            high_conf=config.track.high_conf,
            low_conf=config.track.low_conf,
            match_iou=config.track.match_iou,
            buffer_frames=config.track.buffer_frames,
        )
        self._policies = Policies()
        self._setup = CameraSetup()
        self._danger_radius_m = self._policies.vehicle_danger_radius_m
        self._persons: dict[int, _PersonState] = {}
        self._observed_since: dict[tuple[int, str], float] = {}
        self._vehicle_history: dict[int, tuple[float, PointM]] = {}
        self._depth_cache = DepthCache(
            ttl_s=self._policies.depth_cache_ms / 1000.0,
            move_invalidate_m=_DEPTH_MOVE_INVALIDATE_M,
        )

    # -- 서버 설정 ---------------------------------------------------------

    def apply(self, setup: Setup) -> None:
        """서버에서 받은 설정을 반영한다. 캘리브레이션이 바뀌면 여기서 갈린다."""
        self._policies = setup.policies
        self._setup = setup.cameras.get(self._cam_id, CameraSetup())
        self._danger_radius_m = setup.danger_for("vehicle", setup.policies.vehicle_danger_radius_m)
        self._depth_cache = DepthCache(
            ttl_s=setup.policies.depth_cache_ms / 1000.0,
            move_invalidate_m=_DEPTH_MOVE_INVALIDATE_M,
        )

    @property
    def ready(self) -> bool:
        """호모그래피가 있어야 돈다. 없으면 거리도 구역도 낼 수 없다."""
        return self._setup.ready

    def stats(self) -> PipelineStats:
        return PipelineStats(
            cls_calls=self._classifier.calls,
            cls_cache_hit_rate=self._classifier.cache_hit_rate,
            cls_gated_small=self._classifier.gated_small,
            depth_calls=self._depth.calls if self._depth is not None else 0,
        )

    # -- 처리 --------------------------------------------------------------

    def process(
        self,
        frame_bgr: npt.NDArray[np.uint8],
        *,
        ts: datetime,
        at_s: float,
    ) -> FrameOutput:
        """프레임 한 장을 처리한다. `at_s` 는 단조 시계의 초(타이머용)."""
        homography = self._setup.homography
        if homography is None:
            return FrameOutput(frame=None, candidates=(), lost=())

        detections = [
            item for item in self._detector(frame_bgr) if item.conf >= self._policies.min_confidence
        ]
        observed, lost = self._tracker.update(detections)

        persons = {
            track_id: item for track_id, item in observed.items() if item.object_class == "person"
        }
        vehicles = {
            track_id: item for track_id, item in observed.items() if item.object_class == "vehicle"
        }

        helmets = self._classifier.classify(
            frame_bgr,
            persons,
            at_s=at_s,
            min_crop_px=self._policies.cls_min_crop_px,
            min_conf=self._policies.cls_min_conf,
            cache_ms=self._policies.cls_cache_ms,
        )
        if self._depth is not None:
            self._depth.bind(frame_bgr)

        vehicle_objects = self._vehicles(vehicles, homography, at_s)
        person_objects, candidates = self._persons_and_candidates(
            persons, vehicles, vehicle_objects, helmets, homography, ts=ts, at_s=at_s
        )

        objects: list[DetectedObject] = [*person_objects, *vehicle_objects.values()]
        self._forget(lost)
        return FrameOutput(
            # ★ `type` 을 명시한다. 기본값이 있어도 `exclude_unset` 이 **설정되지 않은
            # 필드를 빼므로**, 생략하면 판별자가 없는 메시지가 나가 서버가 전량 거부한다
            # (실제로 36건이 거부됐다 — FN-SYS-06 이 그것을 드러냈다).
            frame=FrameMsg(type="frame", cam_id=self._cam_id, ts=ts, objects=objects),
            candidates=tuple(candidates),
            lost=tuple(self._lost_messages(lost, homography, ts=ts)),
        )

    # -- 지게차 ------------------------------------------------------------

    def _vehicles(
        self,
        vehicles: dict[int, Detection],
        homography: Homography,
        at_s: float,
    ) -> dict[int, DetectedVehicle]:
        """지게차는 지면 주행 장비라 접점이 명확하다 — 마스크 하단이 `anchor` 다(§2.1).

        **bbox 아래변 중앙이 아니다.** 포크가 뻗었거나 적재물이 있으면 박스 중앙과
        어긋나므로, 클라이언트가 추정하지 않도록 엣지가 계산해서 함께 싣는다.
        """
        built: dict[int, DetectedVehicle] = {}
        for track_id, detection in vehicles.items():
            anchor = mask_foot_point(detection.contour)
            anchor_m = self._to_ground(homography, anchor)
            if anchor_m is None:
                continue
            built[track_id] = DetectedVehicle.model_validate(
                {
                    "class": "vehicle",
                    "track_id": track_id,
                    "conf": round(detection.conf, 3),
                    "bbox": _round_bbox(detection.bbox),
                    "anchor": _round_point(anchor),
                    "anchor_m": _round_point(anchor_m),
                    "moving": self._moving(track_id, anchor_m, at_s),
                    "danger_radius_m": self._danger_radius_m,
                }
            )
        return built

    def _moving(self, track_id: int, anchor_m: PointM, at_s: float) -> bool:
        """이동 중인가. 근접 후보의 우선순위(FN-DET-08 ④)와 화면 표시가 읽는다.

        속도로 판정한다 — 프레임 간격이 노트북에서 일정하지 않아(2~3fps) 변위만
        보면 같은 움직임이 프레임률에 따라 다르게 읽힌다.
        """
        previous = self._vehicle_history.get(track_id)
        self._vehicle_history[track_id] = (at_s, anchor_m)
        if previous is None:
            return False
        elapsed = at_s - previous[0]
        if elapsed <= 0.0:
            return False
        moved = float(np.hypot(anchor_m[0] - previous[1][0], anchor_m[1] - previous[1][1]))
        return moved / elapsed >= self._config.track.vehicle_moving_min_speed

    # -- 사람과 후보 -------------------------------------------------------

    def _persons_and_candidates(
        self,
        persons: dict[int, Detection],
        vehicles: dict[int, Detection],
        vehicle_objects: dict[int, DetectedVehicle],
        helmets: dict[int, HelmetReading],
        homography: Homography,
        *,
        ts: datetime,
        at_s: float,
    ) -> tuple[list[DetectedPerson], list[CandidateMsg]]:
        built: list[DetectedPerson] = []
        candidates: list[CandidateMsg] = []

        for track_id, detection in persons.items():
            state = self._persons.setdefault(track_id, _PersonState(stillness=self._stillness()))
            foot = foot_point_from_mask(
                detection.contour,
                bbox=detection.bbox,
                expected_band_pixels=self._config.footpoint.expected_band_pixels,
                max_spread_ratio=self._config.footpoint.max_spread_ratio,
            )
            foot_m = self._to_ground(homography, foot.point)
            if foot_m is None:
                continue

            posture, ratio, angle, stillness_s = self._posture(
                detection, state, foot.point, homography, at_s
            )
            zone_id = self._zone(foot_m, state)
            helmet = self._helmet(track_id, state, helmets)

            readings = self._nearby(
                track_id,
                detection,
                vehicles,
                vehicle_objects,
                homography,
                foot_conf=foot.conf,
                foot_m=foot_m,
                fall_candidate=posture == "fallen",
                at_s=at_s,
            )

            body: dict[str, Any] = {
                "class": "person",
                "track_id": track_id,
                "conf": round(detection.conf, 3),
                "bbox": _round_bbox(detection.bbox),
                "foot_point": _round_point(foot.point),
                "foot_point_m": _round_point(foot_m),
                "foot_conf": round(foot.conf, 3),
                "posture": posture,
                "height_ratio": ratio,
                "axis_angle_deg": angle,
                "stillness_s": stillness_s,
                "in_zone": zone_id,
                "nearby": [
                    {
                        "class": "vehicle",
                        "track_id": reading.track_id,
                        "dist_m": reading.dist_m,
                        "basis": "mask_nearest",
                        "in_danger_zone": reading.within_danger_radius,
                    }
                    for reading in readings
                ],
            }
            if helmet is not None:
                # 셋은 한 묶음이다(§2.1). 게이트를 통과하지 못하면 **셋 다 싣지 않는다** —
                # `exclude_unset` 이 그 생략을 그대로 전선에 반영한다.
                body["helmet"] = helmet.helmet
                body["helmet_conf"] = round(helmet.conf, 3)
                body["helmet_checked_at"] = ts
            person = DetectedPerson.model_validate(body)
            built.append(person)

            candidates.extend(
                self._candidates(
                    track_id,
                    detection,
                    person=person,
                    readings=readings,
                    helmet=helmet.helmet if helmet else state.helmet,
                    zone_id=zone_id,
                    posture=posture,
                    foot_m=foot_m,
                    foot_conf=foot.conf,
                    ts=ts,
                    at_s=at_s,
                )
            )
        return built, candidates

    def _stillness(self) -> StillnessTracker:
        return StillnessTracker(
            move_px=self._policies.stillness_move_px,
            window_s=self._policies.stillness_window_s,
            shape_change_max=self._policies.stillness_shape_change_max,
        )

    def _posture(
        self,
        detection: Detection,
        state: _PersonState,
        foot_point: PointPx,
        homography: Homography,
        at_s: float,
    ) -> tuple[Posture, float, float, float]:
        """세 게이지와 자세. 판정은 `posture_of` 가 한다(FN-DET-10)."""
        shape = mask_shape(detection.contour)
        stillness_s = state.stillness.observe(at_s, shape)
        reference = self._setup.reference
        if reference is None:
            # 기준 인물이 없으면 **기대 높이를 알 수 없다**. 높이 비율을 만들어 내지
            # 않고 `unknown` 으로 둔다 — 0 을 넣으면 그 값이 「매우 낮음」으로 읽혀
            # 서 있는 사람이 쓰러짐 조건 ①을 통과한다.
            return "unknown", 0.0, shape.angle_deg, round(stillness_s, 2)
        reading = posture_of(
            height_ratio=height_ratio(
                shape, foot_point=foot_point, homography=homography, reference=reference
            ),
            axis_angle_deg=shape.angle_deg,
            stillness_s=stillness_s,
            thresholds=FallThresholds(
                height_ratio_max=self._policies.fall_height_ratio_max,
                axis_angle_min_deg=self._policies.fall_axis_angle_min_deg,
                stillness_s=self._policies.fall_stillness_s,
            ),
        )
        return (
            reading.posture,  # type: ignore[return-value]
            reading.height_ratio,
            reading.axis_angle_deg,
            reading.stillness_s,
        )

    def _zone(self, foot_m: PointM, state: _PersonState) -> str | None:
        """구역 판정. 히스테리시스(`buffer_m`)로 경계에서 떨리지 않게 한다(FN-DET-07)."""
        for zone in self._setup.zones:
            inside = zone_state(foot_m, zone, was_inside=state.in_zone)
            if inside:
                state.in_zone = True
                return zone.zone_id
        state.in_zone = False
        return None

    def _helmet(
        self,
        track_id: int,
        state: _PersonState,
        helmets: dict[int, HelmetReading],
    ) -> HelmetReading | None:
        """채택된 판정. 게이트를 통과하지 못하면 `None` 이고 직전 값이 유지된다(§6.3)."""
        reading = helmets.get(track_id)
        if reading is not None:
            state.helmet = reading.helmet
        return reading

    # -- 근접 --------------------------------------------------------------

    def _nearby(
        self,
        person_track: int,
        person: Detection,
        vehicles: dict[int, Detection],
        vehicle_objects: dict[int, DetectedVehicle],
        homography: Homography,
        *,
        foot_conf: float,
        foot_m: PointM,
        fall_candidate: bool,
        at_s: float,
    ) -> list[NearbyReading]:
        """주변 지게차와의 거리. **확정과 해소가 같은 양을 본다**(§2.1 주석).

        `frame` 과 `candidate` 가 같은 계산을 쓰므로, 엣지가 근접이라고 올린 순간
        서버가 다른 방식으로 재서 해소로 판정하는 일이 생기지 않는다.
        """
        readings: list[NearbyReading] = []
        for vehicle_track, vehicle in vehicles.items():
            built = vehicle_objects.get(vehicle_track)
            if built is None:
                continue
            distance = distance_mask_nearest_m(person.contour, vehicle.contour, homography)
            verified = self._verify_depth(
                person_track,
                vehicle_track,
                person_bbox=person.bbox,
                vehicle_bbox=vehicle.bbox,
                person_m=foot_m,
                vehicle_m=built.anchor_m,
                dist_m=distance,
                foot_conf=foot_conf,
                fall_candidate=fall_candidate,
                at_s=at_s,
            )
            readings.append(
                NearbyReading(
                    track_id=vehicle_track,
                    dist_m=round(distance, 2),
                    method="mask_nearest",
                    moving=built.moving,
                    within_danger_radius=within_radius(distance, built.danger_radius_m),
                    depth_verified=verified,
                )
            )
        return screen_nearby(readings, self._radii())

    def _radii(self) -> ProximityRadii:
        return ProximityRadii(
            screening_m=self._policies.screening_radius_m,
            danger_m=self._danger_radius_m,
            warn_m=self._policies.proximity_threshold_m,
        )

    def _verify_depth(
        self,
        person_track: int,
        vehicle_track: int,
        *,
        person_bbox: Bbox,
        vehicle_bbox: Bbox,
        person_m: PointM,
        vehicle_m: PointM,
        dist_m: float,
        foot_conf: float,
        fall_candidate: bool,
        at_s: float,
    ) -> bool:
        """트리거가 걸렸을 때만 모델을 부른다(§6.6).

        모델이 없으면 **`False` 로 남는다.** 조용히 `True` 로 답하면 검증하지 않은
        근접이 검증된 것으로 기록된다.
        """
        if self._depth is None:
            return False
        triggers = depth_triggers(
            dist_m=dist_m,
            person_bbox=person_bbox,
            vehicle_bbox=vehicle_bbox,
            foot_conf=foot_conf,
            min_foot_conf=self._config.footpoint.min_conf_for_depth,
            band_m=self._policies.depth_band_m,
            fall_candidate=fall_candidate,
        )
        result = verify_depth(
            self._depth,
            self._depth_cache,
            key=(self._cam_id, person_track, vehicle_track),
            at_s=at_s,
            person_bbox=person_bbox,
            vehicle_bbox=vehicle_bbox,
            person_m=person_m,
            vehicle_m=vehicle_m,
            triggers=triggers,
        )
        return result.same_plane

    # -- 후보 --------------------------------------------------------------

    def _candidates(
        self,
        track_id: int,
        detection: Detection,
        *,
        person: DetectedPerson,
        readings: list[NearbyReading],
        helmet: HelmetState | None,
        zone_id: str | None,
        posture: Posture,
        foot_m: PointM,
        foot_conf: float,
        ts: datetime,
        at_s: float,
    ) -> list[CandidateMsg]:
        """규칙에 걸린 유형마다 메시지 하나. **판단이 아니라 규칙 매칭이다.**

        **한 메시지에 유형 하나다**(§2.2). 유형마다 조건 충족 시작 시각이 달라
        `observed_ms` 가 각각의 값을 가져야 하므로 묶지 않는다.
        """
        nearest = proximity_candidate(readings, self._radii())
        matched: dict[str, bool] = {
            ViolationType.NO_HELMET: helmet == "off",
            ViolationType.ZONE_INTRUSION: zone_id is not None,
            ViolationType.PROXIMITY: nearest is not None,
            ViolationType.FALL: posture == "fallen",
        }

        messages: list[CandidateMsg] = []
        for violation, active in matched.items():
            key = (track_id, violation)
            if not active:
                # 조건이 사라지면 관측 시작 시각을 버린다. 다시 걸리면 0부터다.
                self._observed_since.pop(key, None)
                continue
            started = self._observed_since.setdefault(key, at_s)
            body: dict[str, Any] = {
                "type": "candidate",
                "cam_id": self._cam_id,
                "ts": ts,
                "track_id": track_id,
                "violation_type": violation,
                "bbox": _round_bbox(detection.bbox),
                "conf": round(detection.conf, 3),
                "foot_point_m": _round_point(foot_m),
                "observed_ms": int((at_s - started) * 1000.0),
                "zone_id": zone_id if violation == ViolationType.ZONE_INTRUSION else None,
                "nearby": [
                    {
                        "class": "vehicle",
                        "track_id": reading.track_id,
                        "dist_m": reading.dist_m,
                        "method": reading.method,
                        "depth_verified": reading.depth_verified,
                        "moving": reading.moving,
                        "within_danger_radius": reading.within_danger_radius,
                    }
                    for reading in readings
                ],
            }
            if violation == ViolationType.FALL:
                # 쓰러진 사람의 접지점은 의미가 없다(§2.2). 필드를 생략한다.
                body["posture"] = posture
            else:
                body["foot_conf"] = round(foot_conf, 3)
            if violation == ViolationType.NO_HELMET:
                body["helmet"] = helmet
                body["helmet_conf"] = person.helmet_conf
            messages.append(CandidateMsg.model_validate(body))
        return messages

    # -- 소실 --------------------------------------------------------------

    def _lost_messages(
        self,
        lost: list[LostTrack],
        homography: Homography,
        *,
        ts: datetime,
    ) -> list[TrackLostMsg]:
        messages: list[TrackLostMsg] = []
        for item in lost:
            point = mask_foot_point(item.last_detection.contour)
            last_m = self._to_ground(homography, point)
            if last_m is None:
                continue
            body: dict[str, Any] = {
                "type": "track_lost",
                "class": item.object_class,
                "cam_id": self._cam_id,
                "track_id": item.track_id,
                "last_ts": ts,
                "last_foot_point_m": _round_point(last_m),
                "reason": item.reason,
            }
            state = self._persons.get(item.track_id)
            if state is not None and state.helmet is not None:
                body["last_helmet"] = state.helmet
            messages.append(TrackLostMsg.model_validate(body))
        return messages

    def _forget(self, lost: list[LostTrack]) -> None:
        """소실된 트랙의 상태를 버린다. 번호가 재사용될 수 있다."""
        ids = {item.track_id for item in lost}
        if not ids:
            return
        self._classifier.forget(ids)
        for track_id in ids:
            self._persons.pop(track_id, None)
            self._vehicle_history.pop(track_id, None)
        for key in [key for key in self._observed_since if key[0] in ids]:
            self._observed_since.pop(key, None)

    # -- 좌표 --------------------------------------------------------------

    def _to_ground(self, homography: Homography, point: PointPx) -> PointM | None:
        """지면 좌표로. 지평선 위의 점은 대응하는 지면 점이 없다.

        **큰 수를 만들어 내지 않는다.** 그런 좌표가 거리·구역 판정으로 흘러가면
        조용히 틀린 판정이 된다.
        """
        try:
            return homography.to_ground(point)
        except CalibrationError:
            log.debug("cam%d: 지면에 대응하지 않는 점을 건너뛴다 %r", self._cam_id, point)
            return None


def _round_bbox(bbox: Bbox) -> Bbox:
    return (round(bbox[0], 4), round(bbox[1], 4), round(bbox[2], 4), round(bbox[3], 4))


def _round_point(point: PointPx | PointM) -> tuple[float, float]:
    return (round(point[0], 4), round(point[1], 4))
