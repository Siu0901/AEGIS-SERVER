"""이벤트 상태머신 — **M2 범위는 FN-EVT-01(후보 수신 및 중복 병합)뿐이다.**

확정(FN-EVT-02 · `confirm_duration_s`) · 해소(FN-EVT-03) · 쿨다운(FN-EVT-04) ·
소실 유예와 재결합(FN-EVT-07)은 M3 에서 이 모듈에 붙는다. 지금은 후보를 받아
`status = "candidate"` 인 이벤트를 만들거나 기존 것에 병합하는 데까지만 한다.

**I/O 가 없다**(CLAUDE.md 절대규칙 2). 여기서 나오는 것은 "무엇을 만들고 무엇을
갱신할지"라는 판단이고, 실제 저장은 `server/infra/db/repository.py` 가 한다.

FN-EVT-01 의 병합 키는 **`cam_id` + `track_id` + 위반 유형** 셋이다(기능명세서 §4.2).
후보 메시지 하나에는 위반 유형이 하나만 담기므로(§2.2) 후보 한 건은 이벤트 한 건에
대응한다. 한 트랙에 유형이 여럿 걸리면 후보가 유형 수만큼 따로 오고, 이벤트도 그만큼
갈린다 — 안전모 미착용과 구역 침입은 시정 행동도 규정 조항도 달라서 한 건으로 묶으면
시정률의 의미가 무너진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aegis_contracts import CandidateMsg, EventDetail, EventSummary
from aegis_contracts.enums import EventStatus, ViolationType

__all__ = [
    "EVENT_ID_PREFIX",
    "CandidatePlan",
    "build_candidate_event",
    "format_event_id",
    "merge_changes",
    "plan_candidate",
]

#: 이벤트 ID 접두사. 기능명세서 §6 — `EV-YYYYMMDD-NNNN`.
EVENT_ID_PREFIX = "EV"


@dataclass(frozen=True, slots=True)
class CandidatePlan:
    """후보 한 건을 어떻게 처리할지. 위반 유형 단위로 갈린다."""

    creates: tuple[ViolationType, ...]
    """진행 중인 이벤트가 없어 새로 만들 위반 유형."""

    updates: tuple[tuple[ViolationType, str], ...]
    """이미 있어 갱신할 (위반 유형, `event_id`). **새로 만들지 않는다**(FN-EVT-01)."""


def plan_candidate(
    candidate: CandidateMsg,
    open_events: dict[ViolationType, str],
) -> CandidatePlan:
    """FN-EVT-01 — 후보를 진행 중 이벤트에 병합하거나 새로 만든다.

    Args:
        candidate: 엣지가 올린 후보(§2.2). **위반 유형 하나를 나른다.**
        open_events: 같은 `cam_id` · `track_id` 에 대해 이미 진행 중인
            {위반 유형: `event_id`}. 조회는 호출자(저장소)가 한다.

    한 트랙에 유형이 여럿 걸리면 후보 메시지가 유형 수만큼 따로 온다(§2.2). 그래도
    이벤트는 유형별로 갈린다 — 안전모 미착용과 구역 침입은 시정 행동도 규정 조항도
    달라서 한 건으로 묶으면 시정률의 의미가 무너진다.
    """
    violation = candidate.violation
    existing = open_events.get(violation)
    if existing is None:
        return CandidatePlan(creates=(violation,), updates=())
    return CandidatePlan(creates=(), updates=((violation, existing),))


def format_event_id(at: datetime, sequence: int) -> str:
    """`EV-YYYYMMDD-NNNN`. 기능명세서 §6

    날짜는 **UTC** 기준이다 — 저장이 UTC 이므로(§1.2) 로컬 자정으로 끊으면 같은
    날짜 접두사가 서로 다른 두 날에 걸친다.
    """
    return f"{EVENT_ID_PREFIX}-{at.strftime('%Y%m%d')}-{sequence:04d}"


def build_candidate_event(
    candidate: CandidateMsg,
    violation: ViolationType,
    event_id: str,
) -> EventDetail:
    """후보에서 **아직 확정되지 않은** 이벤트 레코드 하나를 만든다. FN-REC-04

    `status` 는 `candidate` 에 머문다. 확정 판정은 M3 이므로 `confirmed_at` ·
    `alerted_at` 은 `null` 이고, 그 자리를 지금 채우면 시정률의 분모가 오염된다.

    `detected_at` 은 **후보를 관측한 시각**(`candidate.ts`)이지 서버가 받은 시각이
    아니다 — 서버 수신 시각을 쓰면 네트워크 지연이 시정 소요 시간에 섞인다(§4.1).
    """
    return EventDetail(
        event_id=event_id,
        cam_id=candidate.cam_id,
        track_id=candidate.track_id,
        violation_type=violation,
        zone_id=candidate.zone_id,
        status=EventStatus.CANDIDATE,
        detected_at=candidate.ts,
        confirmed_at=None,
        alerted_at=None,
        resolved_at=None,
        resolution_sec=None,
        alert_count=0,
        min_distance_m=_min_distance(candidate),
        posture=candidate.posture,
        # FN-EVT-06(반복 위반 집계)은 M4 다. 읽을 때 저장소가 세어 채운다.
        repeat_count_7d=0,
        thumbnail_url=None,
        clip_url=None,
        keyframe_urls=[],
        helmet_conf=candidate.helmet_conf,
        stillness_s=None,
        height_ratio=None,
        depth_verified=_depth_verified(candidate),
        nearby_snapshot=[],
        llm_analysis=None,
        regulation_refs=[],
        similar_incidents=[],
        timeline=[],
    )


def merge_changes(existing: EventSummary, candidate: CandidateMsg) -> dict[str, Any]:
    """FN-EVT-01 — 진행 중 이벤트에 후보를 병합할 때 **실제로 달라진 것만** 돌려준다.

    바뀐 것이 없으면 빈 dict 다. 후보는 초당 여러 번 오므로 매번 같은 값을 다시 쓰면
    DB 가 후보 빈도만큼 갱신 부하를 받는다.

    `min_distance_m` 은 덮어쓰지 않고 **더 작은 값으로만** 내린다 — 이벤트가 살아 있는
    동안 얼마나 가까웠는지가 위험도의 근거이고(§4.1), 마지막 값으로 덮으면 지게차가
    멀어진 뒤에는 위험했던 사실이 사라진다.

    `zone_id` 는 반대로 **확정되면 얼어붙는다**(§4.2). 두 필드가 다르게 동작하는 이유는
    묻는 질문이 다르기 때문이다 — "얼마나 위험했나"는 구간 전체의 최댓값이고,
    "어디서 확정됐나"는 한 순간의 사실이다.
    """
    changes: dict[str, Any] = {}

    # `events.zone_id` 는 **확정 시점의 구역을 기록하고 이후 바꾸지 않는다**(기능명세서 §4.2).
    # 확정 전(`candidate`)에는 최신 관측값으로 따라가되, 확정 이후에는 "어디서 확정됐는가"를
    # 고정된 사실로 남긴다 — 위반자가 구역을 나간 뒤 그 이벤트의 구역까지 바뀌면
    # 구역별 집계(§4.2 분포)가 사후에 흔들린다.
    if existing.status == EventStatus.CANDIDATE and existing.zone_id != candidate.zone_id:
        changes["zone_id"] = candidate.zone_id

    distance = _min_distance(candidate)
    closest = existing.min_distance_m
    if distance is not None and (closest is None or distance < closest):
        changes["min_distance_m"] = distance

    if candidate.posture is not None and candidate.posture != existing.posture:
        changes["posture"] = candidate.posture

    return changes


def _min_distance(candidate: CandidateMsg) -> float | None:
    """가장 가까운 지게차까지의 거리. 주변에 없으면 `null`.

    0.0 으로 채우지 않는다 — "붙어 있었다"와 "잴 대상이 없었다"는 다른 사실이다.
    """
    if not candidate.nearby:
        return None
    return min(vehicle.dist_m for vehicle in candidate.nearby)


def _depth_verified(candidate: CandidateMsg) -> bool | None:
    """뎁스로 앞뒤 분리를 확인했는가. 잴 대상이 없었으면 `null`.

    §2.2 는 트리거 미충족으로 **미실행**일 때도 `false` 를 싣게 한다. 그 `false` 는
    그대로 옮기고, `nearby` 자체가 비었을 때만 `null` 이다.
    """
    if not candidate.nearby:
        return None
    return any(vehicle.depth_verified for vehicle in candidate.nearby)
