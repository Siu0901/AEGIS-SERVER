"""시계열·분포 집계 — 분석 화면(FN-UI-05)의 데이터원. FN-SYS-04

API명세서 §4.2 `GET /metrics/timeseries` · `/metrics/distribution`

★ **비율 규칙을 여기서 다시 적지 않는다.** 버킷마다 `metrics.summarize` 를 그대로
부른다 — §6.7 의 표(무엇이 분자이고 무엇이 분모인가)가 두 곳에 있으면, 나중에 한쪽만
고쳐졌을 때 요약과 추이가 서로 다른 시정률을 말하게 된다. 그때 어느 쪽이 맞는지
가릴 방법이 없다.

**모집단이 빈 버킷은 점을 만들지 않는다.** §4.2 의 `points[].value` 는 `float` 이고,
§6.7 은 분모가 0이면 비율이 존재하지 않는다고 말한다. `0.0` 을 채우면 이벤트가 없던
시간대가 「시정률 0%」로 보이므로, 그 버킷은 **빼고** 화면이 선을 잇지 않게 한다.
`n` 이 함께 실리므로 옆 점만 보고도 그 구간이 왜 비었는지 읽을 수 있다.

**`points[].n` 을 함께 낸다**(§4.2). 표본이 3건인 버킷의 100% 와 40건인 버킷의 87% 를
같은 굵기로 그리면 안 되기 때문이다.

**I/O 가 없다**(절대규칙 2).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aegis_contracts import DistributionBucket, TimeseriesPoint
from aegis_contracts.enums import DistributionBy, EventStatus, MetricBucket, MetricName
from server.domain.metrics import MetricsRow, summarize

__all__ = ["AggregateRow", "bucket_start", "distribution", "timeseries"]


@dataclass(frozen=True, slots=True)
class AggregateRow:
    """집계 한 건. `MetricsRow` 에 **어디서 언제** 났는지를 더한 것이다.

    요약(`GET /metrics/summary`)에는 필요 없던 축들이다 — 추이는 시각이, 분포는
    구역·카메라가 있어야 나뉜다.
    """

    row: MetricsRow
    detected_at: datetime
    cam_id: int
    zone_id: str | None


def bucket_start(at: datetime, bucket: MetricBucket) -> str:
    """그 시각이 속한 버킷의 시작. API명세서 §4.2 `points[].t`

    형식이 버킷마다 다르다 — `day`·`week` 는 `YYYY-MM-DD`(주는 **월요일**),
    `hour` 는 `YYYY-MM-DDTHH:00:00Z`. 명세서가 정한 그대로다.

    **UTC 로 자른다.** 서버 지역시간으로 자르면 배포 장소에 따라 같은 데이터가 다른
    버킷에 떨어지고, 그 차이는 화면에서 드러나지 않는다.
    """
    moment = at.astimezone(UTC)
    if bucket == "hour":
        return moment.strftime("%Y-%m-%dT%H:00:00Z")
    if bucket == "week":
        monday = moment.date() - timedelta(days=moment.weekday())
        return monday.isoformat()
    return moment.date().isoformat()


def timeseries(
    rows: Iterable[AggregateRow],
    *,
    metric: MetricName,
    bucket: MetricBucket,
    resolve_window_s: float,
) -> list[TimeseriesPoint]:
    """§4.2 — 버킷별 지표값과 모집단 크기.

    **버킷이 빈 구간은 만들지 않는다.** 없는 시간대를 0으로 채우면 "그때 위반이 0건"과
    "그때 아직 시스템이 없었다"가 같은 점으로 보인다. 화면이 축을 채운다.
    """
    grouped: dict[str, list[MetricsRow]] = {}
    for item in rows:
        grouped.setdefault(bucket_start(item.detected_at, bucket), []).append(item.row)

    points: list[TimeseriesPoint] = []
    for key in sorted(grouped):
        summary = summarize(grouped[key], period=key, resolve_window_s=resolve_window_s)
        denominator = summary.resolved + summary.resolved_late + summary.unresolved
        resolved_any = summary.resolved + summary.resolved_late

        if metric == "violations":
            # 건수 지표의 모집단은 자기 자신이다 — 비율이 아니므로 `n` 이 곧 값이다.
            value: float | None = summary.total_violations
            population = summary.total_violations
        elif metric == "correction_rate":
            value = summary.correction_rate
            population = denominator
        elif metric == "undetermined_rate":
            value = summary.undetermined_rate
            population = denominator + summary.undetermined
        else:
            # `avg_resolution_sec` — 해소된 건이 없으면 평균이 없다. 0초는
            # "즉시 시정했다"는 주장이라 사실과 다르다.
            value = summary.avg_resolution_sec if resolved_any else None
            population = resolved_any

        if value is None:
            # 모집단이 빈 버킷이다. 점을 만들지 않는다 — 0을 찍으면 「그 구간의
            # 시정률이 0%」라는 주장이 되고, 그것은 §6.7 이 금지한 바로 그 왜곡이다.
            continue
        points.append(TimeseriesPoint(t=key, value=value, n=population))
    return points


#: 분포 축의 라벨. 화면이 코드에 라벨을 적지 않게 서버가 함께 내려준다(§4.2 예시).
_TYPE_LABELS = {
    "no_helmet": "안전모 미착용",
    "zone_intrusion": "금지구역 침입",
    "proximity": "지게차 근접",
    "fall": "쓰러짐",
}


def distribution(
    rows: Sequence[AggregateRow],
    *,
    by: DistributionBy,
    zone_names: dict[str, str] | None = None,
    camera_names: dict[int, str] | None = None,
) -> list[DistributionBucket]:
    """§4.2 — 축별 건수와 비율.

    **모집단은 「집계에서 제외되지 않은 이벤트 전량」이다.** 시정률과 달리 분포는
    "무엇이 얼마나 났는가"를 보는 것이므로 미해소도 판정 불가도 함께 센다. 다만
    오탐(`is_false_positive`)과 확정 전 소멸(`dropped`)은 뺀다 — 위반이 아니었거나
    위반이었는지 알 수 없는 것들이다.

    `by=hour_of_day` 는 `"00"`~`"23"` 을 키로 쓴다. **0을 채워** 사전순 정렬이
    시각순과 일치하게 한다(§4.2) — 그러지 않으면 히트맵에서 10시가 2시 앞에 온다.
    """
    kept = [
        item
        for item in rows
        if not item.row.is_false_positive and item.row.status is not EventStatus.DROPPED
    ]
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for item in kept:
        if by == "violation_type":
            key = item.row.violation_type.value
            labels[key] = _TYPE_LABELS.get(key, key)
        elif by == "zone":
            # 구역 밖에서 난 위반도 사라지면 안 된다. 합이 전체와 맞아야 비율이 성립한다.
            key = item.zone_id or "-"
            labels[key] = (zone_names or {}).get(key, "구역 밖" if key == "-" else key)
        elif by == "camera":
            key = str(item.cam_id)
            labels[key] = (camera_names or {}).get(item.cam_id, f"카메라 {item.cam_id}")
        else:
            key = f"{item.detected_at.astimezone(UTC).hour:02d}"
            labels[key] = f"{key}시"
        counts[key] = counts.get(key, 0) + 1

    total = sum(counts.values())
    ordered = sorted(counts) if by == "hour_of_day" else sorted(counts, key=lambda k: -counts[k])
    return [
        DistributionBucket(
            key=key,
            label=labels[key],
            count=counts[key],
            # 전체가 0이면 버킷도 없으므로 여기서 0으로 나눌 일은 없다.
            ratio=round(counts[key] / total, 4),
        )
        for key in ordered
    ]
