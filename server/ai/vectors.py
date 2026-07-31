"""벡터 계산 — 순수 함수만. FN-AI-02 · FN-AI-04 · FN-AI-07

pgvector 가 SQL 쪽 거리를 맡고, 여기 있는 것은 **파이썬 안에서 비교해야 하는 것들**이다
(사례 매칭 · 이상 점수의 k-NN 평균). 둘 다 대상이 수십 건 수준이라 전수 비교로 충분하고,
근사 인덱스를 쓰면 그 오차가 곧 "왜 이 사례가 붙었나"를 설명할 수 없게 만든다.

I/O 도 시계도 없다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = ["anomaly_score", "cosine_distance", "cosine_similarity"]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """코사인 유사도 −1~1. 길이가 다르면 오류다 — 조용히 자르지 않는다."""
    if len(a) != len(b):
        msg = f"차원이 다르다: {len(a)} 대 {len(b)}"
        raise ValueError(msg)
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        # 영벡터는 방향이 없다. 0을 돌려주면 "직교한다"는 주장이 되지만, 실제로는
        # 비교할 수 없는 입력이다 — 임베딩이 영벡터로 오는 것 자체가 결함이다.
        msg = "영벡터는 유사도를 잴 수 없다"
        raise ValueError(msg)
    return dot / (norm_a * norm_b)


def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """코사인 거리 0~2. `1 − 유사도`."""
    return 1.0 - cosine_similarity(a, b)


def anomaly_score(
    sample: Sequence[float],
    pool: Sequence[Sequence[float]],
    *,
    k: int = 5,
) -> float | None:
    """API명세서 §6.8 — 정상 풀과의 **k-최근접 평균 코사인 거리**를 0~1로 정규화.

    풀이 비어 있으면 `None` 이다. **0.0 을 돌려주지 않는다** — 그것은 "완전히 정상"이라는
    주장인데 실제로는 "비교할 것이 없다"이고, 축적 초기의 모든 프레임이 정상으로 보이면
    이상 탐지가 켜져 있는지조차 알 수 없다(§6.7 의 분모 0 규약과 같은 이유다).

    코사인 거리는 0~2 이지만 임베딩 사이의 거리가 1을 넘는 일은 사실상 없다. 그래도
    범위를 벗어난 값이 화면에 그대로 나가지 않도록 0~1 로 자른다.
    """
    if not pool:
        return None
    distances = sorted(cosine_distance(sample, vector) for vector in pool)
    nearest = distances[: max(1, k)]
    mean = sum(nearest) / len(nearest)
    return round(min(1.0, max(0.0, mean)), 4)
