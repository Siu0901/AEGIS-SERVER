"""FastAPI 진입점 — 조립만 한다.

    uv run uvicorn server.app.main:app --reload

붙어 있는 것:

* `GET /api/v1/system/status` (§4.6 · FN-SYS-01)
* `GET /api/v1/events` · `/events/{id}` · `PATCH /events/{id}` (§4.1 · FN-EVT-05)
* `GET /api/v1/metrics/summary` (§4.2 · FN-SYS-04 · FN-SYS-05)
* `GET /api/v1/zones` · `/policies` (§4.5) — 오버레이가 읽는 폴리곤과 지연 버퍼
* 설정 API (§4.5 · FN-CFG-01~05) — 캘리브레이션 · 구역 편집 · 음원 · 임계값 · 위험 반경
* `/ws/edge` (§2) — 엣지 메시지 수신 · 검증 · 상태머신 입력 (FN-EVT-01 · FN-SYS-06)
* `POST /api/v1/alerts/manual` · `/alerts/mute` (§4.5 · FN-ALM-04 · FN-ALM-05)
* `GET /api/v1/events/{id}/clip` · `/media/*` (§4.1 · FN-REC-03)
* `/ws/dashboard` (§5) — `system` · `overlay` · `event_created` · `event_updated` · `metric`
* 이벤트 상태머신 틱 (확정 · 해소 · 쿨다운 · 소실 유예 · 재결합)
* 경고 집행 — 사전 녹음 wav 재생 · `aegis/alert` 발행 (FN-ALM-01 · 02)
* 클립 예약 추출 루프 (FN-REC-03) — **예약은 DB 에 있으므로 재시작하면 그대로 복구된다**
* mediamtx 폴링으로 메인 스트림 상태 관측 (`server/infra/stream`)
* 기동 시 NTP 오프셋 확인 (FN-SYS-02)

**여기에 로직을 두지 않는다.** 이 파일은 설정을 읽어 부품을 연결하고 수명주기를
관리하는 곳이고, 시스템 시계를 읽는 `RealClock` 을 만드는 곳이기도 하다
(CLAUDE.md 절대규칙 1 — 조립 지점에서만 만든다).
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from aegis_contracts import ComponentSystemMsg, Policies
from aegis_contracts.enums import ComponentState, StreamState
from aegis_vision.clock import Clock, RealClock
from server.app.alert_service import SOUND_REFRESH_SECONDS, AlertService
from server.app.config import ServerSettings, get_server_settings
from server.app.event_service import (
    POLICY_REFRESH_SECONDS,
    TICK_SECONDS,
    EventService,
    EventStore,
    PolicyReader,
)
from server.app.routes import alerts as alert_routes
from server.app.routes import cameras as camera_routes
from server.app.routes import events as event_routes
from server.app.routes import metrics as metric_routes
from server.app.routes import policies as policy_routes
from server.app.routes import sounds as sound_routes
from server.app.routes import system as system_routes
from server.app.routes import vehicles as vehicle_routes
from server.app.routes import zones as zone_routes
from server.app.ws_dashboard import DashboardHub
from server.app.ws_edge import EdgeGateway
from server.domain.cloud_state import CloudRuntime
from server.domain.edge_state import EdgeRuntime
from server.domain.event_machine import EventMachine
from server.domain.mcu_state import McuRuntime
from server.domain.overlay import LiveTracks
from server.infra.audio import SoundLibrary, SoundReader, resolve_player
from server.infra.clip import CLIP_POLL_SECONDS, ClipService
from server.infra.db.repository import (
    DbCameraRepository,
    DbEventRepository,
    DbPolicyRepository,
    DbSoundRepository,
    DbVehicleClassRepository,
    DbZoneRepository,
)
from server.infra.db.session import create_db_engine
from server.infra.mqtt import MqttAlertClient
from server.infra.rec_client import RecClient, RecUnavailableError, StorageReader
from server.infra.stream import MediaMtxClient, StreamWatcher
from server.infra.timesync import check_time_sync

__all__ = ["API_PREFIX", "app", "create_app"]

log = logging.getLogger("server")

#: API명세서 §1.1 — Base URL `http://<server-host>:8000/api/v1`
API_PREFIX = "/api/v1"

#: REC 생존 확인 주기(초). 용량은 급변하지 않으므로 카메라만큼 자주 볼 필요가 없다.
_STORAGE_POLL_SECONDS = 10.0


def _configure_logging() -> None:
    """서버 자신의 로그가 보이게 한다.

    **uvicorn 은 자기 로거만 설정한다.** 루트 로거에 핸들러가 없으면 우리가 남긴
    `log.info` 는 어디에도 나오지 않고, 접근 로그만 남아 "요청은 200 인데 무슨 일이
    있었는지는 모르는" 상태가 된다. 실제로 이번에 캘리브레이션 저장·`zone_updated`
    발행·클립 예약 로그가 전부 사라져 있었다 — 가드가 조용히 꺼진 것과 같다(절대규칙 9).

    이미 핸들러가 있으면(테스트 러너 · 직접 설정) 건드리지 않는다.
    """
    if logging.getLogger().handlers:
        return
    # 한글 Windows 의 콘솔 인코딩(cp949)으로는 로그의 한글과 '—' 가 깨진다. 파일로
    # 넘길 때도 마찬가지라 나중에 읽을 수 없는 로그가 남는다. `tasks.py` · 시드
    # 스크립트와 같은 처리를 서버에도 둔다.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    # HTTP 클라이언트의 INFO 는 **요청 한 줄씩**이다. 스트림 감시가 mediamtx 를 초당
    # 한 번 폴링하므로(FN-SYS-01) 그대로 두면 우리 로그가 그 줄에 파묻힌다 — M5 에서
    # 접근 로그가 덮어버린 것과 같은 문제다. 실패는 WARNING 이상이라 그대로 보인다.
    logging.getLogger("httpx2").setLevel(logging.WARNING)


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
    sounds: SoundReader | None = None,
    cameras: object | None = None,
    vehicle_classes: object | None = None,
    alerts: AlertService | None = None,
    clips: ClipService | None = None,
    mqtt: MqttAlertClient | None = None,
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
    mcu = McuRuntime(stale_after_s=resolved.mcu_stale_after_s)
    cloud = CloudRuntime()
    tracks = LiveTracks()
    event_store: EventStore | None = events or (DbEventRepository(engine) if engine else None)
    policy_reader: PolicyReader | None = policies or (
        DbPolicyRepository(engine) if engine else None
    )
    storage: StorageReader = rec_client or RecClient(resolved.recorder_base)

    # FN-ALM-02 — 브로커가 없어도 기동을 막지 않는다. 붙는 것은 `start()` 에서 비동기로
    # 시도하고, 그때까지 경광등 경고는 실패로 집계된다(조용히 성공하지 않는다).
    mqtt_client = mqtt
    if mqtt_client is None and alerts is None:
        mqtt_client = MqttAlertClient(
            host=resolved.mqtt_host,
            port=resolved.mqtt_port,
            mcu=mcu,
            clock=ticker,
            publish=hub.broadcast,
        )
    # FN-ALM-01 — 음원 매핑은 DB 에서 읽는다(절대규칙 6). 파일명이 코드에 없다.
    alert_service = alerts or AlertService(
        library=SoundLibrary(
            resolved.audio_dir,
            sounds or (DbSoundRepository(engine) if engine else None),
        ),
        player=resolve_player(resolved.audio_backend),
        clock=ticker,
        mcu=mcu,
        mqtt=mqtt_client,
        publish=hub.broadcast,
    )
    # FN-REC-03 — 예약 큐는 DB 의 `clip_status = pending` 이다. 메모리 타이머를 쓰지
    # 않으므로 재시작해도 예약이 남는다.
    clip_service = clips
    if clip_service is None and event_store is not None and isinstance(storage, RecClient):
        clip_service = ClipService(
            rec=storage,
            store=event_store,  # type: ignore[arg-type]
            clock=ticker,
            media_root=resolved.media_root,
            publish=hub.broadcast,
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
        alerts=alert_service,
        clips=clip_service,
    )
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
        if mqtt_client is not None:
            await mqtt_client.start()
        await alert_service.start()
        # 재시작 전에 열려 있던 이벤트를 되살린다. 두지 않으면 그 이벤트들이
        # 영원히 미해소로 남아 시정률 분모를 오염시킨다.
        await event_service.start()
        # 위험 등급(§3 `level` · §5.2 `severity`)의 원천은 DB `alert_sounds.level` 이다
        # (§6 · FN-CFG-03 · 절대규칙 6). 상태머신은 그것을 **주입받아** 순수성을 지킨다.
        # `alert_service.start()` 가 이미 매핑을 읽었으므로 여기서 넘긴다.
        event_service.machine.set_severity(alert_service.severity_map())
        alert_service.set_policies(event_service.machine.policies)
        if clip_service is not None:
            clip_service.set_policies(event_service.machine.policies)
        tasks = [
            asyncio.create_task(
                _watch_storage(storage, hub, ticker, clip_service), name="storage-watch"
            ),
            asyncio.create_task(
                _tick_events(event_service, alert_service, clip_service), name="event-tick"
            ),
        ]
        if clip_service is not None:
            # 첫 순회가 곧 **재시작 복구**다 — 서버가 죽어 있는 동안 실행 시각이 지난
            # `pending` 잡이 여기서 집힌다(기능명세서 §4.4).
            tasks.append(asyncio.create_task(_run_clips(clip_service), name="clip-jobs"))
        log.info(
            "서버 기동 — cams=%s mediamtx=%s rec=%s mqtt=%s:%s",
            resolved.cam_ids,
            resolved.mediamtx_api,
            resolved.recorder_base,
            resolved.mqtt_host,
            resolved.mqtt_port,
        )
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if clip_service is not None:
                # 뒤로 넘긴 키프레임 추출을 마저 끝낸다. 여기서 버리면 확정 직전에
                # 내린 서버가 그 이벤트의 그림을 영영 남기지 않는다 — 클립과 달리
                # 키프레임은 DB 에 예약이 없어 재시작이 되살려주지 못한다.
                await clip_service.wait_idle()
            await watcher.stop()
            if mqtt_client is not None:
                await mqtt_client.stop()
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
    application.state.mcu = mcu
    application.state.cloud = cloud
    application.state.tracks = tracks
    application.state.events = event_store
    application.state.event_service = event_service
    application.state.alerts = alert_service
    application.state.clips = clip_service
    application.state.zones = zones or (DbZoneRepository(engine) if engine else None)
    # FN-CFG-03 — 설정 화면이 음원 매핑을 읽고 고치는 통로(§4.5). 경고 경로가 쓰는
    # `SoundLibrary` 와 같은 테이블을 본다.
    application.state.sounds = sounds or (DbSoundRepository(engine) if engine else None)
    # FN-CFG-01 · 05 — 캘리브레이션과 위험 반경. 설정 화면이 쓰는 저장소들이다.
    application.state.cameras = cameras or (DbCameraRepository(engine) if engine else None)
    application.state.vehicle_classes = vehicle_classes or (
        DbVehicleClassRepository(engine) if engine else None
    )
    application.state.policies = policy_reader

    application.include_router(system_routes.router, prefix=API_PREFIX)
    application.include_router(event_routes.router, prefix=API_PREFIX)
    application.include_router(metric_routes.router, prefix=API_PREFIX)
    application.include_router(alert_routes.router, prefix=API_PREFIX)
    application.include_router(zone_routes.router, prefix=API_PREFIX)
    application.include_router(policy_routes.router, prefix=API_PREFIX)
    application.include_router(sound_routes.router, prefix=API_PREFIX)
    application.include_router(camera_routes.router, prefix=API_PREFIX)
    application.include_router(vehicle_routes.router, prefix=API_PREFIX)

    # §5 「경로 규약」 — 클라이언트에는 URL 만 나가고(`clip_url` · `keyframe_urls`),
    # 그 URL 이 가리키는 곳이 여기다. 파일시스템 경로는 응답에 실리지 않는다.
    #
    # **REC 의 7일 원본이 아니다.** 여기 있는 것은 서버가 영구 보관하는 이벤트 클립과
    # 키프레임뿐이며, 원본은 엣지 SSD 에 있고 §4.7 API 로만 닿는다(기능명세서 §4.4).
    resolved.media_root.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/media",
        StaticFiles(directory=resolved.media_root),
        name="media",
    )

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


async def _run_clips(service: ClipService) -> None:
    """FN-REC-03 — 실행 시각이 지난 클립 예약을 처리한다.

    **첫 순회가 재시작 복구다.** 예약은 DB 의 `clip_status = pending` 하나로 표현되고
    실행 시각은 `confirmed_at + clip_post_roll_s + margin` 으로 계산되므로, 서버가 죽어
    있는 동안 때가 지난 잡도 여기서 함께 집힌다(기능명세서 §4.4).

    예외를 삼키지 않는다(절대규칙 9). 한 번의 실패로 루프를 죽이면 그 뒤 모든 이벤트가
    증거 없이 남는다.
    """
    while True:
        try:
            await service.run_due()
        except Exception:
            log.exception("클립 예약 처리가 실패했다 — 다음 주기에 다시 시도한다")
        await asyncio.sleep(CLIP_POLL_SECONDS)


async def _tick_events(
    service: EventService,
    alerts: AlertService,
    clips: ClipService | None = None,
) -> None:
    """상태머신에 시간을 흘려보낸다 — 소실 감지 · 유예 만료 · 쿨다운.

    확정과 해소는 프레임이 도착할 때 그 자리에서 판정되므로 이 루프에 걸리지 않는다.
    여기서 도는 것은 **관측이 끊겼을 때에도 결론이 나야 하는 것들**이다. 이 루프가
    없으면 엣지가 죽은 순간의 진행 중 이벤트가 영원히 열린 채 남는다.

    예외를 삼키지 않는다(CLAUDE.md 절대규칙 9). 한 번의 실패로 루프를 죽이면 그 뒤
    모든 이벤트가 종결되지 않으므로 로그를 남기고 계속 돈다.
    """
    since_policy = 0.0
    since_sound = 0.0
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            await service.tick()
        except Exception:
            log.exception("이벤트 틱이 실패했다 — 다음 주기에 다시 시도한다")
        since_policy += TICK_SECONDS
        since_sound += TICK_SECONDS
        if since_policy >= POLICY_REFRESH_SECONDS:
            since_policy = 0.0
            await service.refresh_policies()
            # `mute_default_duration_s`(§4.5)도 DB 값이다. 상태머신이 방금 읽은 것을
            # 그대로 나눠 쓴다 — 두 번 읽으면 같은 순간에 서로 다른 값으로 돈다.
            alerts.set_policies(service.machine.policies)
            if clips is not None:
                # `clip_pre_roll_s` · `clip_post_roll_s` 도 DB 값이다(절대규칙 6).
                # 상태머신이 방금 읽은 것을 그대로 나눠 쓴다 — 두 번 읽으면 같은 순간에
                # 서로 다른 사전/사후 구간으로 클립을 뽑는 창이 생긴다.
                clips.set_policies(service.machine.policies)
        if since_sound >= SOUND_REFRESH_SECONDS:
            # 설정 화면(FN-CFG-03 · M6)에서 음원을 바꾸면 이만큼 안에 반영된다.
            # 경고 경로에서 DB 를 읽지 않기 위한 주기 갱신이다 — 1초 예산 안에
            # DB 왕복을 넣지 않는다.
            since_sound = 0.0
            await alerts.refresh_sounds()
            # 음원과 함께 **등급**도 바뀔 수 있다(§6 `alert_sounds.level`). 매핑만
            # 갱신하고 등급을 두면 화면에서 바꾼 위험 등급이 반영되지 않는다.
            service.machine.set_severity(alerts.severity_map())


async def _watch_storage(
    client: StorageReader,
    hub: DashboardHub,
    clock: Clock,
    clips: ClipService | None = None,
) -> None:
    """REC 생존 확인. 상태가 **변할 때만** `system` 을 발행한다(§5.3).

    REC 이 죽으면 7일 녹화가 멈춘다 — 이벤트가 나도 클립을 뽑을 원본이 없다.
    `GET /system/status` 의 `storage` 가 `null` 이 되는 것과 짝을 이루는 통지다.

    **세그먼트 길이도 여기서 흘려보낸다.** 같은 응답 안에 있으므로(§4.7 `recording`)
    요청을 한 번 더 보낼 이유가 없고, 클립 예약 실행 시각은 그 값 없이 계산할 수 없다
    (기능명세서 §4.4).
    """
    state: ComponentState | None = None
    while True:
        try:
            status = await client.status()
            if clips is not None:
                clips.set_segment_seconds(float(status.recording.segment_seconds))
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


_configure_logging()
app = create_app()
