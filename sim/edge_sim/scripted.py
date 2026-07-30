"""시나리오 파일(`sim/cases/*.yaml`)을 시각 순서대로 메시지로 바꾼다.

이 모듈은 **판단하지 않는다.** YAML에 적힌 것을 `aegis_contracts` 스키마로 검증해
그대로 내보낼 뿐이며, 위반 여부·확정·해소는 전부 서버가 정한다.

시나리오 형식:

    name: no_helmet_resolved
    cam_id: 1
    timeline:
      - at: 0.0            # 시작 기준 경과 초
        type: frame        # 나머지 키는 API명세서 §2 메시지 본문 그대로
        cam_id: 1
        objects: [...]

`ts`(`track_lost` 는 `last_ts`)는 적지 않는다. 시작 시각에 `at` 을 더해 주입한다.

**`frame_fps` 를 적으면 `frame` 사이를 채운다.** 실물 엣지는 카메라당 8fps 이상을
올리므로(FN-DET-01), 시나리오에 `frame` 을 그 밀도로 손으로 적으면 30초짜리가
240줄이 되어 사람이 읽을 수 없다. 그래서 시나리오에는 **키프레임만** 적고, 사이는
트랙별 선형 보간으로 생성한다.

    name: no_helmet
    cam_id: 1
    frame_fps: 8          # 없으면 보간하지 않는다 (적힌 frame 만 나간다)

보간하는 것은 **좌표와 게이지뿐**이다(`_LERP_SCALAR` · `_LERP_VECTOR`). `helmet` ·
`posture` · `in_zone` · `moving` 같은 판정·범주 값은 **앞 키프레임 값을 그대로 유지**하고
다음 키프레임에서 한 번에 바뀐다. 사이를 지어내면 시뮬레이터가 판정을 만들어내는
셈이 되고, 그 순간 서버 상태머신 검증이 무의미해진다.

`candidate` · `track_lost` · `heartbeat` 는 보간 대상이 아니다 — 후보를 만들어내는
것은 규칙 판정이고, 그건 시나리오 작성자의 몫이다.

**미터는 시나리오가 적지 않는다 (M6).** 예전에는 `foot_point_m` · `anchor_m` 을 손으로
적었는데, 그러면 픽셀과 미터가 각각 따로 쓰인 두 벌의 좌표가 되어 서로 어긋나도 아무도
모른다(실제로 어긋나 있었다 — `docs/INDEX.md` M6 절). 이제 시나리오에는 **정규화 픽셀만**
적고, `packages/vision` 의 호모그래피로 미터를 계산해 싣는다. 실물 엣지가 하는 일과 같다
(FN-DET-06).

| 시나리오가 적는 것 | 계산해서 싣는 것 |
|---|---|
| `frame` 사람의 `foot_point` | `foot_point_m` |
| `frame` 지게차의 `anchor` | `anchor_m` |
| `candidate` 의 `foot_point` | `foot_point_m` |

카메라별 캘리브레이션은 `scripts/seed_cameras.py` 의 개발용 4점이며 **DB 시드와 같은
상수**다 — 엣지와 서버가 다른 좌표계로 계산하면 거리도 구역도 어긋난다.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import TypeAdapter

from aegis_contracts import EdgeMessage
from aegis_vision import Homography
from scripts.seed_cameras import homography_for

__all__ = ["CASES_DIR", "ScheduledMessage", "load_case", "resolve_case_path", "retime"]

#: 시나리오 파일 디렉토리.
CASES_DIR = Path(__file__).resolve().parent.parent / "cases"

#: 메시지 유형별 타임스탬프 필드 이름. API명세서 §2.
_TS_FIELD: Final[dict[str, str]] = {
    "frame": "ts",
    "candidate": "ts",
    "track_lost": "last_ts",
    "heartbeat": "ts",
}

#: 키프레임 사이를 선형 보간하는 스칼라 필드. API명세서 §2.1
_LERP_SCALAR: Final[frozenset[str]] = frozenset(
    {"conf", "foot_conf", "helmet_conf", "height_ratio", "axis_angle_deg", "stillness_s"}
)

#: 키프레임 사이를 선형 보간하는 좌표 배열 필드. API명세서 §2.1
#:
#: **정규화 픽셀만 보간한다.** 미터는 시나리오가 적지 않고 호모그래피로 계산되므로
#: (`_with_ground_coordinates`), 보간한 픽셀에서 다시 계산하면 원근이 그대로 반영된다.
#: 미터를 직접 보간하면 화면에서 등속으로 걷는 사람이 지면에서는 등속이 아니게 된다.
#:
#: `danger_radius_m` 은 여기 없다 — 설정값이지 관측값이 아니라서 프레임마다 변하지 않는다.
_LERP_VECTOR: Final[frozenset[str]] = frozenset({"bbox", "foot_point", "anchor"})

#: 보간 결과 자릿수. 정규화 좌표는 1e-4 면 1920px 에서 0.2px 미만이라 충분하다.
_ROUND = 4

_ADAPTER: TypeAdapter[Any] = TypeAdapter(EdgeMessage)


@dataclass(frozen=True, slots=True)
class ScheduledMessage:
    """`at_s` 초 뒤에 보낼 메시지 하나."""

    at_s: float
    message: Any
    """`aegis_contracts.EdgeMessage` 판별 유니온의 인스턴스."""


def resolve_case_path(case: str) -> Path:
    """케이스 이름 또는 경로를 파일 경로로 바꾼다."""
    direct = Path(case)
    if direct.suffix and direct.exists():
        return direct
    candidate = CASES_DIR / f"{case}.yaml"
    if not candidate.exists():
        available = ", ".join(sorted(p.stem for p in CASES_DIR.glob("*.yaml"))) or "(없음)"
        msg = f"시나리오를 찾을 수 없다: {case}  —  사용 가능: {available}"
        raise FileNotFoundError(msg)
    return candidate


def load_case(case: str, start: datetime, speed: float = 1.0) -> list[ScheduledMessage]:
    """시나리오를 읽어 시각 순으로 정렬된 메시지 목록을 만든다.

    Args:
        case: 케이스 이름(`no_helmet_resolved`) 또는 yaml 경로.
        start: `at: 0.0` 에 대응하는 절대 시각. 호출자가 `Clock` 에서 얻어 넘긴다.
        speed: 재생 배속. 시나리오 시각과 `ts` 를 **함께** 나눈다.

    배속을 걸 때 `ts` 를 그대로 두면 좌표가 실제 벽시계보다 앞선 시각을 달고 나가고,
    오버레이 시간 정합(§5 · ±100ms)이 배속만큼 어긋난다. 서버 입장에서는 미래에서
    온 프레임이라 클립 구간 계산도 틀어진다. 그래서 둘을 같은 비율로 압축한다.
    """
    if speed <= 0:
        msg = f"speed 는 0보다 커야 한다: {speed!r}"
        raise ValueError(msg)
    path = resolve_case_path(case)
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"시나리오 최상위는 매핑이어야 한다: {path}"
        raise ValueError(msg)

    timeline: Any = raw.get("timeline")
    if not isinstance(timeline, list):
        msg = f"시나리오에 timeline 리스트가 없다: {path}"
        raise ValueError(msg)

    entries: list[tuple[float, dict[str, Any]]] = []
    for index, entry in enumerate(timeline):
        if not isinstance(entry, dict):
            msg = f"timeline[{index}] 는 매핑이어야 한다: {path}"
            raise ValueError(msg)

        payload: dict[str, Any] = dict(entry)
        at_s = float(payload.pop("at", 0.0))

        kind = payload.get("type")
        if _TS_FIELD.get(str(kind)) is None:
            msg = f"timeline[{index}] 의 type 이 올바르지 않다: {kind!r} ({path})"
            raise ValueError(msg)

        entries.append((at_s, payload))

    entries.sort(key=lambda item: item[0])
    entries += _tween_frames(_frame_fps(raw, path), entries)
    entries.sort(key=lambda item: item[0])

    default_cam = int(raw.get("cam_id", 1))
    scheduled: list[ScheduledMessage] = []
    for at_s, payload in entries:
        played_at = at_s / speed
        # 시각은 시나리오가 적지 않는다. 시작 시각 + 경과로 주입한다.
        body = _with_ground_coordinates(dict(payload), default_cam)
        body[_TS_FIELD[str(body["type"])]] = start + timedelta(seconds=played_at)
        scheduled.append(ScheduledMessage(at_s=played_at, message=_ADAPTER.validate_python(body)))
    return scheduled


def _with_ground_coordinates(payload: dict[str, Any], default_cam: int) -> dict[str, Any]:
    """정규화 픽셀 → 지면 미터. FN-DET-06 (API명세서 §6.2)

    **시나리오가 미터를 적으면 오류다.** 픽셀과 미터를 각각 적으면 두 벌의 좌표가 되어
    서로 어긋나도 아무도 모른다 — 실제로 M6 이전 시나리오들이 그 상태였다. 미터의
    출처는 호모그래피 하나뿐이어야 한다.
    """
    kind = str(payload.get("type"))
    if kind not in {"frame", "candidate"}:
        return payload
    homography = _homography(int(payload.get("cam_id", default_cam)))

    if kind == "candidate":
        # `candidate` 에는 픽셀 접지점 자리가 없다(§2.2 는 `foot_point_m` 만 싣는다).
        # 시나리오가 적은 `foot_point` 는 **변환 입력일 뿐**이므로 메시지에서 뺀다 —
        # 남겨두면 계약에 없는 필드가 실려 나가고, 그건 엣지 결함과 같은 모양이다.
        projected = _project(payload, homography, "foot_point", "foot_point_m")
        return {key: value for key, value in projected.items() if key != "foot_point"}

    objects = [_project(dict(obj), homography, *_fields(obj)) for obj in payload.get("objects", [])]
    return payload | {"objects": objects}


def _fields(obj: dict[str, Any]) -> tuple[str, str]:
    """이 객체가 쓰는 (픽셀 필드, 미터 필드). 사람은 접지점, 지게차는 접점이다(§2.1)."""
    if obj.get("class") == "person":
        return ("foot_point", "foot_point_m")
    return ("anchor", "anchor_m")


def _project(
    payload: dict[str, Any],
    homography: Homography,
    pixel_field: str,
    ground_field: str,
) -> dict[str, Any]:
    if ground_field in payload:
        msg = (
            f"시나리오가 {ground_field} 를 직접 적었다 — 미터는 {pixel_field}(정규화 픽셀)에서 "
            "호모그래피로 계산된다(FN-DET-06). 그 줄을 지워라"
        )
        raise ValueError(msg)
    if pixel_field not in payload:
        return payload
    point = payload[pixel_field]
    ground = homography.to_ground((float(point[0]), float(point[1])))
    return payload | {ground_field: [round(ground[0], 2), round(ground[1], 2)]}


@cache
def _homography(cam_id: int) -> Homography:
    """개발용 캘리브레이션. **DB 시드와 같은 상수**를 쓴다(`scripts/seed_cameras.py`).

    실물 엣지는 이 값을 `edge/config.yaml` 에서 받는다. 시뮬레이터가 다른 값을 쓰면
    서버가 계산하는 구역·거리와 엣지가 보내는 좌표가 서로 다른 평면 위에 놓인다.
    """
    return homography_for(cam_id)


def retime(timeline: list[ScheduledMessage], start: datetime) -> list[ScheduledMessage]:
    """이미 만든 타임라인의 시각만 `start` 기준으로 다시 찍는다.

    **`load_case` 는 비싸고(YAML 파싱 + 보간 + 225건 스키마 검증) `retime` 은 싸다.**
    그래서 파싱은 미리 해 두고, 연결이 맺어진 **직후에** 이걸 불러 `ts` 를 실제 재생
    기준으로 맞춘다.

    이 분리가 없으면 `ts` 기준점과 재생 기준점이 서로 다른 순간에 잡힌다. 그 사이에
    든 시간(파싱 + WebSocket 연결)이 **전 구간에 걸친 고정 오차**로 남아, 좌표가 실제
    송신 시각보다 그만큼 과거를 가리킨다. 클라이언트는 그것을 "좌표가 늦게 온다"로
    보고 박스를 그리지 못한다 — 실측으로 2.8초가 이렇게 생겼다.
    """
    return [
        ScheduledMessage(
            at_s=item.at_s,
            message=item.message.model_copy(
                update={
                    _TS_FIELD[str(item.message.type)]: start + timedelta(seconds=item.at_s),
                }
            ),
        )
        for item in timeline
    ]


def _frame_fps(raw: dict[str, Any], path: Path) -> float | None:
    """`frame_fps` 를 읽는다. 없으면 보간하지 않는다."""
    value: Any = raw.get("frame_fps")
    if value is None:
        return None
    fps = float(value)
    if fps <= 0:
        msg = f"frame_fps 는 0보다 커야 한다: {value!r} ({path})"
        raise ValueError(msg)
    return fps


def _tween_frames(
    fps: float | None,
    entries: list[tuple[float, dict[str, Any]]],
) -> list[tuple[float, dict[str, Any]]]:
    """키프레임 사이를 `fps` 밀도로 채운다. 카메라별로 따로 잇는다.

    양쪽 키프레임에 **모두 있는 트랙만** 보간한다. 한쪽에만 있는 트랙은 등장·퇴장을
    뜻하므로 그 키프레임 시각에 그대로 나타나고 사라진다 — 없는 위치를 지어내지 않는다.
    """
    if fps is None:
        return []

    by_cam: dict[int, list[tuple[float, dict[str, Any]]]] = {}
    for at_s, payload in entries:
        if payload["type"] == "frame":
            by_cam.setdefault(int(payload["cam_id"]), []).append((at_s, payload))

    step = 1.0 / fps
    made: list[tuple[float, dict[str, Any]]] = []
    for keyframes in by_cam.values():
        for (t0, f0), (t1, f1) in itertools.pairwise(keyframes):
            span = t1 - t0
            if span <= step:
                continue
            count = int(span / step)
            for k in range(1, count + 1):
                at_s = t0 + k * step
                if at_s >= t1:
                    break
                made.append((round(at_s, 6), _lerp_frame(f0, f1, (at_s - t0) / span)))
    return made


def _lerp_frame(f0: dict[str, Any], f1: dict[str, Any], u: float) -> dict[str, Any]:
    """`frame` 두 장 사이의 중간 프레임 하나."""
    later = {(obj["class"], obj["track_id"]): obj for obj in f1["objects"]}
    objects = [
        _lerp_object(obj, later[(obj["class"], obj["track_id"])], u)
        for obj in f0["objects"]
        if (obj["class"], obj["track_id"]) in later
    ]
    return {"type": "frame", "cam_id": f0["cam_id"], "objects": objects}


def _lerp_object(o0: dict[str, Any], o1: dict[str, Any], u: float) -> dict[str, Any]:
    """좌표·게이지만 섞는다. 판정·범주 값은 앞 키프레임 것을 그대로 쓴다."""
    out = dict(o0)
    for key, value in o0.items():
        if key not in o1:
            continue
        other = o1[key]
        if key in _LERP_SCALAR:
            out[key] = round(value + (other - value) * u, _ROUND)
        elif key in _LERP_VECTOR:
            out[key] = [round(a + (b - a) * u, _ROUND) for a, b in zip(value, other, strict=True)]
    return out
