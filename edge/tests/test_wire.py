"""전선에 나가는 것 — **마스크는 나가지 않는다.**

계약에 마스크 필드가 아예 없으므로 구조적으로 불가능하지만, 그 사실을 테스트로
못박는다. 나중에 "디버깅용으로 잠깐" 마스크를 실으면 대역폭이 수십 배가 되고
대시보드가 그것을 그리기 시작한다 — 사용자가 요구한 것은 **박스만** 보이는 것이다.

`helmet` 생략 규약(§6.3)도 여기서 검증한다. 게이트를 통과하지 못했는데 필드가 실려
나가면 서버가 그것을 판정 결과로 읽어 타이머를 리셋한다 — 명세는 **동결**을 정한다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from aegis_contracts.edge import CandidateMsg, DetectedPerson, FrameMsg

TS = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)

PERSON: dict[str, Any] = {
    "class": "person",
    "track_id": 1,
    "conf": 0.94,
    "bbox": [0.21, 0.31, 0.26, 0.44],
    "foot_point": [0.235, 0.436],
    "foot_point_m": [3.2, 7.4],
    "foot_conf": 0.92,
    "posture": "standing",
    "height_ratio": 0.98,
    "axis_angle_deg": 6.2,
    "stillness_s": 0.0,
    "in_zone": None,
    "nearby": [],
}


def _wire(message: FrameMsg | CandidateMsg) -> dict[str, Any]:
    """실제로 전선에 나가는 JSON. `exclude_unset` 이 생략 규약을 그대로 반영한다."""
    loaded: dict[str, Any] = json.loads(message.model_dump_json(by_alias=True, exclude_unset=True))
    return loaded


def _first_object(objects: list[dict[str, Any]]) -> dict[str, Any]:
    return objects[0]


def _frame(person: dict[str, Any]) -> dict[str, Any]:
    return _wire(
        FrameMsg.model_validate({"type": "frame", "cam_id": 1, "ts": TS, "objects": [person]})
    )


def test_frame_carries_no_mask() -> None:
    frame = FrameMsg.model_validate({"type": "frame", "cam_id": 1, "ts": TS, "objects": [PERSON]})
    text = frame.model_dump_json(by_alias=True)
    assert "mask" not in text
    assert "contour" not in text
    assert "polygon" not in text


def test_person_fields_are_exactly_the_contract() -> None:
    """마스크에서 **계산한 값**만 나간다 — 형상 자체가 아니라."""
    person = DetectedPerson.model_validate(PERSON)
    assert set(_first_object(_frame(PERSON)["objects"])) == set(PERSON)
    assert person.height_ratio == 0.98


def test_helmet_is_omitted_when_the_gate_blocks_it() -> None:
    """★ 크기·신뢰도 게이트 미통과는 **필드 생략**이다. `unknown` 이라는 값은 없다."""
    obj = _first_object(_frame(PERSON)["objects"])
    assert "helmet" not in obj
    assert "helmet_conf" not in obj


def test_helmet_travels_as_a_set_of_three() -> None:
    """실릴 때는 셋이 함께다(§2.1) — 값·신뢰도·판정시각."""
    body = dict(PERSON)
    body["helmet"] = "off"
    body["helmet_conf"] = 0.81
    body["helmet_checked_at"] = TS
    obj = _first_object(_frame(body)["objects"])
    assert {"helmet", "helmet_conf", "helmet_checked_at"} <= set(obj)


def test_nearby_is_always_present_even_when_empty() -> None:
    """★ 빠진 것과 없는 것이 같아 보이면 안 되는 자리다.

    엣지가 이 필드를 빠뜨리면 서버는 「주변에 지게차가 없다」로 읽고 진행 중인
    `proximity` 이벤트를 해소로 판정한다.
    """
    assert _first_object(_frame(PERSON)["objects"])["nearby"] == []


def test_exclude_unset_drops_type_unless_it_is_set() -> None:
    """★ **`type` 은 기본값이 있어도 명시해야 한다.**

    엣지는 `exclude_unset=True` 로 보낸다 — `helmet` 게이트 미통과 시 「필드 자체를
    생략」하는 규약(§6.3)을 그렇게 표현하기 때문이다. 그런데 그 옵션은 **설정하지 않은
    필드를 전부 빼므로**, 기본값에 기대면 판별자인 `type` 이 사라진다.

    실제로 이것 때문에 서버가 36건을 `union_tag_not_found` 로 거부했다. 거부가 조용하지
    않아서(FN-SYS-06) 드러났다 — 이 테스트는 그 회귀를 막는다.
    """
    without = FrameMsg.model_validate({"cam_id": 1, "ts": TS, "objects": []})
    assert "type" not in json.loads(without.model_dump_json(exclude_unset=True))

    with_type = FrameMsg.model_validate({"type": "frame", "cam_id": 1, "ts": TS, "objects": []})
    assert json.loads(with_type.model_dump_json(exclude_unset=True))["type"] == "frame"


def test_candidate_carries_one_violation_type() -> None:
    """한 트랙에 두 유형이 걸리면 메시지를 두 개 보낸다(§2.2). 배열이 아니다."""
    candidate = CandidateMsg.model_validate(
        {
            "cam_id": 1,
            "ts": TS,
            "track_id": 1,
            "violation_type": "no_helmet",
            "bbox": [0.21, 0.31, 0.26, 0.44],
            "conf": 0.94,
            "foot_point_m": [3.2, 7.4],
            "observed_ms": 1200,
            "zone_id": None,
            "helmet": "off",
        }
    )
    assert isinstance(candidate.violation_type, str)
    assert "mask" not in candidate.model_dump_json(by_alias=True)
