"""`frame` → `overlay` 합성. API명세서 §5.1 · FN-UI-02

**`frame` 을 그대로 흘려보내지 않는다.** 서버가 진행 중인 이벤트 상태와 근접 거리를
합쳐서 내려보낸다 — 클라이언트가 위반 여부를 스스로 추론하지 않게 하기 위함이고,
FN-UI-02 표시 규칙(위반자 적색 · 근접 거리선 · 거리 라벨)을 채우려면 이 정보가 필요하다.

**I/O 가 없다**(CLAUDE.md 절대규칙 2).

M2 의 범위에서 유의할 것:

* `alert_state` 는 M2 에서 대부분 **`candidate`** 다. 확정 판정이 M3 이기 때문이다.
  `candidate` 와 `null` 은 다르다 — 전자는 위반 조건이 관측됐으나 확정 전, 후자는
  이 트랙에 진행 중 이벤트가 아예 없다는 뜻이다(§5.1).
* 위반 표시는 후보가 들어온 순간부터 켜지고 **꺼지지 않는다.** 해소 판정
  (FN-EVT-03)이 M3 이기 때문이다. 지금 임의의 시간으로 끄면 그 값이 곧 가짜
  시정률이 된다 — 트랙이 사라질 때만 지운다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aegis_contracts import (
    CandidateMsg,
    DetectedPerson,
    DetectedVehicle,
    FrameMsg,
    NearbyVehicle,
    OverlayMsg,
    OverlayNearby,
    OverlayObject,
    OverlayPerson,
    OverlayVehicle,
    PointPx,
)
from aegis_contracts.enums import AlertState, EventStatus, ViolationType

__all__ = ["LiveTracks", "TrackState", "compose_overlay"]

#: `EventStatus` → `AlertState`. 오버레이에는 **진행 중**인 값만 실린다(§5.1).
#:
#: 종결 상태(`resolved` · `expired`)는 여기 없다 — 그 트랙에는 진행 중 이벤트가
#: 없으므로 `alert_state` 가 `null` 이 된다.
_ALERT_STATE: dict[EventStatus, AlertState] = {
    EventStatus.CANDIDATE: "candidate",
    EventStatus.ACTIVE: "active",
    EventStatus.ALERTED: "alerted",
    EventStatus.RE_ALERTED: "re_alerted",
    EventStatus.LOST: "lost",
}

#: `alert_state` 우선순위. 한 트랙에 유형이 여럿이면 **가장 앞선 단계**를 싣는다.
#:
#: 박스는 트랙당 하나뿐이라 상태도 하나여야 하는데, dict 순회 순서(= 위반이 걸린
#: 순서)로 고르면 같은 상황에서 실행마다 다른 값이 나온다. 경고까지 간 위반이 있으면
#: 그것이 이긴다 — 확정 전 후보 때문에 경고 표시가 내려가면 안 된다.
_ALERT_RANK: dict[AlertState, int] = {
    "candidate": 0,
    "active": 1,
    "lost": 2,
    "alerted": 3,
    "re_alerted": 4,
}


@dataclass(slots=True)
class TrackState:
    """트랙 하나에 붙어 있는 이벤트 상태. `overlay` 를 채우는 재료다."""

    events: dict[ViolationType, str] = field(default_factory=dict)
    """{위반 유형: `event_id`} — 진행 중인 것만."""

    statuses: dict[ViolationType, EventStatus] = field(default_factory=dict)

    nearby: tuple[NearbyVehicle, ...] = ()
    """마지막 후보가 실어 보낸 주변 지게차(§2.2). 거리선의 원천이다."""

    @property
    def violations(self) -> list[ViolationType]:
        return list(self.events)

    @property
    def event_ids(self) -> list[str]:
        return list(self.events.values())

    @property
    def alert_state(self) -> AlertState | None:
        """가장 앞선 경고 단계 하나. 진행 중 이벤트가 없으면 `null`(§5.1)."""
        states = [
            _ALERT_STATE[status] for status in self.statuses.values() if status in _ALERT_STATE
        ]
        if not states:
            return None
        best: AlertState = states[0]
        for state in states[1:]:
            if _ALERT_RANK[state] > _ALERT_RANK[best]:
                best = state
        return best


class LiveTracks:
    """카메라별 트랙 상태 보관. `/ws/edge` 가 쓰고 `overlay` 가 읽는다."""

    def __init__(self) -> None:
        self._tracks: dict[tuple[int, int], TrackState] = {}

    def state(self, cam_id: int, track_id: int) -> TrackState | None:
        return self._tracks.get((cam_id, track_id))

    def record_candidate(
        self,
        candidate: CandidateMsg,
        events: dict[ViolationType, tuple[str, EventStatus]],
    ) -> None:
        """후보 처리 결과를 반영한다. `events` 는 이 트랙에 붙은 진행 중 이벤트 전량."""
        state = self._tracks.setdefault((candidate.cam_id, candidate.track_id), TrackState())
        state.events = {violation: event_id for violation, (event_id, _) in events.items()}
        state.statuses = {violation: status for violation, (_, status) in events.items()}
        state.nearby = tuple(candidate.nearby)

    def forget(self, cam_id: int, track_id: int) -> None:
        """트랙이 사라졌다. **새 트랙이 같은 번호를 물려받아도 위반을 이어받지 않도록** 지운다."""
        self._tracks.pop((cam_id, track_id), None)

    def clear(self) -> None:
        """엣지가 끊겼다. 관측 주체가 없으므로 들고 있던 위반 표시를 전부 내린다."""
        self._tracks.clear()


def compose_overlay(frame: FrameMsg, tracks: LiveTracks) -> OverlayMsg:
    """`frame` 한 장에 이벤트 상태를 합쳐 `overlay` 를 만든다. API명세서 §5.1

    지게차의 접지 좌표는 **엣지가 보낸 `anchor` 를 그대로 쓴다**(§2.1). 마스크 하단에서
    산출한 값이라 `bbox` 아래변 중앙과 다르다 — 포크가 뻗었거나 적재물이 있으면 어긋난다.
    """
    anchors = {
        obj.track_id: obj.anchor for obj in frame.objects if isinstance(obj, DetectedVehicle)
    }
    objects: list[OverlayObject] = []
    for obj in frame.objects:
        state = tracks.state(frame.cam_id, obj.track_id)
        if isinstance(obj, DetectedPerson):
            objects.append(_person(obj, state, anchors))
        else:
            objects.append(_vehicle(obj, state))
    return OverlayMsg(cam_id=frame.cam_id, ts=frame.ts, objects=objects)


# `SpecModel` 은 `populate_by_name` 을 켜지 않는다 — `class` 별칭을 가진 모델은
# `model_validate` 로 만든다(계약 패키지 `_base.SpecModel` 주석 참조).


def _person(
    obj: DetectedPerson,
    state: TrackState | None,
    anchors: dict[int, PointPx],
) -> OverlayPerson:
    body: dict[str, object] = {
        "class": "person",
        "track_id": obj.track_id,
        "bbox": obj.bbox,
        "foot_point": obj.foot_point,
        "posture": obj.posture,
        "in_zone": obj.in_zone,
        "violations": state.violations if state else [],
        "event_ids": state.event_ids if state else [],
        "alert_state": state.alert_state if state else None,
        "nearby": _nearby(state, anchors),
    }
    # `helmet` 은 게이트 미통과 시 **필드 자체가 생략**된다(§2.1 · §6.3).
    # `null` 로 채우면 "분류했는데 값이 없다"가 되어 규약이 뒤집힌다.
    if obj.helmet is not None:
        body["helmet"] = obj.helmet
    return OverlayPerson.model_validate(body)


def _vehicle(obj: DetectedVehicle, state: TrackState | None) -> OverlayVehicle:
    del state  # 위반은 사람 트랙에 붙는다(§2.2). 지게차 박스는 앰버 고정이다.
    return OverlayVehicle.model_validate(
        {
            "class": "vehicle",
            "track_id": obj.track_id,
            "bbox": obj.bbox,
            "anchor": obj.anchor,
            "moving": obj.moving,
            "danger_radius_m": obj.danger_radius_m,
            "violations": [],
            "event_ids": [],
            "alert_state": None,
            "nearby": [],
        }
    )


def _nearby(state: TrackState | None, anchors: dict[int, PointPx]) -> list[OverlayNearby]:
    """거리선을 그릴 수 있는 것만 남긴다.

    **이 프레임에 보이지 않는 지게차는 뺀다.** 선의 반대편 끝점을 찍을 수 없으므로
    화면에는 어차피 그릴 수 없고, 거리 라벨만 남기면 아무 데도 안 붙은 숫자가 뜬다.
    """
    if state is None:
        return []
    return [
        OverlayNearby.model_validate(
            {
                "class": "vehicle",
                "track_id": vehicle.track_id,
                "dist_m": vehicle.dist_m,
                "anchor": anchors[vehicle.track_id],
                "in_danger_zone": vehicle.within_danger_radius,
            }
        )
        for vehicle in state.nearby
        if vehicle.track_id in anchors
    ]
