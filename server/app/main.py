"""FastAPI 진입점 — 조립만 한다.

    uv run uvicorn server.app.main:app --reload

붙어 있는 것:

* `GET /api/v1/system/status` (§4.6 · FN-SYS-01)
* `GET /api/v1/events` · `/events/{id}` · `PATCH /events/{id}` (§4.1 · FN-EVT-05)
* `GET /api/v1/metrics/summary` (§4.2 · FN-SYS-04 · FN-SYS-05)
* `GET /api/v1/zones` · `/policies` (§4.5) — 오버레이가 읽는 폴리곤과 지연 버퍼
* `/ws/edge` (§2) — 엣지 메시지 수신 · 검증 · 상태머신 입력 (FN-EVT-01 · FN-SYS-06)
* `/ws/dashboard` (§5) — `system` · `overlay` · `event_created` · `event_updated` · `metric`
* 이벤트 상태머신 틱 (확정 · 해소 · 쿨다운 · 소실 유예 · 재결합)
* mediamtx 폴링으로 메인 스트림 상태 관측 (`server/infra/stream`)
* 기동 시 NTP 오프셋 확인 (FN-SYS-02)

경고 발동(wav · MQTT)과 클립 예약 추출은 M4 다.

**여기에 로직을 두지 않는다.** 이 파일은 설정을 읽어 부품을 연결하고 수명주기를
관리하는 곳이고, 시스템 시계를 읽는 `RealClock` 을 만드는 곳이기도 하다
(CLAUDE.md 절대규칙 1 — 조립 지점에서만 만든다).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aegis_contracts import ComponentSystemMsg, Policies
from aegis_contracts.enums import ComponentState, StreamState
from aegis_vision.clock import Clock, RealClock
from server.app.config import ServerSettings, get_server_settings
from server.app.event_service import (
    POLICY_REFRESH_SECONDS,
    TICK_SECONDS,
    EventService,
    EventStore,
    PolicyReader,
)
from server.app.routes import events as event_routes
from server.app.routes import metrics as metric_routes
from server.app.routes import policies as policy_routes
from server.app.routes import system as system_routes
from server.app.routes import zones as zone_routes
from server.app.ws_dashboard import DashboardHub
from server.app.ws_edge import EdgeGateway
from server.domain.edge_state import EdgeRuntime
from server.domain.event_machine import EventMachine
from server.domain.overlay import LiveTracks
from server.infra.db.repository import (
    DbEventRepository,
    DbPolicyRepository,
    DbZoneRepository,
)
from server.infra.db.session import create_db_engine
from server.infra.rec_client import RecClient, RecUnavailableError, StorageReader
from server.infra.stream import MediaMtxClient, StreamWatcher
from server.infra.timesync import check_time_sync

__all__ = ["API_PREFIX", "app", "create_app"]

log = logging.getLogger("server")

#: API명세서 §1.1 — Base URL `http://<server-host>:8000/api/v1`
API_PREFIX = "/api/v1"

#: REC 생존 확인 주기(초). 용량은 급변하지 않으므로 카메라만큼 자주 볼 필요가 없다.
_STORAGE_POLL_SECONDS = 10.0


class StreamObserver(Protocol):
    """`create_app` 이 요구하는 스트림 감시자. 테스트가 가짜를 끼워 넣을 자리다."""

    def states(self) -> dict[int, StreamState]: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


def create_app(
    settings: ServerSettings | None = None,
    clock: Clock | None = None,
    *,
    rec_client: StorageReader | None = None,
    stream_watcher: StreamObserver | None = None,
    events: EventStore | None = None,
    zones: object | None = None,
    policies: PolicyReader | None = None,
) -> FastAPI:
    """부품을 조립한다. 인자를 주지 않으면 설정에 맞는 실물을 만든다.

    `rec_client` · `stream_watcher` 를 주입받는 이유는 테스트 때문만이 아니다.
    이 둘은 **바깥 프로세스에 붙는 유일한 통로**라, 여기서 갈아끼울 수 있어야
    M9 에서 REC 을 젯슨으로 옮길 때 서버 코드를 건드리지 않는다.

    저장소 셋(`events` · `zones` · `policies`)도 같은 이유로 주입 가능하다. 기본값은
    `.env` 의 `DATABASE_URL` 로 만든 DB 구현이며, **엔진 생성은 접속하지 않으므로**
    DB 가 꺼져 있어도 기동은 된다 — 그 사실은 각 라우터가 503 으로 드러낸다.
    """
    resolved = settings or get_server_settings()
    ticker: Clock = clock or RealClock()

    engine = create_db_engine() if events is None or zones is None or policies is None else None
    hub = DashboardHub()
    edge = EdgeRuntime()
    tracks = LiveTracks()
    event_store: EventStore | None = events or (DbEventRepository(engine) if engine else None)
    policy_reader: PolicyReader | None = policies or (
        DbPolicyRepository(engine) if engine else None
    )
    # 임계값은 기동 직후 DB 에서 덮어쓴다(`EventService.start`). 여기 있는 `Policies()`
    # 는 계약 기본값이며 DB 시드의 원천이기도 하다(절대규칙 6).
    event_service = EventService(
        machine=EventMachine(clock=ticker, policies=Policies()),
        tracks=tracks,
        publish=hub.broadcast,
        clock=ticker,
        store=event_store,
        policies=policy_reader,
    )
    storage: StorageReader = rec_client or RecClient(resolved.recorder_base)
    watcher: StreamObserver = stream_watcher or StreamWatcher(
        client=MediaMtxClient(resolved.mediamtx_api),
        cam_ids=resolved.cam_ids,
        clock=ticker,
        publish=hub.broadcast,
        poll_seconds=resolved.stream_poll_seconds,
        down_after_seconds=resolved.stream_down_after_seconds,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # FN-SYS-02 — 클립 구간 정합의 전제. 실패해도 기동을 막지 않되 반드시 남긴다.
        await check_time_sync(
            resolved.ntp_server,
            ticker,
            warn_offset_ms=resolved.ntp_warn_offset_ms,
        )
        await watcher.start()
        # 재시작 전에 열려 있던 이벤트를 되살린다. 두지 않으면 그 이벤트들이
        # 영원히 미해소로 남아 시정률 분모를 오염시킨다.
        await event_service.start()
        storage_task = asyncio.create_task(
            _watch_storage(storage, hub, ticker), name="storage-watch"
        )
        tick_task = asyncio.create_task(_tick_events(event_service), name="event-tick")
        log.info(
            "서버 기동 — cams=%s mediamtx=%s rec=%s",
            resolved.cam_ids,
            resolved.mediamtx_api,
            resolved.recorder_base,
        )
        try:
            yield
        finally:
            for task in (storage_task, tick_task):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await watcher.stop()
            await storage.aclose()

    application = FastAPI(
        title="AEGIS",
        version="0.1.0",
        summary="자율 현장 대응형 AI 안전관제 시스템",
        lifespan=lifespan,
    )
    # 프론트는 개발 중 vite dev 서버(:5173)에서 뜨므로 오리진이 다르다.
    application.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.state.settings = resolved
    application.state.clock = ticker
    application.state.hub = hub
    application.state.rec_client = storage
    application.state.stream_watcher = watcher
    application.state.edge = edge
    application.state.tracks = tracks
    application.state.events = event_store
    application.state.event_service = event_service
    application.state.zones = zones or (DbZoneRepository(engine) if engine else None)
    application.state.policies = policy_reader

    application.include_router(system_routes.router, prefix=API_PREFIX)
    application.include_router(event_routes.router, prefix=API_PREFIX)
    application.include_router(metric_routes.router, prefix=API_PREFIX)
    application.include_router(zone_routes.router, prefix=API_PREFIX)
    application.include_router(policy_routes.router, prefix=API_PREFIX)

    @application.exception_handler(HTTPException)
    async def spec_error(request: Request, exc: HTTPException) -> JSONResponse:
        """오류 본문을 §1.4 봉투 그대로 내보낸다.

        FastAPI 기본 처리기는 `detail` 을 한 겹 더 감싸 `{"detail": {"error": ...}}`
        가 되는데, 그러면 클라이언트가 계약과 다른 모양을 보게 된다.
        """
        del request
        # `HTTPException.detail` 은 선언상 `str` 이지만 실제로는 무엇이든 담긴다.
        body: object = exc.detail
        if isinstance(body, dict) and "error" in body:
            return JSONResponse(status_code=exc.status_code, content=body)
        return JSONResponse(status_code=exc.status_code, content={"detail": body})

    @application.get("/health")
    def health() -> dict[str, str]:
        """부팅 스모크용. 구성요소 상태는 `GET /api/v1/system/status`(FN-SYS-01) 소관이다."""
        return {"status": "ok"}

    @application.websocket("/ws/edge")
    async def edge_socket(websocket: WebSocket) -> None:
        """API명세서 §2. 검증에 실패한 메시지는 집계하고 버린다(FN-SYS-06)."""
        gateway = EdgeGateway(
            edge=edge,
            tracks=tracks,
            publish=hub.broadcast,
            clock=ticker,
            events=event_service,
        )
        await gateway.serve(websocket)

    @application.websocket("/ws/dashboard")
    async def dashboard(websocket: WebSocket) -> None:
        """API명세서 §5. 서버가 일방적으로 밀어 넣는다 — 클라이언트 메시지는 받지 않는다.

        전체 스냅샷이 필요하면 `GET /api/v1/system/status` 를 쓴다(§5.3).
        """
        await hub.connect(websocket)
        try:
            while True:
                # 수신은 연결 유지 확인용이다. 내용은 계약에 없으므로 버린다.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await hub.disconnect(websocket)

    return application


async def _tick_events(service: EventService) -> None:
    """상태머신에 시간을 흘려보낸다 — 소실 감지 · 유예 만료 · 쿨다운.

    확정과 해소는 프레임이 도착할 때 그 자리에서 판정되므로 이 루프에 걸리지 않는다.
    여기서 도는 것은 **관측이 끊겼을 때에도 결론이 나야 하는 것들**이다. 이 루프가
    없으면 엣지가 죽은 순간의 진행 중 이벤트가 영원히 열린 채 남는다.

    예외를 삼키지 않는다(CLAUDE.md 절대규칙 9). 한 번의 실패로 루프를 죽이면 그 뒤
    모든 이벤트가 종결되지 않으므로 로그를 남기고 계속 돈다.
    """
    since_refresh = 0.0
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            await service.tick()
        except Exception:
            log.exception("이벤트 틱이 실패했다 — 다음 주기에 다시 시도한다")
        since_refresh += TICK_SECONDS
        if since_refresh >= POLICY_REFRESH_SECONDS:
            since_refresh = 0.0
            await service.refresh_policies()


async def _watch_storage(client: StorageReader, hub: DashboardHub, clock: Clock) -> None:
    """REC 생존 확인. 상태가 **변할 때만** `system` 을 발행한다(§5.3).

    REC 이 죽으면 7일 녹화가 멈춘다 — 이벤트가 나도 클립을 뽑을 원본이 없다.
    `GET /system/status` 의 `storage` 가 `null` 이 되는 것과 짝을 이루는 통지다.
    """
    state: ComponentState | None = None
    while True:
        try:
            await client.status()
            observed: ComponentState = "ok"
            detail = "REC 정상"
        except RecUnavailableError as exc:
            observed = "down"
            detail = f"REC 응답 없음: {exc}"

        if observed != state:
            log.info("storage %s -> %s", state, observed)
            await hub.broadcast(
                ComponentSystemMsg(
                    component="storage",
                    state=observed,
                    detail=detail,
                    at=clock.now(),
                )
            )
            state = observed
        await asyncio.sleep(_STORAGE_POLL_SECONDS)


app = create_app()
