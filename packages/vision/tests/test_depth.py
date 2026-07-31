"""뎁스 온디맨드 — 언제 부르고 얼마나 재사용하는가. FN-DET-11 (API명세서 §6.6)

**모델은 없다.** 여기서 잠그는 것은 트리거 조건과 캐시 규칙이며, 실제 추론은 M9 의
`edge/depth.py` 가 채운다. 그래서 `DepthProbe` 를 결정적인 대역으로 주입한다.

★ **거리 수치가 뎁스에서 나오지 않는다**는 것도 함께 잠근다(절대규칙 4).
`DepthResult` 에는 미터 필드가 아예 없다.
"""

from __future__ import annotations

import pytest

from aegis_vision.depth import (
    DepthCache,
    DepthResult,
    DepthTrigger,
    DepthTriggers,
    bbox_iou,
    depth_triggers,
    verify,
)
from aegis_vision.homography import Bbox, PointM

BAND = (2.0, 3.5)
PERSON = (0.10, 0.40, 0.20, 0.70)
VEHICLE = (0.50, 0.40, 0.70, 0.70)
OVERLAPPING = (0.15, 0.40, 0.35, 0.70)


class CountingProbe:
    """부른 횟수를 세는 대역. 캐시가 실제로 호출을 줄이는지 보려면 이것이 필요하다."""

    def __init__(self, *, same_plane: bool = True) -> None:
        self.calls = 0
        self._same_plane = same_plane

    def measure(self, *, person_bbox: Bbox, vehicle_bbox: Bbox | None) -> DepthResult:
        del person_bbox, vehicle_bbox
        self.calls += 1
        return DepthResult(same_plane=self._same_plane, depth_variance=0.12)


# --- 트리거 ---------------------------------------------------------------


def test_no_trigger_means_no_call() -> None:
    """네 조건 중 어느 것도 걸리지 않으면 모델을 부르지 않는다."""
    triggers = depth_triggers(
        dist_m=1.0,
        person_bbox=PERSON,
        vehicle_bbox=VEHICLE,
        foot_conf=0.9,
        min_foot_conf=0.5,
        band_m=BAND,
    )
    assert not triggers
    assert triggers.reasons == ()


@pytest.mark.parametrize("dist", [2.0, 2.8, 3.5])
def test_grey_band_triggers_including_the_boundaries(dist: float) -> None:
    """A — 회색지대. 경계값을 밖으로 보면 임계 근처가 검증 사각지대가 된다."""
    triggers = depth_triggers(dist_m=dist, min_foot_conf=0.5, band_m=BAND)
    assert DepthTrigger.GRAY_BAND in triggers.reasons


def test_overlap_triggers_at_any_overlap() -> None:
    """B — IoU > 0. 1픽셀이라도 겹치면 앞뒤 관계를 화면만으로는 알 수 없다."""
    assert bbox_iou(PERSON, VEHICLE) == 0.0
    assert bbox_iou(PERSON, OVERLAPPING) > 0.0
    triggers = depth_triggers(
        dist_m=1.0,
        person_bbox=PERSON,
        vehicle_bbox=OVERLAPPING,
        min_foot_conf=0.5,
        band_m=BAND,
    )
    assert triggers.reasons == (DepthTrigger.OVERLAP,)


def test_low_foot_confidence_triggers() -> None:
    """C — 접지점을 못 믿으면 그 거리도 못 믿는다."""
    triggers = depth_triggers(dist_m=1.0, foot_conf=0.4, min_foot_conf=0.5, band_m=BAND)
    assert triggers.reasons == (DepthTrigger.LOW_FOOT_CONF,)


def test_fall_candidate_triggers() -> None:
    """D — 쓰러짐 3조건 충족 시 깊이 분산으로 자세를 보강한다(FN-DET-10)."""
    triggers = depth_triggers(dist_m=1.0, min_foot_conf=0.5, band_m=BAND, fall_candidate=True)
    assert triggers.reasons == (DepthTrigger.FALL_CANDIDATE,)


def test_every_reason_is_collected() -> None:
    """첫 조건에서 끊으면 왜 실행됐는지 로그로 구분할 수 없다."""
    triggers = depth_triggers(
        dist_m=2.5,
        person_bbox=PERSON,
        vehicle_bbox=OVERLAPPING,
        foot_conf=0.2,
        min_foot_conf=0.5,
        band_m=BAND,
        fall_candidate=True,
    )
    assert len(triggers.reasons) == 4


