"""REC HTTP API (API명세서 §4.7).

    uv run tasks.py rec
    uv run uvicorn recorder.main:app --host 127.0.0.1 --port 9100

**서버는 이 API 로만 녹화에 접근한다.** 같은 기계에서 돌더라도 파일 경로로 읽지
않는다 — 운용 시 이 프로세스는 엣지 SSD 위에 있고, 그때 고쳐야 하는 값은
`RECORDER_BASE` 하나뿐이어야 한다(기능명세서 §4.4).

세 개의 엔드포인트만 있다.

    POST /clips     구간 추출 (여러 세그먼트를 이어붙여 잘라낸다)
    GET  /keyframe  단일 프레임 JPEG (사후 구간을 기다리지 않는다)
    GET  /status    카메라별 녹화 상태 + storage 절
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import AwareDatetime

from aegis_contracts import ClipRequest, ClipResponse, ErrorBody, ErrorResponse, RecStatusResponse
from aegis_vision.clock import RealClock
from recorder import clips
from recorder.config import get_rec_settings
from recorder.ffmpeg import FfmpegError
from recorder.service import RecorderService

__all__ = ["app", "create_app"]

log = logging.getLogger("recorder")


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    """API명세서 §1.4 오류 봉투. REC 도 같은 형식을 쓴다."""
    body = ErrorResponse(error=ErrorBody(code=code, message=message))  # type: ignore[arg-type]
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def create_app() -> FastAPI:
    settings = get_rec_settings()
    service = RecorderService(settings, RealClock())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    application = FastAPI(
        title="AEGIS REC",
        version="0.1.0",
        summary="녹화 컴포넌트 — 메인 스트림 세그먼트 녹화와 구간 추출 (API명세서 §4.7)",
        lifespan=lifespan,
    )
    application.state.service = service

    @application.exception_handler(clips.ClipError)
    async def _clip_error(_: Request, exc: clips.ClipError) -> JSONResponse:
        return _error(400, "VALIDATION_ERROR", str(exc))

    @application.exception_handler(FfmpegError)
    async def _ffmpeg_error(_: Request, exc: FfmpegError) -> JSONResponse:
        # 조용히 200 을 돌려주지 않는다. 클립이 없는데 있다고 하면 서버는 그 이벤트에
        # 증거가 있다고 믿고 clip_status 를 ready 로 넘긴다.
        log.error("ffmpeg 실패: %s", exc)
        return _error(500, "VALIDATION_ERROR", f"녹화 처리 실패: {exc}")

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/status", response_model=RecStatusResponse)
    async def status() -> RecStatusResponse:
        """카메라별 녹화 상태와 저장소. 서버가 §4.6 `storage` 에 실어 나른다."""
        return await service.status()

    @application.post("/clips", response_model=ClipResponse)
    async def create_clip(request: ClipRequest) -> ClipResponse:
        """구간 추출.

        요청 구간에 걸치는 세그먼트가 여러 개면 이어붙여 잘라낸다. 세그먼트 경계와
        키프레임 때문에 결과는 요청과 다를 수 있고, 그 실제 구간을
        `actual_from` / `actual_to` 로 정확히 돌려준다.
        """
        return await clips.extract_clip(
            settings,
            cam_id=request.cam_id,
            start=request.from_.astimezone(UTC),
            end=request.to.astimezone(UTC),
            event_id=request.event_id,
        )

    @application.get("/clips/{filename}")
    def download_clip(filename: str) -> FileResponse:
        """`download_url` 이 가리키는 곳. 서버가 받아 자기 저장소에 영구 보관한다."""
        stem = filename[:-4] if filename.endswith(".mp4") else filename
        path = clips.clip_path(settings, stem)
        if not path.is_file():
            msg = f"클립이 없다: {filename}"
            raise clips.ClipError(msg)
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    @application.get(
        "/keyframe",
        responses={200: {"content": {"image/jpeg": {}}, "description": "JPEG 한 장"}},
    )
    async def keyframe(
        cam_id: Annotated[int, Query(ge=1)],
        at: Annotated[AwareDatetime, Query()],
    ) -> Response:
        """단일 프레임 JPEG. 이벤트 확정 시 즉시 호출되므로 지연 없이 응답한다.

        **버퍼 안이면 메모리에서, 밖이면 세그먼트에서**(기능명세서 §4.4). 확정 시점의
        프레임은 아직 어떤 파일에도 없으므로 세그먼트만으로는 답할 수 없다 — 그 경로만
        있던 시절에는 확정 직후 요청이 500 으로 끝나 이벤트 상세 화면이 비어 있었다.
        """
        wanted = at.astimezone(UTC)
        buffer = service.snapshots(cam_id)
        if buffer is not None and (hit := buffer.nearest(wanted)) is not None:
            found_at, payload = hit
            log.debug(
                "cam%d %s 키프레임을 스냅샷 버퍼에서 냈다 (%+.2f초)",
                cam_id,
                wanted.isoformat(),
                (found_at - wanted).total_seconds(),
            )
            return Response(content=payload, media_type="image/jpeg")
        payload = await clips.extract_keyframe(settings, cam_id=cam_id, at=wanted)
        return Response(content=payload, media_type="image/jpeg")

    return application


app = create_app()


def run() -> None:
    """`uv run tasks.py rec` 진입점."""
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    settings = get_rec_settings()
    uvicorn.run(
        "recorder.main:app",
        host=settings.rec_bind_host,
        port=settings.rec_bind_port,
        log_level="info",
    )


if __name__ == "__main__":
    run()
