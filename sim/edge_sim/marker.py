"""marker 검증 모드 — 영상에 태운 사각형과 **같은 궤적**의 person 좌표를 만든다.

    uv run tasks.py cams --marker          # 영상에 사각형을 태운다
    uv run tasks.py sim --mode marker      # 같은 궤적의 좌표를 보낸다

궤적 정의는 `deploy/marker_path.py` **한 곳에만** 있다. 여기서 다시 쓰지 않는다 —
중복 정의하면 두 박스가 어긋났을 때 영상이 틀렸는지 좌표가 틀렸는지 알 수 없어,
정합을 재려던 도구가 오히려 원인을 감춘다.

화면에서 보는 법: 자홍색 사각형(영상)과 청록색 오버레이 박스(좌표)가 겹치면
정합이 맞는 것이다. 가로로 벌어진 거리가 곧 시간 오차이며, 가로 왕복 주기 8초 ·
진폭 0.72 이므로 **정규화 0.01 ≈ 55ms** 다(1920px 기준 19px ≈ 55ms).

**위반을 만들지 않는다.** 안전모를 쓴 정상 작업자 하나만 보낸다 — 이 모드의 목적은
정합 측정이고, 위반 색이 섞이면 겹침 여부를 눈으로 보기 어려워진다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from aegis_contracts import FrameMsg
from deploy.marker_path import BOX_H, BOX_W, position

from .scripted import ScheduledMessage

__all__ = ["DEFAULT_DURATION_S", "DEFAULT_FPS", "MARKER_TRACK_ID", "build", "reproject"]

#: 영상 속 사각형에 대응하는 트랙 번호. 사람이 로그에서 알아보기 쉬운 값으로 둔다.
MARKER_TRACK_ID = 99

#: 기본 재생 길이(초)와 프레임률. 가로 주기 8초 × 여러 바퀴를 볼 수 있게 잡았다.
DEFAULT_DURATION_S = 60.0
DEFAULT_FPS = 8.0


def _frame(cam_id: int, ts: datetime) -> FrameMsg:
    """그 시각의 사각형 위치를 person 하나로 표현한 프레임.

    `bbox` 는 사각형과 **정확히 같은 사각형**이고 `foot_point` 는 그 아래변 중앙이다.
    오버레이가 접지점을 점으로 찍으므로 두 표현이 함께 겹치는지 볼 수 있다.
    """
    cx, cy = position(ts.timestamp())
    x1, x2 = cx - BOX_W / 2, cx + BOX_W / 2
    y1, y2 = cy - BOX_H / 2, cy + BOX_H / 2
    body: dict[str, Any] = {
        "type": "frame",
        "cam_id": cam_id,
        "ts": ts,
        "objects": [
            {
                "class": "person",
                "track_id": MARKER_TRACK_ID,
                "conf": 0.99,
                "bbox": [x1, y1, x2, y2],
                "helmet": "on",
                "helmet_conf": 0.99,
                "foot_point": [cx, y2],
                # 지면 실좌표는 이 모드에서 쓰이지 않는다(구역·거리 판정을 하지 않는다).
                # 그래도 §2.1 필수 필드라 화면 좌표에서 그럴듯하게 만들어 채운다.
                "foot_point_m": [round(cx * 12.0, 3), round((1.0 - y2) * 20.0, 3)],
                "foot_conf": 0.99,
                "posture": "standing",
                "height_ratio": 1.0,
                "axis_angle_deg": 0.0,
                "stillness_s": 0.0,
                "in_zone": None,
                # 이 모드에는 지게차가 없다. **빈 배열도 실어야 한다**(§2.1) —
                # 필드를 빼면 계약 위반이고, 서버는 "주변에 없다"를 해소 근거로 쓴다.
                "nearby": [],
            }
        ],
    }
    return FrameMsg.model_validate(body)


def build(
    start: datetime,
    *,
    cam_id: int = 1,
    duration_s: float = DEFAULT_DURATION_S,
    fps: float = DEFAULT_FPS,
) -> list[ScheduledMessage]:
    """재생 타임라인을 만든다. `start` 는 자리표시자여도 된다 — `reproject` 가 다시 맞춘다."""
    step = 1.0 / fps
    count = int(duration_s / step)
    return [
        ScheduledMessage(
            at_s=round(index * step, 6),
            message=_frame(cam_id, start + timedelta(seconds=index * step)),
        )
        for index in range(count + 1)
    ]


def reproject(timeline: list[ScheduledMessage]) -> list[ScheduledMessage]:
    """각 프레임의 좌표를 **그 프레임의 `ts`** 로 다시 계산한다.

    `retime` 이 `ts` 만 고쳐 놓기 때문에 필요하다. 좌표가 옛 `ts` 에서 나온 값이면
    영상과 위상이 어긋나고, 그러면 이 도구가 재려던 오차에 도구 자신의 오차가 섞인다.
    """
    return [
        ScheduledMessage(at_s=item.at_s, message=_frame(item.message.cam_id, item.message.ts))
        for item in timeline
    ]
