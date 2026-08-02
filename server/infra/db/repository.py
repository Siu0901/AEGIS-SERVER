"""저장소 구현 — `server/domain/repository.py` 프로토콜의 DB 쪽 짝. FN-REC-04

도메인은 저장 방법을 모른다(CLAUDE.md 절대규칙 2). SQL·세션·트랜잭션은 전부 여기 있고,
바깥으로 나가는 것은 계약 모델(`aegis_contracts`)뿐이다.

**동기 엔진을 스레드로 감싼다.** 서버 런타임은 전부 비동기인데 SQLModel 세션은
동기다. `asyncio.to_thread` 로 감싸면 이벤트 루프가 DB I/O 에 막히지 않는다 —
`/ws/edge` 가 초당 수십 개의 프레임을 처리하는 동안 후보 저장 한 건이 루프를 세우면
오버레이 전체가 끊긴다. 비동기 드라이버로 바꾸는 것은 이 경계 안쪽의 일이다.

M2 에서 실제로 쓰이는 것은 셋이다 — 이벤트 생성·조회(FN-EVT-01 · FN-REC-04),
구역 조회(`GET /zones`), 정책 조회(`GET /policies`). 재결합·클립 예약 질의는
해당 마일스톤에서 채운다.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, cast

from sqlalchemy import Engine, delete
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, func, select

from aegis_contracts import (
    AlertSound,
    EventDetail,
    EventListQuery,
    EventStatus,
    EventSummary,
    Policies,
    TimelineEntry,
    VehicleClass,
    ViolationType,
    Zone,
)
from aegis_contracts.enums import AlertLevel
from server.domain.aggregates import AggregateRow
from server.domain.alerts import MINIMUM_LEVEL, LevelFloorError, SoundEntry, check_level
from server.domain.event_machine import format_event_id
from server.domain.metrics import MetricsRow
from server.infra.db.models import AlertSound as SoundRow
from server.infra.db.models import Anomaly as AnomalyRow
from server.infra.db.models import Camera as CameraRow
from server.infra.db.models import Event as EventRow
from server.infra.db.models import NormalPoolSample as NormalPoolRow
from server.infra.db.models import Policy as PolicyRow
from server.infra.db.models import VehicleClassRow
from server.infra.db.models import Zone as ZoneRow

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "OPEN_STATUSES",
    "DbAiRepository",
    "DbCameraRepository",
    "DbEventRepository",
    "DbPolicyRepository",
    "DbSoundRepository",
    "DbVehicleClassRepository",
    "DbZoneRepository",
]

log = logging.getLogger("server.infra.db")

#: `GET /events` 의 기본·최대 페이지 크기. 명세서에 값이 없어 서버가 정한다.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

#: 종결되지 않은 상태. FN-EVT-01 이 "진행 중"이라고 부르는 집합이다(기능명세서 §4.2).
OPEN_STATUSES: tuple[EventStatus, ...] = (
    EventStatus.CANDIDATE,
    EventStatus.ACTIVE,
    EventStatus.ALERTED,
    EventStatus.RE_ALERTED,
    EventStatus.LOST,
)

#: 반복 위반 집계 창. 기능명세서 §4.2 FN-EVT-06.
REPEAT_WINDOW = timedelta(days=7)

#: 클라이언트로 나가는 파일 참조의 접두사. §5 「경로 규약」 — 파일시스템 경로를
#: 그대로 실어보내지 않는다.
MEDIA_URL_PREFIX = "/media"

#: 상태별로 함께 찍히는 시각 컬럼. 기능명세서 §6 · §5.2 전이별 동반 필드.
#:
#: **`re_alerted` 는 `alerted_at` 을 건드리지 않는다**(§5.2). 최초 경고 시각을 덮으면
#: `resolution_sec` 이 마지막 방송 기준으로 줄어 시정률이 부풀려진다.
_STATUS_STAMP: dict[EventStatus, Callable[[datetime], dict[str, Any]]] = {
    EventStatus.ACTIVE: lambda at: {"confirmed_at": at},
    EventStatus.ALERTED: lambda at: {"alerted_at": at, "last_alerted_at": at},
    EventStatus.RE_ALERTED: lambda at: {"last_alerted_at": at},
    EventStatus.LOST: lambda at: {"lost_at": at},
    EventStatus.RESOLVED: lambda at: {"resolved_at": at},
    EventStatus.EXPIRED: lambda at: {"expired_at": at},
    EventStatus.DROPPED: lambda at: {"dropped_at": at},
}


class DbEventRepository:
    """`server.domain.repository.EventRepository` 구현."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- 조회 -----------------------------------------------------------

    async def get(self, event_id: str) -> EventDetail | None:
        return await asyncio.to_thread(self._get, event_id)

    def _get(self, event_id: str) -> EventDetail | None:
        with Session(self._engine) as session:
            row = session.get(EventRow, event_id)
            if row is None:
                return None
            return _detail(row, self._repeat_count(session, row))

    async def list_events(self, query: EventListQuery) -> tuple[list[EventSummary], str | None]:
        return await asyncio.to_thread(self._list_events, query)

    def _list_events(self, query: EventListQuery) -> tuple[list[EventSummary], str | None]:
        limit = min(query.limit or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
        statement = select(EventRow)
        if query.from_ is not None:
            statement = statement.where(col(EventRow.detected_at) >= query.from_)
        if query.to is not None:
            statement = statement.where(col(EventRow.detected_at) <= query.to)
        if query.cam_id is not None:
            statement = statement.where(col(EventRow.cam_id) == query.cam_id)
        if query.type is not None:
            statement = statement.where(col(EventRow.violation_type) == query.type.value)
        if query.status is not None:
            statement = statement.where(col(EventRow.status) == query.status.value)
        if query.zone_id is not None:
            statement = statement.where(col(EventRow.zone_id) == query.zone_id)

        cursor = _decode_cursor(query.cursor)
        if cursor is not None:
            at, last_id = cursor
            # 최신순 정렬이므로 "그 시각보다 이전, 같은 시각이면 ID 가 작은 것"이 다음 장이다.
            statement = statement.where(
                (col(EventRow.detected_at) < at)
                | ((col(EventRow.detected_at) == at) & (col(EventRow.event_id) < last_id))
            )

        statement = statement.order_by(
            col(EventRow.detected_at).desc(), col(EventRow.event_id).desc()
        ).limit(limit + 1)

        with Session(self._engine) as session:
            rows = list(session.exec(statement))
            has_more = len(rows) > limit
            rows = rows[:limit]
            items = [_summary(row, self._repeat_count(session, row)) for row in rows]

        next_cursor = _encode_cursor(rows[-1]) if has_more and rows else None
        return items, next_cursor

    async def find_open_by_track(
        self,
        cam_id: int,
        track_id: int,
        violation_type: ViolationType,
    ) -> EventSummary | None:
        """진행 중 이벤트를 찾는다. 중복 병합(FN-EVT-01)의 1차 조회."""
        return (await self.find_open_events(cam_id, track_id)).get(violation_type)

    async def find_open_events(
        self, cam_id: int, track_id: int
    ) -> dict[ViolationType, EventSummary]:
        """이 트랙에 붙어 있는 **진행 중 이벤트 전량**을 위반 유형별로.

        후보 하나가 위반 여러 개를 실어 오므로(§2.2) 유형마다 따로 묻는 대신 한 번에
        가져온다. 유형별 조회를 반복하면 후보 한 건에 DB 왕복이 유형 수만큼 붙는다.
        """
        return await asyncio.to_thread(self._find_open_events, cam_id, track_id)

    def _find_open_events(self, cam_id: int, track_id: int) -> dict[ViolationType, EventSummary]:
        statement = (
            select(EventRow)
            .where(col(EventRow.cam_id) == cam_id)
            .where(col(EventRow.track_id) == track_id)
            .where(col(EventRow.status).in_([status.value for status in OPEN_STATUSES]))
            .order_by(col(EventRow.detected_at).desc())
        )
        with Session(self._engine) as session:
            rows = list(session.exec(statement))
        found: dict[ViolationType, EventSummary] = {}
        for row in rows:
            violation = ViolationType(row.violation_type)
            if violation in found:
                # 원래 생기면 안 되는 상태다(FN-EVT-01 이 막는다). 조용히 넘기지 않는다.
                log.warning(
                    "진행 중 이벤트가 중복이다 — cam=%s track=%s type=%s (%s 를 무시)",
                    cam_id,
                    track_id,
                    violation.value,
                    row.event_id,
                )
                continue
            found[violation] = _summary(row, 0)
        return found

    async def find_lost_by_camera(self, cam_id: int) -> list[EventSummary]:
        """재결합 후보가 되는 `lost` 이벤트들. FN-EVT-07 ②

        런타임 재결합은 상태머신이 메모리에서 하므로 이 질의는 진단·복구용이다.
        """
        return await asyncio.to_thread(self._find_lost_by_camera, cam_id)

    def _find_lost_by_camera(self, cam_id: int) -> list[EventSummary]:
        statement = (
            select(EventRow)
            .where(col(EventRow.cam_id) == cam_id)
            .where(col(EventRow.status) == EventStatus.LOST.value)
            .order_by(col(EventRow.lost_at).desc())
        )
        with Session(self._engine) as session:
            return [_summary(row, 0) for row in session.exec(statement)]

    async def find_open_all(self) -> list[EventSummary]:
        """종결되지 않은 이벤트 전량. 서버 재시작 시 상태머신을 되살리는 데 쓴다.

        복구하지 않으면 그 이벤트들은 어떤 전이도 받지 못한 채 `alerted` 로 남아
        시정률 분모에 영원히 미해소로 계상된다 — 재시작 한 번이 지표를 왜곡한다.
        """
        return await asyncio.to_thread(self._find_open_all)

    def _find_open_all(self) -> list[EventSummary]:
        statement = (
            select(EventRow)
            .where(col(EventRow.status).in_([status.value for status in OPEN_STATUSES]))
            .where(col(EventRow.is_false_positive).is_(False))
            .order_by(col(EventRow.detected_at))
        )
        with Session(self._engine) as session:
            return [_summary(row, 0) for row in session.exec(statement)]

    async def metrics_rows(self, from_: datetime | None, to: datetime | None) -> list[MetricsRow]:
        """FN-SYS-04 · FN-SYS-05 — 지표 집계에 필요한 네 칸만 긁어온다.

        판정(무엇이 분자이고 무엇이 분모인가)은 SQL 이 아니라
        `server/domain/metrics.py` 가 한다. 집계 규칙이 §6.7 표 하나에만 있어야
        나중에 값이 이상할 때 어디를 봐야 하는지가 분명해진다.
        """
        return await asyncio.to_thread(self._metrics_rows, from_, to)

    def _metrics_rows(self, from_: datetime | None, to: datetime | None) -> list[MetricsRow]:
        # **다섯 칸만 읽는다.** 이벤트 행에는 `embedding`(halfvec 3072)과 jsonb 가 여럿
        # 붙어 있어 전량을 읽으면 지표 한 번에 그것들이 통째로 넘어온다.
        #
        # `sqlmodel.select` 가 아니라 `sqlalchemy.select` 를 쓰는 이유: 앞쪽 타입 스텁의
        # 컬럼 오버로드가 **네 칸까지만** 있어 다섯째부터 반환 타입이 무너진다.
        statement = sa_select(
            col(EventRow.violation_type),
            col(EventRow.status),
            col(EventRow.resolution_sec),
            col(EventRow.is_false_positive),
            col(EventRow.alert_suppressed),
        )
        if from_ is not None:
            statement = statement.where(col(EventRow.detected_at) >= from_)
        if to is not None:
            statement = statement.where(col(EventRow.detected_at) <= to)
        with Session(self._engine) as session:
            rows = list(session.execute(statement).all())
        return [
            MetricsRow(
                violation_type=ViolationType(violation_type),
                status=EventStatus(status),
                resolution_sec=resolution_sec,
                is_false_positive=is_false_positive,
                alert_suppressed=alert_suppressed,
            )
            for (
                violation_type,
                status,
                resolution_sec,
                is_false_positive,
                alert_suppressed,
            ) in rows
        ]

    async def count_repeat_7d(
        self,
        cam_id: int,
        track_id: int,
        zone_id: str | None,
        at: datetime,
        violation_type: str | None = None,
    ) -> int:
        """동일 트랙·구역의 최근 7일 **유사** 이벤트 수. FN-EVT-06

        ★ **작업자 개인 단위 누적이 아니다**(API명세서 §4.2 「작업자 개인 단위 누적은
        하지 않는다」). `track_id` 는 세션 내 추적 번호일 뿐 신원이 아니므로, 이 숫자는
        「이 사람이 4번 어겼다」가 아니라 **「이 자리·이 추적에서 같은 위반이 4번
        관측됐다」**로 읽어야 한다. 화면 라벨도 그렇게 적는다(`EventsPage`).
        """
        return await asyncio.to_thread(
            self._count_repeat_7d, cam_id, track_id, zone_id, at, violation_type
        )

    def _count_repeat_7d(
        self,
        cam_id: int,
        track_id: int,
        zone_id: str | None,
        at: datetime,
        violation_type: str | None,
    ) -> int:
        with Session(self._engine) as session:
            return self._repeat_query(session, cam_id, track_id, zone_id, at, violation_type)

    def _repeat_count(self, session: Session, row: EventRow) -> int:
        """목록·상세에 실을 `repeat_count_7d`.

        기준 시각은 **그 이벤트의 관측 시각**이다. 지금 시각으로 세면 어제 본 목록과
        오늘 본 목록에서 같은 이벤트의 숫자가 달라진다.
        """
        if row.detected_at is None:
            return 0
        return self._repeat_query(
            session, row.cam_id, row.track_id, row.zone_id, row.detected_at, row.violation_type
        )

    def _repeat_query(
        self,
        session: Session,
        cam_id: int,
        track_id: int,
        zone_id: str | None,
        at: datetime,
        violation_type: str | None,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(EventRow)
            .where(col(EventRow.cam_id) == cam_id)
            .where(col(EventRow.detected_at) > at - REPEAT_WINDOW)
            .where(col(EventRow.detected_at) <= at)
            # 오탐으로 정정된 건은 반복 횟수에 넣지 않는다(FN-EVT-05).
            .where(col(EventRow.is_false_positive).is_(False))
        )
        if violation_type is not None:
            # §4.1 이 말하는 「**유사** 이벤트」다. 안전모 미착용과 지게차 근접을 한
            # 숫자로 합치면 "무엇이 반복되고 있는가"가 사라져 대응을 정할 수 없다.
            statement = statement.where(col(EventRow.violation_type) == violation_type)
        if zone_id is None:
            statement = statement.where(col(EventRow.track_id) == track_id)
        else:
            # 기능명세서 §4.2 — "동일 트랙 **또는** 동일 구역".
            statement = statement.where(
                (col(EventRow.track_id) == track_id) | (col(EventRow.zone_id) == zone_id)
            )
        return int(session.exec(statement).one())

    async def find_due_clip_jobs(self, now: datetime, delay_s: float) -> list[str]:
        """실행 시각이 지난 `clip_status = pending` 이벤트 ID들. FN-REC-03

        **이 질의가 곧 예약 큐다.** 메모리 큐를 두지 않으므로 서버가 죽어도 예약이
        남고, 재시작 뒤 첫 호출이 그대로 복구가 된다(기능명세서 §4.4).

        `delay_s` = `clip_post_roll_s + margin`. `confirmed_at + delay_s <= now` 인
        것만 고른다 — 더 일찍 부르면 사후 구간이 아직 디스크에 없어 앞부분만 담긴 클립이
        나오고, 그 실패는 `partial` 로 기록되어 되돌릴 수 없다.
        """
        return await asyncio.to_thread(self._find_due_clip_jobs, now, delay_s)

    def _find_due_clip_jobs(self, now: datetime, delay_s: float) -> list[str]:
        statement = (
            select(EventRow)
            .where(col(EventRow.clip_status) == "pending")
            .where(col(EventRow.confirmed_at).is_not(None))
            .where(col(EventRow.confirmed_at) <= now - timedelta(seconds=delay_s))
            .order_by(col(EventRow.confirmed_at))
        )
        with Session(self._engine) as session:
            return [row.event_id for row in session.exec(statement)]

    # -- 쓰기 -----------------------------------------------------------

    async def next_event_id(self, at: datetime) -> str:
        """`EV-YYYYMMDD-NNNN` 의 다음 번호. 기능명세서 §6

        같은 날짜 접두사 중 가장 큰 값에 1을 더한다. 이벤트를 만드는 것은
        `/ws/edge` 한 곳뿐이라 경합이 없다 — 쓰기 주체가 늘면 시퀀스로 바꾼다.
        """
        return await asyncio.to_thread(self._next_event_id, at)

    def _next_event_id(self, at: datetime) -> str:
        prefix = format_event_id(at, 0)[:-4]
        statement = (
            select(EventRow.event_id)
            .where(col(EventRow.event_id).startswith(prefix))
            .order_by(col(EventRow.event_id).desc())
            .limit(1)
        )
        with Session(self._engine) as session:
            latest = session.exec(statement).first()
        return format_event_id(at, int(latest[-4:]) + 1 if latest else 1)

    async def create(self, event: EventDetail) -> None:
        await asyncio.to_thread(self._create, event)

    def _create(self, event: EventDetail) -> None:
        with Session(self._engine) as session:
            session.add(_row(event))
            session.commit()

    async def update(self, event_id: str, changes: Mapping[str, Any]) -> None:
        await asyncio.to_thread(self._update, event_id, changes)

    def _update(self, event_id: str, changes: Mapping[str, Any]) -> None:
        with Session(self._engine) as session:
            row = session.get(EventRow, event_id)
            if row is None:
                # 있는 줄 알고 갱신했는데 없다. 삼키면 이벤트가 조용히 사라진 것처럼 보인다.
                log.warning("갱신할 이벤트가 없다: %s", event_id)
                return
            for key, value in changes.items():
                setattr(row, key, value)
            session.add(row)
            session.commit()

    async def set_status(self, event_id: str, status: EventStatus, at: datetime) -> None:
        """상태 전이 1건. 전이 판단 자체는 도메인 상태머신이 한다.

        평상시 경로는 이쪽이 아니다 — 상태머신은 상태와 시각을 함께 담은 `Effect`
        를 내므로 `update` 한 번으로 끝난다. 이 메서드는 상태만 알고 있는 호출자
        (운영 도구·복구 스크립트)를 위한 편의 경로다.
        """
        stamp = _STATUS_STAMP.get(status)
        await self.update(event_id, {"status": status.value, **(stamp(at) if stamp else {})})

    # -- 분석 화면 집계 (FN-UI-05 · FN-SYS-04) ---------------------------

    async def aggregate_rows(
        self,
        from_: datetime | None,
        to: datetime | None,
    ) -> list[AggregateRow]:
        """추이·분포가 보는 행들. `metrics_rows` 에 **시각·카메라·구역**을 더한 것이다.

        요약과 같은 판정 규칙을 쓰기 위해 `MetricsRow` 를 그대로 품는다 — §6.7 표가
        두 벌이 되면 요약과 추이가 서로 다른 시정률을 말하게 된다.
        """
        return await asyncio.to_thread(self._aggregate_rows, from_, to)

    def _aggregate_rows(
        self,
        from_: datetime | None,
        to: datetime | None,
    ) -> list[AggregateRow]:
        # 여덟 칸만 읽는다. `embedding`(halfvec 3072)과 jsonb 를 끌고 오면 한 달치
        # 추이 한 번에 수백 MB 가 넘어온다.
        statement = sa_select(
            col(EventRow.violation_type),
            col(EventRow.status),
            col(EventRow.resolution_sec),
            col(EventRow.is_false_positive),
            col(EventRow.alert_suppressed),
            col(EventRow.detected_at),
            col(EventRow.cam_id),
            col(EventRow.zone_id),
        ).where(col(EventRow.detected_at).is_not(None))
        if from_ is not None:
            statement = statement.where(col(EventRow.detected_at) >= from_)
        if to is not None:
            statement = statement.where(col(EventRow.detected_at) <= to)
        with Session(self._engine) as session:
            rows = list(session.execute(statement).all())
        return [
            AggregateRow(
                row=MetricsRow(
                    violation_type=ViolationType(violation_type),
                    status=EventStatus(status),
                    resolution_sec=resolution_sec,
                    is_false_positive=is_false_positive,
                    alert_suppressed=alert_suppressed,
                ),
                detected_at=detected_at,
                cam_id=cam_id,
                zone_id=zone_id,
            )
            for (
                violation_type,
                status,
                resolution_sec,
                is_false_positive,
                alert_suppressed,
                detected_at,
                cam_id,
                zone_id,
            ) in rows
        ]

    async def repeat_ranking(
        self, since: datetime, limit: int
    ) -> list[tuple[str, str, str, int, datetime]]:
        """§4.2 `GET /metrics/repeat` — (subject, key, violation_type, count, last_at).

        ★ **작업자 개인 단위 누적은 하지 않는다**(§4.2). `track` 축은 세션 내 추적
        번호일 뿐 신원이 아니므로, 같은 사람이 다른 날 잡혀도 다른 트랙이다. 이 숫자는
        「이 사람이 몇 번」이 아니라 「이 자리·이 추적에서 몇 번」으로 읽어야 한다.

        라벨 붙이기는 라우터가 한다 — 구역 이름은 `zones` 테이블에 있고 이 저장소는
        `events` 만 본다.
        """
        return await asyncio.to_thread(self._repeat_ranking, since, limit)

    def _repeat_ranking(
        self, since: datetime, limit: int
    ) -> list[tuple[str, str, str, int, datetime]]:
        found: list[tuple[str, str, str, int, datetime]] = []
        axes: tuple[tuple[str, Any], ...] = (
            ("zone", col(EventRow.zone_id)),
            ("camera", col(EventRow.cam_id)),
            ("track", col(EventRow.track_id)),
        )
        with Session(self._engine) as session:
            for subject, column in axes:
                statement = (
                    sa_select(
                        column,
                        col(EventRow.violation_type),
                        func.count(),
                        func.max(col(EventRow.detected_at)),
                    )
                    .where(col(EventRow.detected_at) >= since)
                    .where(col(EventRow.is_false_positive).is_(False))
                    # 확정된 적이 없는 후보는 「반복 위반」이 아니다(§4.2 · FN-EVT-06).
                    .where(col(EventRow.status) != EventStatus.DROPPED.value)
                    .where(column.is_not(None))
                    .group_by(column, col(EventRow.violation_type))
                    .order_by(func.count().desc())
                    .limit(limit)
                )
                for key, violation_type, count, last_at in session.execute(statement).all():
                    found.append((subject, str(key), str(violation_type), int(count), last_at))
        # 축이 섞인 목록을 다시 정렬한다 — 화면은 "무엇이 가장 자주 반복되는가"를
        # 한 표로 보여주고, 축은 그 안에서 라벨로 구분된다.
        found.sort(key=lambda item: (-item[3], item[0], item[1]))
        return found[:limit]

    # -- 임베딩 · 장면 검색 (FN-AI-01 · 02) -------------------------------

    async def save_embedding(self, event_id: str, vector: list[float]) -> None:
        """FN-AI-01 — 키프레임 임베딩을 그 이벤트 행에 붙인다.

        **벡터는 로컬에만 남는다**(기능명세서 §4.5 · §7 보안). 클라우드로 나간 것은
        키프레임이고 돌아온 숫자는 여기서 끝난다.
        """
        await self.update(event_id, {"embedding": vector})

    async def search_events(
        self,
        *,
        vector: list[float] | None,
        from_: datetime | None,
        to: datetime | None,
        cam_id: int | None,
        violation_type: str | None,
        limit: int,
    ) -> list[tuple[EventSummary, float | None, str | None]]:
        """FN-AI-02 — **하이브리드**. 구조화 조건은 SQL, 자유 문장만 벡터 랭킹.

        ★ 통계 질문에 벡터 검색을 쓰지 않는다(기능명세서 §4.5). 기간·카메라·유형은
        `WHERE` 로 먼저 좁히고, 남은 것만 코사인 거리로 정렬한다. 순서가 반대면
        「지난주 1번 카메라」 같은 조건이 유사도에 밀려 무시된다.

        `vector` 가 `None` 이면 순수 SQL 검색이며 유사도는 `None` 이다 — 재지 않은
        숫자를 지어내지 않는다.

        세 번째 칸은 **클립 URL** 이다. `EventSummary`(§4.1 목록)에는 그 칸이 없고
        경로 → URL 변환은 이 파일에만 있으므로(§5 경로 규약), 저장소가 함께 낸다 —
        호출자가 `event_id` 로 URL 을 조립하면 그 규칙이 두 곳이 된다.
        """
        return await asyncio.to_thread(
            self._search_events, vector, from_, to, cam_id, violation_type, limit
        )

    def _search_events(
        self,
        vector: list[float] | None,
        from_: datetime | None,
        to: datetime | None,
        cam_id: int | None,
        violation_type: str | None,
        limit: int,
    ) -> list[tuple[EventSummary, float | None, str | None]]:
        statement = select(EventRow)
        # ① 구조화 조건 — 벡터를 꺼내기 전에 좁힌다.
        if from_ is not None:
            statement = statement.where(col(EventRow.detected_at) >= from_)
        if to is not None:
            statement = statement.where(col(EventRow.detected_at) <= to)
        if cam_id is not None:
            statement = statement.where(col(EventRow.cam_id) == cam_id)
        if violation_type is not None:
            statement = statement.where(col(EventRow.violation_type) == violation_type)
        # 오탐으로 정정된 건은 검색 결과에도 넣지 않는다 — 위반이 아니었기 때문이다.
        statement = statement.where(col(EventRow.is_false_positive).is_(False))

        with Session(self._engine) as session:
            if vector is None:
                rows = list(
                    session.exec(
                        statement.order_by(col(EventRow.detected_at).desc()).limit(limit)
                    ).all()
                )
                return [(_summary(row, 0), None, _media_url(row.clip_path)) for row in rows]

            # ② 자유 문장 — 좁혀진 집합 안에서만 코사인 거리로 정렬한다.
            #    임베딩이 없는 이벤트는 비교 대상이 아니다(확정 전이거나 클라우드가
            #    꺼져 있던 구간). 조용히 0점으로 섞으면 순위가 오염된다.
            # `EventRow.embedding` 의 타입 스텁에는 pgvector 연산자가 없다. 테이블
            # 컬럼에서 직접 꺼내야 `cosine_distance` 를 쓸 수 있다.
            embedding_column = cast("Any", EventRow).__table__.c.embedding
            distance = embedding_column.cosine_distance(vector)
            ranked = (
                statement.where(col(EventRow.embedding).is_not(None))
                .order_by(distance)
                .limit(limit)
            )
            rows = list(session.exec(ranked).all())
            scores: dict[str, float] = {
                str(event_id): float(value)
                for event_id, value in session.execute(
                    sa_select(col(EventRow.event_id), distance).where(
                        col(EventRow.event_id).in_([row.event_id for row in rows])
                    )
                ).all()
            }
        return [
            # §4.3 `similarity` 는 **코사인 유사도**다. pgvector 가 주는 것은 거리이므로
            # 1에서 뺀다 — 그대로 실으면 "가장 닮은 것"이 가장 낮은 숫자가 된다.
            (
                _summary(row, 0),
                round(1.0 - float(scores.get(row.event_id, 1.0)), 4),
                _media_url(row.clip_path),
            )
            for row in rows
        ]


class DbAiRepository:
    """정상 풀과 이상 플래그. 기능명세서 §6 `normal_pool` · `anomalies` · FN-AI-04

    이벤트와 **다른 저장소로 나눈 이유**: 이상 탐지는 이벤트가 없어도 돌고(5분 주기
    샘플링), 안전 루프의 어떤 판정도 이 표를 읽지 않는다. 경계를 나눠 두면 그 사실이
    코드에서도 보인다.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def add_sample(
        self, cam_id: int, time_bucket: str, vector: list[float], at: datetime, model: str
    ) -> None:
        """정상 풀에 한 건 쌓는다. **시간대별로 분리 축적한다**(기능명세서 §4.5).

        `model` 은 이 벡터를 만든 임베딩 모델이다 — 없으면 모델 교체 후 옛 벡터와
        새 벡터가 한 풀에서 비교된다(§6 `normal_pool.embedding_model`).
        """
        await asyncio.to_thread(self._add_sample, cam_id, time_bucket, vector, at, model)

    def _add_sample(
        self, cam_id: int, time_bucket: str, vector: list[float], at: datetime, model: str
    ) -> None:
        with Session(self._engine) as session:
            session.add(
                NormalPoolRow(
                    cam_id=cam_id,
                    time_bucket=time_bucket,
                    embedding=vector,
                    embedding_model=model,
                    sampled_at=at,
                )
            )
            session.commit()

    async def pool(
        self, cam_id: int, time_bucket: str, limit: int, model: str
    ) -> list[list[float]]:
        """그 카메라·그 시간대·**그 모델**의 최근 정상 샘플들(§6.8).

        모델이 다른 행은 아예 읽지 않는다. 다른 공간의 벡터와 거리를 재면 그 값은
        「평소와 다르다」가 아니라 「비교할 수 없다」인데, 숫자는 그 둘을 구분하지 않는다.
        """
        return await asyncio.to_thread(self._pool, cam_id, time_bucket, limit, model)

    def _pool(self, cam_id: int, time_bucket: str, limit: int, model: str) -> list[list[float]]:
        statement = (
            select(NormalPoolRow)
            .where(col(NormalPoolRow.cam_id) == cam_id)
            .where(col(NormalPoolRow.time_bucket) == time_bucket)
            .where(col(NormalPoolRow.embedding_model) == model)
            .where(col(NormalPoolRow.embedding).is_not(None))
            .order_by(col(NormalPoolRow.sampled_at).desc())
            .limit(limit)
        )
        with Session(self._engine) as session:
            return [
                [float(value) for value in row.embedding]
                for row in session.exec(statement).all()
                if row.embedding is not None
            ]

    async def drop_other_models(self, model: str) -> int:
        """현재 모델이 아닌 정상 풀 행을 지운다. 지운 건수를 돌려준다.

        ★ **새 모델 풀이 충분히 찬 뒤에 부른다**(`anomaly_min_pool`). 먼저 지우면
        교체 직후 비교 대상이 0이 되어 그 구간이 통째로 판정 불가가 된다 — 옛 행은
        어차피 `pool()` 이 읽지 않으므로 남아 있어도 판정을 오염시키지 않는다.
        """
        return await asyncio.to_thread(self._drop_other_models, model)

    def _drop_other_models(self, model: str) -> int:
        statement = delete(NormalPoolRow).where(col(NormalPoolRow.embedding_model) != model)
        with Session(self._engine) as session:
            result = session.exec(statement)
            session.commit()
            return int(result.rowcount or 0)

    async def create_anomaly(
        self,
        cam_id: int,
        score: float,
        at: datetime,
        *,
        keyframe_path: str | None = None,
        llm_note: str | None = None,
    ) -> int:
        """이상 플래그 한 건. **경고 방송을 발동하지 않는다**(FN-AI-04)."""
        return await asyncio.to_thread(
            self._create_anomaly, cam_id, score, at, keyframe_path, llm_note
        )

    def _create_anomaly(
        self,
        cam_id: int,
        score: float,
        at: datetime,
        keyframe_path: str | None,
        llm_note: str | None,
    ) -> int:
        with Session(self._engine) as session:
            row = AnomalyRow(
                cam_id=cam_id,
                score=score,
                detected_at=at,
                keyframe_path=keyframe_path,
                llm_note=llm_note,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return int(row.id or 0)

    async def set_anomaly_keyframe(self, anomaly_id: int, path: str) -> None:
        """이상 프레임 저장 경로를 뒤늦게 채운다(§4 `GET /anomalies`).

        파일명이 `{anomaly_id}.jpg` 라 **행이 먼저 생겨야** 이름이 정해진다. 그래서
        경로는 두 번째 쓰기로 들어간다 — 이 갱신을 빼먹으면 파일은 디스크에 있는데
        목록의 `keyframe_url` 은 영원히 `null` 이고, 그 사실은 화면에 「그림 없음」으로만
        보여 저장이 실패한 것과 구분되지 않는다.
        """
        await asyncio.to_thread(self._set_anomaly_keyframe, anomaly_id, path)

    def _set_anomaly_keyframe(self, anomaly_id: int, path: str) -> None:
        with Session(self._engine) as session:
            row = session.get(AnomalyRow, anomaly_id)
            if row is None:
                log.warning("이상 플래그가 없어 키프레임 경로를 남기지 못했다 — %s", anomaly_id)
                return
            row.keyframe_path = path
            session.add(row)
            session.commit()

    async def list_anomalies(
        self, from_: datetime | None, limit: int
    ) -> list[tuple[int, int, float, datetime, str | None, str | None]]:
        """최근 이상 플래그. 분석 화면(FN-UI-05)과 지표의 `anomaly_flags` 가 쓴다."""
        return await asyncio.to_thread(self._list_anomalies, from_, limit)

    def _list_anomalies(
        self, from_: datetime | None, limit: int
    ) -> list[tuple[int, int, float, datetime, str | None, str | None]]:
        statement = select(AnomalyRow).order_by(col(AnomalyRow.detected_at).desc()).limit(limit)
        if from_ is not None:
            statement = statement.where(col(AnomalyRow.detected_at) >= from_)
        with Session(self._engine) as session:
            rows = list(session.exec(statement).all())
        return [
            (
                int(row.id or 0),
                row.cam_id,
                row.score,
                # `detected_at` 은 항상 채워 넣는 칸이다. 비어 있으면 행이 깨진 것이므로
                # 자정 같은 그럴듯한 값으로 메우지 않고 건너뛴다.
                row.detected_at,
                row.keyframe_path,
                row.llm_note,
            )
            for row in rows
            if row.detected_at is not None
        ]


class DbZoneRepository:
    """`server.domain.repository.ZoneRepository` 구현. 기능명세서 §6 `zones`"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def list_zones(self, cam_id: int | None = None) -> list[Zone]:
        return await asyncio.to_thread(self._list_zones, cam_id)

    def _list_zones(self, cam_id: int | None) -> list[Zone]:
        statement = select(ZoneRow).order_by(col(ZoneRow.cam_id), col(ZoneRow.zone_id))
        if cam_id is not None:
            statement = statement.where(col(ZoneRow.cam_id) == cam_id)
        with Session(self._engine) as session:
            return [_zone(row) for row in session.exec(statement)]

    async def get(self, zone_id: str) -> Zone | None:
        return await asyncio.to_thread(self._get, zone_id)

    def _get(self, zone_id: str) -> Zone | None:
        with Session(self._engine) as session:
            row = session.get(ZoneRow, zone_id)
            return _zone(row) if row else None

    async def delete(self, zone_id: str) -> bool:
        """구역 삭제. 없던 구역이면 `False`(§5.4 `action: "delete"`)."""
        return await asyncio.to_thread(self._delete, zone_id)

    def _delete(self, zone_id: str) -> bool:
        with Session(self._engine) as session:
            row = session.get(ZoneRow, zone_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    async def upsert(self, zone: Zone) -> None:
        await asyncio.to_thread(self._upsert, zone)

    def _upsert(self, zone: Zone) -> None:
        with Session(self._engine) as session:
            row = session.get(ZoneRow, zone.zone_id) or ZoneRow(
                zone_id=zone.zone_id, cam_id=zone.cam_id, name=zone.name
            )
            row.cam_id = zone.cam_id
            row.name = zone.name
            row.polygon_m = [list(point) for point in zone.polygon_m]
            row.polygon = [list(point) for point in zone.polygon]
            row.buffer_m = zone.buffer_m
            row.active = zone.active
            session.add(row)
            session.commit()


class DbCameraRepository:
    """`server.domain.repository.CameraRepository` 구현. 기능명세서 §6 `cameras`

    캘리브레이션 결과(호모그래피)가 여기 산다. **카메라를 물리적으로 움직이면 다시
    찍어야 한다**(API명세서 §6.2) — 그 사실이 `calibrated_at` 으로 드러난다.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def list_cameras(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_cameras)

    def _list_cameras(self) -> list[dict[str, Any]]:
        statement = select(CameraRow).order_by(col(CameraRow.cam_id))
        with Session(self._engine) as session:
            return [row.model_dump() for row in session.exec(statement)]

    async def get_homography(self, cam_id: int) -> list[list[float]] | None:
        return await asyncio.to_thread(self._get_homography, cam_id)

    def _get_homography(self, cam_id: int) -> list[list[float]] | None:
        with Session(self._engine) as session:
            row = session.get(CameraRow, cam_id)
            return None if row is None else row.homography

    async def save_calibration(
        self,
        cam_id: int,
        homography: list[list[float]],
        ref_height: dict[str, Any] | None,
        calibrated_at: datetime,
        calib_points: list[dict[str, Any]] | None = None,
        reproj_error_m: float | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._save_calibration,
            cam_id,
            homography,
            ref_height,
            calibrated_at,
            calib_points,
            reproj_error_m,
        )

    def _save_calibration(
        self,
        cam_id: int,
        homography: list[list[float]],
        ref_height: dict[str, Any] | None,
        calibrated_at: datetime,
        calib_points: list[dict[str, Any]] | None,
        reproj_error_m: float | None,
    ) -> None:
        with Session(self._engine) as session:
            row = session.get(CameraRow, cam_id)
            if row is None:
                # 카메라 행이 없으면 만들지 않는다 — `rtsp_main`·`rtsp_sub` 를 지어낼 수
                # 없고, 지어낸 주소로는 아무 영상도 오지 않는다. 라우터가 404 로 알린다.
                msg = f"등록되지 않은 카메라다: {cam_id}"
                raise LookupError(msg)
            row.homography = homography
            row.ref_height = ref_height
            row.calib_points = calib_points
            row.reproj_error_m = reproj_error_m
            row.calibrated_at = calibrated_at
            session.add(row)
            session.commit()

    async def patch_camera(self, cam_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
        """`PATCH /cameras/{cam_id}` (API명세서 §4.5). 없는 카메라면 `None`."""
        return await asyncio.to_thread(self._patch_camera, cam_id, changes)

    def _patch_camera(self, cam_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
        with Session(self._engine) as session:
            row = session.get(CameraRow, cam_id)
            if row is None:
                return None
            for key, value in changes.items():
                setattr(row, key, value)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.model_dump()


class DbVehicleClassRepository:
    """`server.domain.repository.VehicleClassRepository` 구현. FN-CFG-05

    위험 반경은 장비를 따라다니는 **동적 영역**이고 근접 임계값(`proximity_threshold_m`)은
    **즉시 경고 기준**이다. 둘은 2단계로 동작하므로 저장 위치도 다르다(§4.5).
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def list_vehicle_classes(self) -> list[VehicleClass]:
        return await asyncio.to_thread(self._list_vehicle_classes)

    def _list_vehicle_classes(self) -> list[VehicleClass]:
        statement = select(VehicleClassRow).order_by(col(VehicleClassRow.class_name))
        with Session(self._engine) as session:
            return [
                VehicleClass(
                    class_name=row.class_name,
                    danger_radius_m=row.danger_radius_m,
                    active=row.active,
                )
                for row in session.exec(statement)
            ]

    async def patch(self, class_name: str, changes: dict[str, Any]) -> VehicleClass | None:
        """없는 클래스면 `None`. **새로 만들지 않는다** — 감지 클래스는 2종 고정이고
        (절대규칙 11) 런타임에 추가하는 경로가 있으면 그 규칙이 무너진다."""
        return await asyncio.to_thread(self._patch_vehicle_class, class_name, changes)

    def _patch_vehicle_class(self, class_name: str, changes: dict[str, Any]) -> VehicleClass | None:
        with Session(self._engine) as session:
            row = session.get(VehicleClassRow, class_name)
            if row is None:
                return None
            for key, value in changes.items():
                setattr(row, key, value)
            session.add(row)
            session.commit()
            session.refresh(row)
            return VehicleClass(
                class_name=row.class_name,
                danger_radius_m=row.danger_radius_m,
                active=row.active,
            )


class DbSoundRepository:
    """`server.domain.repository.SoundRepository` 구현. 기능명세서 §6 `alert_sounds`

    등급(`level`)까지 여기서 온다 — 관리자가 설정 화면에서 바꾸는 값이므로 코드에
    박힌 표가 아니라 이 행이 §3 `AlertCommand.level` 의 원천이다(절대규칙 6).
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def load_sounds(self) -> dict[str, SoundEntry]:
        return await asyncio.to_thread(self._load_sounds)

    def _load_sounds(self) -> dict[str, SoundEntry]:
        statement = select(SoundRow).where(col(SoundRow.active).is_(True))
        with Session(self._engine) as session:
            return {row.violation_type: _sound_entry(row) for row in session.exec(statement)}

    async def list_sounds(self) -> list[AlertSound]:
        """`GET /alert-sounds`(§4.5) — **꺼진 항목도 포함한 전량**.

        `load_sounds` 와 다른 이유: 경고 경로는 켜진 것만 알면 되지만, 설정 화면은 꺼진
        항목을 다시 켤 수 있어야 한다. 꺼진 것을 감추면 화면에서 되살릴 방법이 없다.
        """
        return await asyncio.to_thread(self._list_sounds)

    def _list_sounds(self) -> list[AlertSound]:
        statement = select(SoundRow).order_by(col(SoundRow.violation_type))
        with Session(self._engine) as session:
            return [_alert_sound(row) for row in session.exec(statement)]

    async def patch_sound(self, violation_type: str, changes: dict[str, Any]) -> AlertSound | None:
        """`PUT /alert-sounds/{violation_type}`(§4.5). 없는 유형이면 `None`.

        **행을 새로 만들지 않는다.** 등록되지 않은 이름으로 만들 수 있게 하면 오타가
        그대로 새 음원 키가 되고, 그 키는 아무도 재생하지 않는다.
        """
        return await asyncio.to_thread(self._patch_sound, violation_type, changes)

    def _patch_sound(self, violation_type: str, changes: dict[str, Any]) -> AlertSound | None:
        with Session(self._engine) as session:
            row = session.get(SoundRow, violation_type)
            if row is None:
                return None
            for key, value in changes.items():
                setattr(row, key, value)
            session.add(row)
            session.commit()
            session.refresh(row)
            return _alert_sound(row)


class DbPolicyRepository:
    """`server.domain.repository.PolicyRepository` 구현. 기능명세서 §6 `policies`

    임계값·타이머는 코드가 아니라 여기서만 읽는다(CLAUDE.md 절대규칙 6).
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def load(self) -> Policies:
        return await asyncio.to_thread(self._load)

    def _load(self) -> Policies:
        with Session(self._engine) as session:
            rows = list(session.exec(select(PolicyRow)))
        stored = {row.key: row.value for row in rows}
        known = set(Policies.model_fields)
        # 계약에 없는 키가 DB 에 있으면 시드와 명세서가 어긋난 것이다. 조용히 버리지 않는다.
        for key in sorted(set(stored) - known):
            log.warning("policies 테이블에 계약에 없는 키가 있다: %s", key)
        return Policies.model_validate({k: v for k, v in stored.items() if k in known})

    async def patch(self, changes: dict[str, Any]) -> Policies:
        await asyncio.to_thread(self._patch, changes)
        return await self.load()

    def _patch(self, changes: dict[str, Any]) -> None:
        with Session(self._engine) as session:
            for key, value in changes.items():
                row = session.get(PolicyRow, key) or PolicyRow(key=key, value=value)
                row.value = value
                session.add(row)
            session.commit()


# --------------------------------------------------------------------------
# 행 ↔ 계약 모델
# --------------------------------------------------------------------------


def _detected_at(row: EventRow) -> datetime:
    """`detected_at` 은 §4.1 에서 필수다. 비어 있으면 레코드가 깨진 것이다."""
    if row.detected_at is None:
        msg = f"detected_at 이 비어 있다: {row.event_id}"
        raise ValueError(msg)
    return row.detected_at


def _summary(row: EventRow, repeat_count_7d: int) -> EventSummary:
    return EventSummary(
        event_id=row.event_id,
        cam_id=row.cam_id,
        track_id=row.track_id,
        violation_type=ViolationType(row.violation_type),
        zone_id=row.zone_id,
        status=EventStatus(row.status),
        detected_at=_detected_at(row),
        confirmed_at=row.confirmed_at,
        alerted_at=row.alerted_at,
        # §4.1 이 응답에 추가한 두 칸. 컬럼만 있고 읽을 경로가 없던 시기가 끝났다.
        last_alerted_at=row.last_alerted_at,
        note=row.note,
        resolved_at=row.resolved_at,
        resolution_sec=row.resolution_sec,
        alert_count=row.alert_count,
        min_distance_m=row.min_distance_m,
        posture=row.posture,  # type: ignore[arg-type]
        repeat_count_7d=repeat_count_7d,
        thumbnail_url=_media_url(row.keyframe_paths[0]) if row.keyframe_paths else None,
    )


def _detail(row: EventRow, repeat_count_7d: int) -> EventDetail:
    return EventDetail(
        **_summary(row, repeat_count_7d).model_dump(),
        clip_url=_media_url(row.clip_path),
        keyframe_urls=[url for path in row.keyframe_paths if (url := _media_url(path))],
        helmet_conf=row.helmet_conf,
        stillness_s=row.stillness_s,
        height_ratio=row.height_ratio,
        depth_verified=row.depth_verified,
        nearby_snapshot=row.nearby_snapshot,  # type: ignore[arg-type]
        llm_analysis=row.llm_analysis,
        regulation_refs=row.regulation_refs,  # type: ignore[arg-type]
        similar_incidents=row.similar_incidents,  # type: ignore[arg-type]
        timeline=_timeline(row),
        clip_status=row.clip_status,  # type: ignore[arg-type]
        clip_error=row.clip_error,
        alert_suppressed=row.alert_suppressed,
    )


def _timeline(row: EventRow) -> list[TimelineEntry]:
    """상태 전이 타임라인(§4.1). **저장된 시각들로 재구성한다.**

    전이 로그 테이블을 따로 두지 않는 이유는 기능명세서 §6 에 그런 테이블이 없기
    때문이다. 전이표(§4.2)의 각 상태에는 대응하는 시각 컬럼이 하나씩 있으므로
    그것만으로 순서가 복원된다.

    `re_alerted` 는 **마지막 재경고 하나만** 나온다(`last_alerted_at`). 중간 재경고
    시각을 담는 자리는 없고 `alert_count` 만 남으므로, 없는 시각을 지어내지 않는다.

    종결 셋(`resolved` · `expired` · `dropped`)이 모두 나온다 — §6 이 `dropped_at` 을
    신설하면서 확정 전 소멸도 타임라인에서 끝을 갖게 됐다.
    """
    stamps: list[tuple[datetime | None, EventStatus]] = [
        (row.detected_at, EventStatus.CANDIDATE),
        (row.confirmed_at, EventStatus.ACTIVE),
        (row.alerted_at, EventStatus.ALERTED),
        (row.last_alerted_at if row.alert_count > 1 else None, EventStatus.RE_ALERTED),
        (row.lost_at, EventStatus.LOST),
        (row.resolved_at, EventStatus.RESOLVED),
        (row.expired_at, EventStatus.EXPIRED),
        (row.dropped_at, EventStatus.DROPPED),
    ]
    entries = [TimelineEntry(at=at, state=state) for at, state in stamps if at is not None]
    return sorted(entries, key=lambda entry: entry.at)


def _row(event: EventDetail) -> EventRow:
    return EventRow(
        event_id=event.event_id,
        cam_id=event.cam_id,
        track_id=event.track_id,
        violation_type=event.violation_type.value,
        zone_id=event.zone_id,
        status=event.status.value,
        detected_at=event.detected_at,
        confirmed_at=event.confirmed_at,
        alerted_at=event.alerted_at,
        last_alerted_at=event.last_alerted_at,
        note=event.note,
        resolved_at=event.resolved_at,
        resolution_sec=event.resolution_sec,
        alert_count=event.alert_count,
        min_distance_m=event.min_distance_m,
        depth_verified=event.depth_verified,
        posture=event.posture,
        stillness_s=event.stillness_s,
        height_ratio=event.height_ratio,
        helmet_conf=event.helmet_conf,
        nearby_snapshot=[item.model_dump(by_alias=True) for item in event.nearby_snapshot],
        similar_incidents=[item.model_dump() for item in event.similar_incidents],
        regulation_refs=[item.model_dump() for item in event.regulation_refs],
        llm_analysis=event.llm_analysis,
        clip_status=event.clip_status,
        clip_error=event.clip_error,
        alert_suppressed=event.alert_suppressed,
    )


def _zone(row: ZoneRow) -> Zone:
    return Zone(
        zone_id=row.zone_id,
        cam_id=row.cam_id,
        name=row.name,
        polygon_m=[(point[0], point[1]) for point in row.polygon_m],
        polygon=[(point[0], point[1]) for point in row.polygon],
        buffer_m=row.buffer_m,
        active=row.active,
    )


def _sound_entry(row: SoundRow) -> SoundEntry:
    """`alert_sounds` 한 행 → 도메인 값."""
    return SoundEntry(
        file_path=row.file_path,
        level=_level(row),
        label=row.label,
    )


def _alert_sound(row: SoundRow) -> AlertSound:
    """`alert_sounds` 한 행 → §4.5 응답 모델."""
    return AlertSound(
        violation_type=row.violation_type,
        file_path=row.file_path,
        level=_level(row),
        label=row.label,
        active=row.active,
    )


def _level(row: SoundRow) -> AlertLevel:
    """`alert_sounds.level` 을 §3 이 허용하는 값으로 좁힌다.

    §3 은 `1|2|3` 만 허용하는데 DB 컬럼은 `int` 다. 범위를 벗어난 값이 들어 있으면
    **조용히 고치지 않고** 기본 「경고」 급으로 낮추고 로그를 남긴다 — ESP32 가 모르는
    등급을 받으면 아무 패턴도 켜지 않아 경보가 사라진다.

    **안전 하한(§3)도 여기서 다시 본다.** API 가 막지만(`check_level`) DB 를 직접 고칠
    수도 있고, 그렇게 들어온 `fall` = 2 를 그대로 쓰면 긴급 상황에서 부저가 울리지
    않는다. 읽는 쪽에서 하한으로 끌어올리고 그 사실을 남긴다.
    """
    level = row.level
    if level not in (1, 2, 3):
        log.error(
            "alert_sounds.%s 의 level 이 %s 다 — §3 은 1|2|3 만 허용한다. 2 로 다룬다",
            row.violation_type,
            level,
        )
        level = 2
    try:
        check_level(row.violation_type, cast("AlertLevel", level))
    except LevelFloorError as exc:
        floor = MINIMUM_LEVEL[ViolationType(row.violation_type)]
        log.error("%s — %d 로 올려서 쓴다", exc, floor)
        level = floor
    return cast("AlertLevel", level)


def _media_url(path: str | None) -> str | None:
    """저장 경로를 클라이언트가 쓸 URL 로 바꾼다. §5 「경로 규약」

    파일시스템 경로(`clip_path` · `keyframe_paths`)를 그대로 내려보내지 않는다 —
    서버 디렉토리 구조가 새어 나가고, M9 에서 REC 이 젯슨으로 옮겨가면 그 경로는
    클라이언트 입장에서 아무 의미가 없어진다.
    """
    if not path:
        return None
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if "media" in parts:
        parts = parts[parts.index("media") + 1 :]
    return f"{MEDIA_URL_PREFIX}/{'/'.join(parts)}"


def _encode_cursor(row: EventRow) -> str:
    payload = json.dumps({"at": _detected_at(row).isoformat(), "id": row.event_id})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    """커서를 되푼다. 깨진 커서는 **무시하지 않고** 오류를 낸다.

    조용히 첫 장으로 되돌리면 클라이언트는 목록이 끝난 줄 알거나 같은 장을 무한히 돈다.
    """
    if not cursor:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(payload["at"]), str(payload["id"])
    except (binascii.Error, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        msg = f"커서를 해석할 수 없다: {cursor!r}"
        raise ValueError(msg) from exc
