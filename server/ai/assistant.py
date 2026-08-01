"""챗봇 라우팅 · 브리핑 · 보고서. FN-AI-08 · 09 · 10 · API명세서 §4.4

기능명세서 §4.5 라우팅 표 그대로다.

| 질의 유형 | 처리 경로 | 예시 |
|---|---|---|
| 통계·집계 | SQL 조회 | "이번 주 위반 몇 건" |
| 장면 검색 | 임베딩 유사도 | "사다리 근처 작업 장면" |
| 현재 상황 | 현재 프레임 → 멀티모달 LLM | "지금 2번 카메라 상황은?" |

★ **라우팅을 LLM 에게 맡기지 않는다.** 경로 판단이 비결정적이면 같은 질문이 어떤 날은
SQL 로, 어떤 날은 벡터로 가고 그 차이를 설명할 수 없다. 무엇보다 `vision` 경로는 실제
프레임을 캡처하므로, 통계 질문이 그쪽으로 새면 답이 틀리는 동시에 비용이 든다.

★ **통계 답변의 숫자는 SQL 이 만든다.** LLM 은 그 숫자를 문장으로 옮길 뿐이고,
표(`attachments[].kind == "table"`)에 원본이 함께 실린다 — 사람이 문장과 표를 대조할 수
있어야 한다. 클라우드가 없으면 **문장을 서버가 직접 조립한다**(FN-SYS-03) — 통계 질의는
인터넷 없이도 답이 나와야 하는 기능이다(§7 가용성 「인터넷 단절 시 … SQL 통계 정상 동작」).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aegis_contracts.enums import ChatRoute

__all__ = ["ROUTE_WORDS", "route_of"]

#: 경로를 가르는 말들. 위에서부터 먼저 걸리는 것이 이긴다.
#:
#: `vision` 이 맨 위인 이유: 「지금 2번 카메라」에는 카메라 번호가 들어 있어 장면 검색과
#: 겹친다. 「지금」이 있으면 그것은 과거 장면을 찾는 질의가 아니라 현재 상황 질의다.
ROUTE_WORDS: tuple[tuple[ChatRoute, tuple[str, ...]], ...] = (
    ("vision", ("지금", "현재", "실시간", "브리핑", "상황은", "어때")),
    (
        "sql",
        (
            "몇 건", "몇건", "건수", "통계", "비율", "시정률", "평균", "추이",
            "얼마나", "총", "집계", "순위", "가장 많",
            # 「각각 무슨 위반이야?」 — 유형별 내역도 집계다. 이 말들이 없으면
            # 그 질문이 장면 검색으로 새고, 사람은 통계를 물었는데 클립을 받는다.
            "무슨 위반", "어떤 위반", "위반 종류", "유형", "내역", "각각", "종류",
        ),
    ),
    ("vector", ("장면", "찾아", "검색", "비슷", "영상", "클립", "보여")),
)  # fmt: skip

_CAM_RE = re.compile(r"(\d+)\s*번?\s*(?:카메라|캠|cam)", re.IGNORECASE)

#: 이보다 짧으면서 아무 신호도 없는 질의는 **앞 질문에 이어지는 말**로 본다.
#: 「각각은?」 · 「더 자세히」 · 「그럼 어제는」 같은 것들이다.
_FOLLOW_UP_MAX_LEN = 20


@dataclass(frozen=True, slots=True)
class Routing:
    """라우팅 결과 하나."""

    route: ChatRoute
    cam_id: int | None
    """`vision` 경로에서 어느 카메라를 볼지. 없으면 전체를 훑는다."""


def route_of(message: str, previous: ChatRoute | None = None) -> Routing:
    """질의 하나를 세 경로 중 하나로 보낸다. API명세서 §4.4 `route`

    ★ **앞 대화를 본다.** 신호가 없는 짧은 후속 질의(「각각은?」 · 「그럼 어제는」)는
    앞 질문과 같은 경로로 보낸다. 그러지 않으면 「이번 주 위반 몇 건」 다음의
    「각각 무슨 위반이야?」가 기본값인 장면 검색으로 새고, 사람은 통계를 이어 묻다가
    갑자기 클립을 받는다 — 실제로 그랬다.

    **기본은 `vector` 다.** 무엇을 묻는지 모르겠고 이어지는 말도 아니면 장면을 찾아
    보여주는 쪽이 통계를 지어내는 것보다 낫다 — 틀린 그림은 사람이 바로 알아보지만
    틀린 숫자는 그대로 보고서에 들어간다.
    """
    cam = _CAM_RE.search(message)
    cam_id = int(cam.group(1)) if cam else None
    for route, words in ROUTE_WORDS:
        if any(word in message for word in words):
            return Routing(route=route, cam_id=cam_id)
    if previous is not None and len(message.strip()) <= _FOLLOW_UP_MAX_LEN:
        return Routing(route=previous, cam_id=cam_id)
    return Routing(route="vector", cam_id=cam_id)
