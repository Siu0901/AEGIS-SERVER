"""추적 — 번호 유지와 소실 통지. FN-DET-03 · API명세서 §2.3

**엣지는 판단하지 않는다.** 여기서 검증하는 것은 번호를 잇는 규칙과 끊긴 사실을
알리는 시점까지이며, 유예·재결합·`expired` 종결은 서버 몫이다.
"""

from __future__ import annotations

from aegis_contracts.enums import ObjectClass
from aegis_vision import Bbox
from edge.detect import Detection
from edge.track import Tracker


def _detection(bbox: Bbox, *, conf: float = 0.9, cls: ObjectClass = "person") -> Detection:
    x1, y1, x2, y2 = bbox
    return Detection(
        object_class=cls,
        conf=conf,
        bbox=bbox,
        contour=((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
        box_height_px=(y2 - y1) * 360,
    )


def _tracker(buffer_frames: int = 2) -> Tracker:
    return Tracker(high_conf=0.5, low_conf=0.2, match_iou=0.25, buffer_frames=buffer_frames)


def test_same_object_keeps_its_number() -> None:
    tracker = _tracker()
    first, _ = tracker.update([_detection((0.30, 0.30, 0.40, 0.60))])
    second, _ = tracker.update([_detection((0.31, 0.30, 0.41, 0.60))])
    assert list(first) == list(second)


def test_low_confidence_frame_keeps_the_track_alive() -> None:
    """★ ByteTrack 의 핵심. 가려져 신뢰도가 떨어진 프레임을 버리지 않는다.

    버리면 트랙이 끊기고 진행 중인 이벤트가 `expired` 로 빠진다 — 지게차 뒤로
    반쯤 가려지는 것은 현장에서 늘 일어나는 일이다.
    """
    tracker = _tracker()
    observed, _ = tracker.update([_detection((0.30, 0.30, 0.40, 0.60))])
    track_id = next(iter(observed))

    faded, lost = tracker.update([_detection((0.31, 0.30, 0.41, 0.60), conf=0.3)])
    assert not lost
    assert list(faded) == [track_id]


def test_low_confidence_alone_does_not_start_a_track() -> None:
    """잡음이 번호를 얻으면 안 된다 — 2단계 연결은 **잇기만** 한다."""
    observed, lost = _tracker().update([_detection((0.30, 0.30, 0.40, 0.60), conf=0.3)])
    assert not observed
    assert not lost


def test_classes_are_never_crossed() -> None:
    """박스가 겹쳐도 사람과 지게차를 잇지 않는다.

    이으면 그 순간 사람의 위반 이력이 지게차에 붙는다.
    """
    tracker = _tracker()
    person, _ = tracker.update([_detection((0.30, 0.30, 0.40, 0.60))])
    vehicle, _ = tracker.update([_detection((0.30, 0.30, 0.40, 0.60), cls="vehicle")])
    assert set(person).isdisjoint(vehicle)


def test_track_lost_only_after_the_buffer() -> None:
    """버퍼 안의 짧은 단절은 통지하지 않는다(§2.3)."""
    tracker = _tracker(buffer_frames=2)
    observed, _ = tracker.update([_detection((0.30, 0.30, 0.40, 0.60))])
    track_id = next(iter(observed))

    assert tracker.update([])[1] == []
    assert tracker.update([])[1] == []
    lost = tracker.update([])[1]
    assert [item.track_id for item in lost] == [track_id]


def test_edge_exit_is_reported_as_out_of_view() -> None:
    """화면 밖으로 나간 트랙은 재결합 대상이 아니다 — 이유를 구분해서 보낸다."""
    tracker = _tracker(buffer_frames=0)
    tracker.update([_detection((0.0, 0.30, 0.08, 0.60))])
    lost = tracker.update([])[1]
    assert [item.reason for item in lost] == ["out_of_view"]


def test_middle_of_frame_disappearance_is_occlusion() -> None:
    tracker = _tracker(buffer_frames=0)
    tracker.update([_detection((0.40, 0.40, 0.50, 0.70))])
    lost = tracker.update([])[1]
    assert [item.reason for item in lost] == ["occluded"]


def test_faded_track_is_reported_as_low_conf() -> None:
    tracker = _tracker(buffer_frames=0)
    tracker.update([_detection((0.40, 0.40, 0.50, 0.70))])
    tracker.update([_detection((0.40, 0.40, 0.50, 0.70), conf=0.3)])
    lost = tracker.update([])[1]
    assert [item.reason for item in lost] == ["low_conf"]


def test_no_predicted_boxes_are_emitted() -> None:
    """**관측된 트랙만 돌려준다.**

    예측만으로 박스를 만들어 내보내면 서버가 그것을 관측으로 읽어 해소 타이머를
    잘못 돌린다 — 사라진 사람이 계속 서 있는 것으로 보인다.
    """
    tracker = _tracker(buffer_frames=5)
    tracker.update([_detection((0.40, 0.40, 0.50, 0.70))])
    observed, _ = tracker.update([])
    assert observed == {}


def test_two_people_keep_separate_numbers() -> None:
    tracker = _tracker()
    first, _ = tracker.update(
        [_detection((0.10, 0.30, 0.20, 0.60)), _detection((0.60, 0.30, 0.70, 0.60))]
    )
    second, _ = tracker.update(
        [_detection((0.11, 0.30, 0.21, 0.60)), _detection((0.61, 0.30, 0.71, 0.60))]
    )
    assert len(first) == 2
    assert set(first) == set(second)