def test_inverted_band_is_refused() -> None:
    with pytest.raises(ValueError, match="뒤집혔다"):
        depth_triggers(dist_m=1.0, min_foot_conf=0.5, band_m=(3.5, 2.0))


# --- 실행과 캐시 -----------------------------------------------------------

KEY = (1, 3, 11)


def _cache() -> DepthCache:
    return DepthCache(ttl_s=0.5, move_invalidate_m=0.5)


def _verify(
    probe: CountingProbe,
    cache: DepthCache,
    *,
    at_s: float,
    person_m: PointM = (4.0, 8.0),
    vehicle_m: PointM = (6.0, 8.0),
    triggers: DepthTriggers | None = None,
) -> DepthResult:
    return verify(
        probe,
        cache,
        key=KEY,
        at_s=at_s,
        person_bbox=PERSON,
        vehicle_bbox=VEHICLE,
        person_m=person_m,
        vehicle_m=vehicle_m,
        # 빈 `DepthTriggers` 는 falsy 라 `or` 로 기본값을 고르면 안 된다 — 「트리거
        # 없음」을 넘기려는 테스트가 조용히 회색지대로 바뀐다.
        triggers=depth_triggers(dist_m=2.5, min_foot_conf=0.5, band_m=BAND)
        if triggers is None
        else triggers,
    )


def test_not_running_reports_false_not_true() -> None:
    """★ §6.6 — 「트리거 미충족으로 미실행」도 `false` 다.

    조용히 `True` 로 답하면 검증하지 않은 근접이 검증된 것으로 기록된다.
    """
    probe = CountingProbe()
    result = _verify(
        probe,
        _cache(),
        at_s=0.0,
        triggers=depth_triggers(dist_m=1.0, min_foot_conf=0.5, band_m=BAND),
    )
    assert probe.calls == 0
    assert result.same_plane is False


def test_result_is_reused_within_the_ttl() -> None:
    """§6.6 — 같은 쌍은 0.5초 동안 재사용한다. 8fps 면 프레임 4장에 호출 1회다."""
    probe, cache = CountingProbe(), _cache()
    for step in range(4):
        _verify(probe, cache, at_s=step * 0.1)
    assert probe.calls == 1


def test_result_expires_after_the_ttl() -> None:
    probe, cache = CountingProbe(), _cache()
    _verify(probe, cache, at_s=0.0)
    _verify(probe, cache, at_s=0.6)
    assert probe.calls == 2


def test_movement_invalidates_immediately() -> None:
    """★ §6.6 — 어느 한쪽이 임계 이상 움직이면 즉시 무효다.

    움직였다면 그 앞뒤 판정은 **다른 장면의 것**이다. 시간이 남았다는 이유로 재사용하면
    지게차가 지나간 뒤에도 「근접 확정」이 유지된다.
    """
    probe, cache = CountingProbe(), _cache()
    _verify(probe, cache, at_s=0.0)
    _verify(probe, cache, at_s=0.1, vehicle_m=(6.6, 8.0))
    assert probe.calls == 2


def test_forgetting_a_track_drops_its_pairs() -> None:
    """트랙이 끊겼다 — 같은 번호를 받은 새 트랙이 남의 판정을 물려받으면 안 된다."""
    probe, cache = CountingProbe(), _cache()
    _verify(probe, cache, at_s=0.0)
    assert cache.size == 1
    cache.forget(cam_id=1, track_id=11)
    assert cache.size == 0
    _verify(probe, cache, at_s=0.1)
    assert probe.calls == 2


def test_depth_result_carries_no_distance() -> None:
    """★ 절대규칙 4 — 거리 수치는 호모그래피에서만 나온다.

    뎁스가 미터를 낼 수 있게 되는 순간 누군가 그것을 쓴다. 필드를 두지 않는 것이
    「쓰지 마라」보다 강하다.
    """
    fields = set(DepthResult.__dataclass_fields__)
    assert fields == {"same_plane", "depth_variance"}
    assert not [name for name in fields if name.endswith("_m")]


def test_cache_rejects_degenerate_settings() -> None:
    with pytest.raises(ValueError, match="0보다"):
        DepthCache(ttl_s=0.0, move_invalidate_m=0.5)
