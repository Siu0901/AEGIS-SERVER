"""지표 — 「방송 후 시정률」과 그 주변. API명세서 §4.2 · §6.7

| 경로 | 쓰는 곳 |
|---|---|
| `GET /metrics/summary` | 개요(FN-UI-01) · 챗봇 통계 경로(FN-AI-08) |
| `GET /metrics/timeseries` | 분석 화면의 시정률 추이(FN-UI-05) |
| `GET /metrics/distribution` | 유형 분포 · 시간대 히트맵(FN-UI-05) |
| `GET /metrics/repeat` | 반복 위반 순위(FN-UI-05 · FN-EVT-06) |
| `GET /anomalies` | 이상 탐지 플래그 목록(FN-AI-04) — **경고가 아니라 '주의'다** |

**두 숫자는 항상 함께 나간다.** 시정률만 떼어 보여주면 추적이 끊긴 이벤트가 몇 건인지
알 수 없어 그 숫자를 검증할 수 없다 — `방송 후 시정률 87% (판정 불가 5%)` 형태가
표기 규칙이다(FN-SYS-04/05).

★ **집계 규칙은 여기 없다.** 무엇이 분자이고 무엇이 분모인가는 `server/domain/metrics.py`
와 `aggregates.py` 에만 있고, 이 파일은 저장소에서 행을 받아 그 함수에 넘길 뿐이다.
규칙이 라우터로 새면 요약과 추이가 서로 다른 시정률을 말하게 된다.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime

from aegis_contracts import (
    AnomalyItem,
    AnomalyListResponse,
    DistributionBucket,
    ErrorBody,
    ErrorResponse,
    MetricsDistributionResponse,
    MetricsRepeatResponse,
    MetricsSummary,
    MetricsTimeseriesResponse,
    RepeatItem,
    Zone,
)
from aegis_contracts.enums import DistributionBy, MetricBucket, MetricName, ViolationType
from aegis_vision.clock import Clock
from server.app.event_service import EventService
from server.domain.aggregates import AggregateRow, distribution, timeseries

__all__ = ["router"]

log = logging.getLogger("server.routes.metrics")

router = APIRouter(tags=["metrics"])

#: 반복 순위의 기본·최대 기간과 개수. §4.2 예시가 `days=7&limit=10` 이다.
MAX_REPEAT_DAYS = 90
MAX_REPEAT_LIMIT = 50

#: 이상 목록의 최대 개수. 화면은 최근 것만 보여주면 되고, 전량이 필요하면 DB 를 본다.
MAX_ANOMALY_LIMIT = 200


class AggregateStore(Protocol):
    """`DbEventRepository` 중 이 라우터가 쓰는 부분."""

    async def aggregate_rows(self, from_: Any, to: Any) -> list[AggregateRow]: ...

    async def repeat_ranking(self, since: Any, limit: int) -> list[Any]: ...


class AnomalyStore(Protocol):
    """`DbAiRepository` 중 이 라우터가 쓰는 부분. FN-AI-04"""

    async def list_anomalies(self, from_: Any, limit: int) -> list[Any]: ...


@router.get(
    "/metrics/summary",
    response_model=MetricsSummary,
    responses={503: {"model": ErrorResponse}},
)
async def metrics_summary(
    request: Request,
    from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to: AwareDatetime | None = None,
) -> MetricsSummary:
    """구간을 주지 않으면 **오늘**(UTC 자정 기준)이다.

    §4.2 는 `period` 를 응답 필드로만 정의하고 쿼리 파라미터를 적지 않았다. 다른 지표
    엔드포인트와 같은 `from` · `to` 를 받고, 주지 않으면 `period = "today"` 로 답한다.
    """
    service: EventService | None = getattr(request.app.state, "event_service", None)
    if service is None:
        raise _error(503, "이벤트 저장소가 연결되지 않았습니다")
    try:
        return await service.summary(from_=from_, to=to)
    except (OSError, RuntimeError) as exc:
        log.warning("지표를 계산하지 못했다: %s", exc)
        raise _error(503, "지표를 계산하지 못했습니다", str(exc)) from exc


@router.get(
    "/metrics/timeseries",
    response_model=MetricsTimeseriesResponse,
    responses={503: {"model": ErrorResponse}},
)
async def metrics_timeseries(
    request: Request,
    metric: MetricName,
    bucket: MetricBucket,
    from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to: AwareDatetime | None = None,
) -> MetricsTimeseriesResponse:
    """§4.2 — 버킷별 지표 추이. FN-UI-05

    **모집단이 빈 버킷은 점이 없다**(§6.7). 0을 찍으면 이벤트가 없던 구간이
    「시정률 0%」로 보이므로, 그 버킷을 빼고 화면이 선을 잇지 않게 한다. 각 점에
    `n`(모집단)이 함께 실려 표본이 작은 구간을 구분할 수 있다.
    """
    rows = await _rows(request, from_, to)
    service = _service(request)
    return MetricsTimeseriesResponse(
        metric=metric,
        bucket=bucket,
        points=timeseries(
            rows,
            metric=metric,
            bucket=bucket,
            resolve_window_s=service.machine.policies.resolve_window_s,
        ),
    )


@router.get(
    "/metrics/distribution",
    response_model=MetricsDistributionResponse,
    responses={503: {"model": ErrorResponse}},
)
async def metrics_distribution(
    request: Request,
    by: DistributionBy,
    from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to: AwareDatetime | None = None,
) -> MetricsDistributionResponse:
    """§4.2 — 축별 건수와 비율. `by=hour_of_day` 가 시간대 히트맵의 데이터원이다."""
    rows = await _rows(request, from_, to)
    buckets: list[DistributionBucket] = distribution(
        rows,
        by=by,
        zone_names=await _zone_names(request),
        camera_names=await _camera_names(request),
    )
    return MetricsDistributionResponse(by=by, buckets=buckets)


@router.get(
    "/metrics/repeat",
    response_model=MetricsRepeatResponse,
    responses={503: {"model": ErrorResponse}},
)
async def metrics_repeat(
    request: Request,
    days: int = 7,
    limit: int = 10,
) -> MetricsRepeatResponse:
    """§4.2 — 반복 위반 순위. FN-EVT-06 · FN-UI-05

    ★ **작업자 개인 단위 누적은 하지 않는다.** `track` 축은 세션 내 추적 번호일 뿐
    신원이 아니므로 라벨도 그렇게 적는다 — 「작업자 #3」이 아니라 「추적 #3」이다.
    """
    store = _store(request)
    clock: Clock = request.app.state.clock
    window = max(1, min(days, MAX_REPEAT_DAYS))
    since = clock.now() - timedelta(days=window)
    try:
        ranked = await store.repeat_ranking(since, max(1, min(limit, MAX_REPEAT_LIMIT)))
    except (OSError, RuntimeError) as exc:
        log.warning("반복 위반을 세지 못했다: %s", exc)
        raise _error(503, "반복 위반을 집계하지 못했습니다", str(exc)) from exc

    zones = await _zone_names(request)
    cameras = await _camera_names(request)
    items = [
        RepeatItem(
            subject=subject,
            key=key,
            label=_repeat_label(subject, key, zones, cameras),
            violation_type=ViolationType(violation_type),
            count=count,
            last_at=last_at,
        )
        for subject, key, violation_type, count, last_at in ranked
    ]
    return MetricsRepeatResponse(days=window, items=items)


@router.get(
    "/anomalies",
    response_model=AnomalyListResponse,
    responses={503: {"model": ErrorResponse}},
)
async def list_anomalies(
    request: Request,
    days: int = 7,
    limit: int = 50,
) -> AnomalyListResponse:
    """FN-AI-04 — 이상 탐지 플래그 목록.

    ★ **경고 방송을 발동하지 않는 종류의 알림이다.** 조명·날씨로도 점수가 오르므로
    위반과 같은 표시로 그리지 않는다 — 대시보드 '주의'다(기능명세서 §4.5).

    §5.3 은 `anomaly` **발행**만 정의한다. 발행만으로는 새로고침한 화면과 서버가 죽어
    있던 동안의 이상을 볼 수 없어 — 화면이 메시지를 놓친 것과 이상이 없었던 것이 같아
    보인다 — §4 가 이 조회 경로를 함께 정의했다.
    """
    store: AnomalyStore | None = getattr(request.app.state, "ai_store", None)
    if store is None:
        raise _error(503, "이상 탐지 저장소가 연결되지 않았습니다")
    clock: Clock = request.app.state.clock
    since = clock.now() - timedelta(days=max(1, min(days, MAX_REPEAT_DAYS)))
    try:
        rows = await store.list_anomalies(since, max(1, min(limit, MAX_ANOMALY_LIMIT)))
    except (OSError, RuntimeError) as exc:
        log.warning("이상 목록을 읽지 못했다: %s", exc)
        raise _error(503, "이상 탐지 목록을 읽지 못했습니다", str(exc)) from exc
    return AnomalyListResponse(
        items=[
            AnomalyItem(
                anomaly_id=anomaly_id,
                cam_id=cam_id,
                score=score,
                detected_at=detected_at,
                note=note,
                # `media/anomalies/{id}.jpg`(§4 `GET /anomalies`). 저장에 실패했으면
                # 경로가 비어 있고, 그때는 없는 URL 을 문자열로 내보내지 않는다(§5.2).
                keyframe_url=_anomaly_url(path),
            )
            for anomaly_id, cam_id, score, detected_at, path, note in rows
        ]
    )


def _anomaly_url(path: str | None) -> str | None:
    """저장 경로 → `/media/anomalies/...` URL. 비어 있으면 `null` 이다(§5.2)."""
    if not path:
        return None
    return f"/media/anomalies/{Path(path).name}"


def _repeat_label(
    subject: str,
    key: str,
    zones: dict[str, str],
    cameras: dict[int, str],
) -> str:
    if subject == "zone":
        return zones.get(key, key)
    if subject == "camera":
        return cameras.get(int(key), f"카메라 {key}")
    # ★ 「작업자」라고 쓰지 않는다(§4.2). 추적 번호는 신원이 아니고 카메라를 벗어나면
    #   유효하지 않다. 라벨이 사람을 가리키면 그 숫자가 개인 평가로 읽힌다.
    return f"추적 #{key}"


async def _rows(request: Request, from_: Any, to: Any) -> list[AggregateRow]:
    store = _store(request)
    try:
        return await store.aggregate_rows(from_, to)
    except (OSError, RuntimeError) as exc:
        log.warning("집계 행을 읽지 못했다: %s", exc)
        raise _error(503, "지표를 계산하지 못했습니다", str(exc)) from exc


async def _zone_names(request: Request) -> dict[str, str]:
    """구역 라벨. 화면이 코드에 이름을 적지 않게 서버가 함께 내려준다."""
    zones = getattr(request.app.state, "zones", None)
    if zones is None:
        return {}
    try:
        items: list[Zone] = await zones.list_zones()
    except Exception:
        log.warning("구역 이름을 읽지 못했다 — 분포 라벨에 ID 가 그대로 나간다")
        return {}
    return {zone.zone_id: zone.name for zone in items}


async def _camera_names(request: Request) -> dict[int, str]:
    """카메라 라벨. **DB `cameras.name` 이 원천이다**(§6) — 설치 위치명은 설정에 있다."""
    cameras = getattr(request.app.state, "cameras", None)
    if cameras is None:
        return {}
    try:
        rows = await cameras.list_cameras()
    except Exception:
        log.warning("카메라 이름을 읽지 못했다 — 분포 라벨에 번호가 그대로 나간다")
        return {}
    return {int(row["cam_id"]): str(row["name"]) for row in rows}


def _service(request: Request) -> EventService:
    service: EventService | None = getattr(request.app.state, "event_service", None)
    if service is None:
        raise _error(503, "이벤트 저장소가 연결되지 않았습니다")
    return service


def _store(request: Request) -> AggregateStore:
    store: AggregateStore | None = getattr(request.app.state, "events", None)
    if store is None:
        raise _error(503, "이벤트 저장소가 연결되지 않았습니다")
    return store


def _error(http_status: int, message: str, reason: str | None = None) -> HTTPException:
    """§1.4 오류 봉투. FastAPI 기본 `{"detail": ...}` 형태를 쓰지 않는다."""
    body = ErrorResponse(
        error=ErrorBody.model_validate(
            {
                "code": "NOT_FOUND",
                "message": message,
                "detail": {"reason": reason} if reason else None,
            }
        )
    )
    return HTTPException(status_code=http_status, detail=body.model_dump(mode="json"))
