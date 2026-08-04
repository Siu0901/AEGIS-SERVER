"""다중 객체 추적 — `track_id` 부여와 소실 통지. FN-DET-03 · API명세서 §2.3

**ByteTrack 의 핵심 착상을 따른다** — 신뢰도가 높은 감지로 먼저 잇고, 남은 트랙을
**낮은 신뢰도 감지로 한 번 더** 이어 본다. 낮은 신뢰도 박스를 버리지 않는 것이
ByteTrack 이 가림에 강한 이유다. 사람이 지게차 뒤로 반쯤 가려지면 신뢰도가 떨어지는데,
그 프레임을 버리면 트랙이 끊기고 진행 중인 이벤트가 `expired` 로 빠진다.

★ **칼만 필터가 없다.** 원논문은 칼만 필터로 다음 위치를 예측하지만 여기서는 직전
두 박스의 차이로 등속 예측만 한다. 노트북 실측 처리율이 초당 2~3프레임이라 예측
모델의 정밀도보다 프레임 간격이 지배적이고, 젯슨(8fps 이상)으로 옮길 때는 ultralytics
의 ByteTrack 구현으로 교체하는 것이 맞다. **이 차이를 숨기지 않는다**(절대규칙 10) —
`edge/README.md` 와 `docs/INDEX.md` 에 남긴다.

**엣지는 판단하지 않는다.** 여기서 하는 일은 번호를 붙이고 끊긴 사실을 알리는 것까지다.
`track_lost` 를 받은 뒤의 유예(15초)·재결합(10초·반경)·`expired` 종결은 전부 서버 몫이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aegis_contracts.enums import ObjectClass, TrackLostReason
from aegis_vision import Bbox, bbox_iou

from .detect import Detection

__all__ = ["LostTrack", "Tracker"]

#: 프레임 가장자리로부터 이 비율 안쪽이면 「화면 밖으로 나갔다」로 본다.
_EDGE_MARGIN = 0.02


@dataclass(frozen=True, slots=True)
class LostTrack:
    """`track_lost` 메시지의 재료. 마지막으로 본 상태를 담는다(§2.3)."""

    track_id: int
    object_class: ObjectClass
    last_bbox: Bbox
    last_detection: Detection
    reason: TrackLostReason


@dataclass(slots=True)
class _State:
    track_id: int
    object_class: ObjectClass
    detection: Detection
    previous_bbox: Bbox | None = None
    misses: int = 0
    low_conf_frames: int = 0
    matched_low_conf: bool = field(default=False)

    def predict(self) -> Bbox:
        """등속 예측. 직전 박스가 없으면 현재 박스 그대로다."""
        current = self.detection.bbox
        if self.previous_bbox is None:
            return current
        return tuple(  # type: ignore[return-value]
            value + (value - old) for value, old in zip(current, self.previous_bbox, strict=True)
        )


class Tracker:
    """카메라 한 대의 추적기. `track_id` 는 카메라 안에서만 유일하다."""

    def __init__(
        self,
        *,
        high_conf: float,
        low_conf: float,
        match_iou: float,
        buffer_frames: int,
    ) -> None:
        self._high_conf = high_conf
        self._low_conf = low_conf
        self._match_iou = match_iou
        self._buffer_frames = buffer_frames
        self._states: dict[int, _State] = {}
        self._next_id = 1

    def update(self, detections: list[Detection]) -> tuple[dict[int, Detection], list[LostTrack]]:
        """한 프레임을 넣고 `{track_id: Detection}` 과 소실 목록을 받는다.

        돌려주는 표에는 **이 프레임에서 실제로 관측된 트랙만** 담긴다. 예측만으로
        박스를 만들어 넣지 않는다 — 엣지가 만들어 낸 좌표가 `frame` 으로 나가면
        서버는 그것을 관측으로 읽고 해소 타이머를 잘못 돌린다.
        """
        high = [item for item in detections if item.conf >= self._high_conf]
        low = [item for item in detections if self._low_conf <= item.conf < self._high_conf]

        observed: dict[int, Detection] = {}
        remaining = dict(self._states)

        # 1단계 — 높은 신뢰도.
        for track_id, detection in _associate(remaining, high, self._match_iou):
            self._absorb(track_id, detection, low_conf=False)
            observed[track_id] = detection
            remaining.pop(track_id, None)

        # 2단계 — 남은 트랙을 낮은 신뢰도 감지로 이어 본다. **새 트랙은 만들지 않는다** —
        # 낮은 신뢰도에서 트랙을 시작하면 잡음이 곧 번호를 얻는다.
        for track_id, detection in _associate(remaining, low, self._match_iou):
            self._absorb(track_id, detection, low_conf=True)
            observed[track_id] = detection
            remaining.pop(track_id, None)

        used = {id(item) for item in observed.values()}
        for detection in high:
            if id(detection) not in used:
                observed[self._start(detection)] = detection

        lost = self._age(remaining)
        return observed, lost

    def drop(self, track_ids: set[int]) -> None:
        """외부에서 트랙을 버린다(카메라 재연결 등). 소실 통지는 발생하지 않는다."""
        for track_id in track_ids:
            self._states.pop(track_id, None)

    def active(self) -> set[int]:
        return set(self._states)

    # -- 내부 --------------------------------------------------------------

    def _start(self, detection: Detection) -> int:
        track_id = self._next_id
        self._next_id += 1
        self._states[track_id] = _State(
            track_id=track_id,
            object_class=detection.object_class,
            detection=detection,
        )
        return track_id

    def _absorb(self, track_id: int, detection: Detection, *, low_conf: bool) -> None:
        state = self._states[track_id]
        state.previous_bbox = state.detection.bbox
        state.detection = detection
        state.misses = 0
        state.low_conf_frames = state.low_conf_frames + 1 if low_conf else 0

    def _age(self, unmatched: dict[int, _State]) -> list[LostTrack]:
        """관측되지 않은 트랙의 나이를 올리고, 버퍼를 넘긴 것을 소실로 낸다."""
        lost: list[LostTrack] = []
        for track_id, state in unmatched.items():
            state.misses += 1
            if state.misses <= self._buffer_frames:
                continue
            self._states.pop(track_id, None)
            lost.append(
                LostTrack(
                    track_id=track_id,
                    object_class=state.object_class,
                    last_bbox=state.detection.bbox,
                    last_detection=state.detection,
                    reason=_reason(state),
                )
            )
        return lost


def _reason(state: _State) -> TrackLostReason:
    """왜 끊겼는가. 서버 재결합 판단과 사후 분석이 읽는다(§2.3).

    화면 밖으로 나간 트랙은 재결합 대상이 아니지만 가려진 트랙은 대상이다 — 그래서
    셋을 뭉뚱그리지 않는다.
    """
    x1, y1, x2, y2 = state.detection.bbox
    far = 1.0 - _EDGE_MARGIN
    if x1 <= _EDGE_MARGIN or y1 <= _EDGE_MARGIN or x2 >= far or y2 >= far:
        return "out_of_view"
    if state.low_conf_frames:
        return "low_conf"
    return "occluded"


def _associate(
    states: dict[int, _State],
    detections: list[Detection],
    match_iou: float,
) -> list[tuple[int, Detection]]:
    """IoU 탐욕 매칭. 같은 클래스끼리만 잇는다.

    **사람과 지게차를 잇지 않는다.** 박스가 겹칠 때 클래스를 무시하면 지게차가
    사람 트랙을 이어받아, 그 순간 사람의 위반 이력이 지게차에 붙는다.

    헝가리안이 아니라 탐욕인 이유는 규모다 — 한 프레임의 객체가 열 개 안쪽이라
    최적 할당과 결과가 사실상 같고, 코드가 짧으면 검증하기 쉽다.
    """
    if not states or not detections:
        return []
    pairs: list[tuple[float, int, int]] = []
    for track_id, state in states.items():
        predicted = state.predict()
        for index, detection in enumerate(detections):
            if detection.object_class != state.object_class:
                continue
            score = bbox_iou(predicted, detection.bbox)
            if score >= match_iou:
                pairs.append((score, track_id, index))

    pairs.sort(key=lambda item: item[0], reverse=True)
    taken_tracks: set[int] = set()
    taken_detections: set[int] = set()
    matched: list[tuple[int, Detection]] = []
    for _, track_id, index in pairs:
        if track_id in taken_tracks or index in taken_detections:
            continue
        taken_tracks.add(track_id)
        taken_detections.add(index)
        matched.append((track_id, detections[index]))
    return matched
