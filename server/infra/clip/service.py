"""이벤트 클립·키프레임 예약 추출. FN-REC-03 (기능명세서 §4.4 · API명세서 §4.7)

```
confirmed_at              키프레임 즉시 추출 (링버퍼에 이미 있다)
                          clip_status = pending  · 예약 등록
confirmed_at + post_roll  사후 세그먼트 기록 완료
        + margin          예약 실행 → POST /clips → 서버 저장소에 영구 보관
                          clip_status = ready · §5.2 event_updated 로 clip_url 발행
```

**확정 즉시 추출하지 않는다.** 그 순간에는 사후 구간이 아직 녹화되지 않아 앞부분만
담긴 클립이 나오고, 그 실패는 되돌릴 수 없다 — 시간이 지난 뒤 다시 뽑으려 해도 이미
`ready` 로 기록되어 아무도 다시 부르지 않는다. `margin` 은 세그먼트 파일이 닫히기 전에
잘라내 파일 끝이 손상되는 것을 막는다(§4.4).

**큐를 메모리에 두지 않는다.** 예약의 유일한 표현은 DB 의 `clip_status = pending` 이고,
실행 시각은 `confirmed_at + post_roll + margin` 으로 계산된다. 그래서 **서버가 죽어도
예약이 남고, 재시작 뒤 첫 조회가 곧 복구다.** 메모리 타이머를 썼다면 재시작 순간
진행 중이던 이벤트의 클립이 영원히 `pending` 으로 남는다.

**REC 파일에 경로로 접근하지 않는다**(기능명세서 §4.4). 받은 바이트를 서버 저장소
(`media/`)에 옮겨 적는다 — 운용 시 원본은 엣지 SSD 에 있고 7일 뒤 사라진다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from aegis_contracts import (
    ClipRequest,
    ClipResponse,
    EventDetail,
    EventUpdatedMsg,
    Policies,
    SpecModel,
)
from aegis_vision.clock import Clock
from server.infra.rec_client import ClipExtractor, RecUnavailableError

__all__ = [
    "CLIP_POLL_SECONDS",
    "DEFAULT_MARGIN_S",
    "KEYFRAME_COUNT",
    "ClipService",
    "ClipStore",
]

log = logging.getLogger("server.clips")

#: 예약 큐(= DB)를 훑는 주기(초). 실행 시각이 지난 잡을 이 간격 안에 집어 든다.
#:
#: `margin` 이 2초이므로 그보다 촘촘히 돌 이유가 없다. 클립이 몇 초 늦게 준비되는 것은
#: 문제가 아니다 — 대시보드는 그동안 키프레임을 보여준다(§4.2).
CLIP_POLL_SECONDS = 2.0

#: 사후 구간 뒤에 더 기다리는 여유(초). 기능명세서 §4.4 「추출 타이밍」이 정한 값이다.
#:
#: 세그먼트가 10초 단위로 닫히므로, 사후 구간이 끝나는 순간에는 마지막 세그먼트가 아직
#: 열려 있을 수 있다. 그 파일을 잘라내면 끝이 손상된다.
DEFAULT_MARGIN_S = 2.0

#: 확정 시 뽑는 키프레임 수. 기능명세서 §4.4 「고화질 키프레임 2~3장」.
KEYFRAME_COUNT = 2


class ClipStore(Protocol):
    """클립 예약이 요구하는 저장소. 구현은 `server/infra/db/repository.py`."""

    async def get(self, event_id: str) -> EventDetail | None: ...

    async def update(self, event_id: str, changes: Mapping[str, Any]) -> None: ...

    async def find_due_clip_jobs(self, now: datetime, delay_s: float) -> list[str]: ...


class Broadcaster(Protocol):
    """§5.2 `event_updated` 를 대시보드로 미는 통로(`DashboardHub.broadcast`)."""

    async def __call__(self, message: SpecModel) -> None: ...


class ClipService:
    """확정 시 키프레임을 뽑고, 클립 추출을 예약하고, 때가 되면 실행한다."""

    def __init__(
        self,
        *,
        rec: ClipExtractor,
        store: ClipStore,
        clock: Clock,
        media_root: Path,
        policies: Policies | None = None,
        publish: Broadcaster | None = None,
        margin_s: float = DEFAULT_MARGIN_S,
    ) -> None:
        self._rec = rec
        self._store = store
        self._clock = clock
        self._media_root = media_root
        self._policies = policies or Policies()
        self._publish = publish
        self._margin_s = margin_s
        self._tasks: set[asyncio.Task[None]] = set()
        """뒤로 넘긴 키프레임 추출들. 참조를 놓으면 GC 가 중간에 회수한다."""

    def set_policies(self, policies: Policies) -> None:
        """`clip_pre_roll_s` · `clip_post_roll_s` 는 DB 에서 온다(절대규칙 6)."""
        self._policies = policies

    @property
    def delay_s(self) -> float:
        """확정 → 예약 실행까지의 대기. `clip_post_roll_s + margin`."""
        return self._policies.clip_post_roll_s + self._margin_s

    @property
    def clips_dir(self) -> Path:
        return self._media_root / "clips"

    @property
    def keyframes_dir(self) -> Path:
        return self._media_root / "keyframes"

    # -- 확정 시 (FN-EVT-02 연계) ------------------------------------------

    async def on_confirmed(self, event_id: str, cam_id: int, confirmed_at: datetime) -> None:
        """확정됐다. 클립 추출을 예약하고 키프레임 추출을 **뒤로 넘긴다.**

        예약(`clip_status = pending`)만 기다린다 — DB 쓰기 한 번이라 짧고, 그것이
        끝나야 예약이 재시작을 견딘다.

        **키프레임은 기다리지 않는다.** REC 의 `GET /keyframe` 은 ffmpeg 이 세그먼트를
        열고 되감아 디코딩하는 작업이라 실측 **한 장에 약 5초**가 걸렸다(2026-07-30,
        카메라·REC 이 같은 기계에서 도는 상태). 그동안 이 코루틴을 잡고 있으면 같은
        루프에서 도는 `/ws/edge` 수신이 통째로 멈춘다 — 확정 한 건이 그 뒤 10초치
        프레임을 밀어내고, **밀린 만큼 다른 이벤트의 타이머가 늦게 흐른다.**

        경고(FN-ALM-01)는 이 호출보다 먼저 나가므로 1초 예산과는 무관하다. 여기서
        막히는 것은 그다음 관측들이다.

        두 작업의 실패가 서로를 막지 않는다. 키프레임을 못 받아도 클립 예약은 걸리고,
        그 반대도 마찬가지다 — 하나가 없다고 다른 증거까지 버릴 이유가 없다.
        """
        await self._schedule(event_id)
        self._spawn(self._grab_keyframes(event_id, cam_id, confirmed_at), f"keyframe:{event_id}")

    def _spawn(self, work: Coroutine[Any, Any, None], name: str) -> None:
        """뒤로 넘긴 작업 하나. **참조를 들고 있어야 GC 가 중간에 회수하지 않는다.**"""
        task = asyncio.create_task(work, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        if (error := task.exception()) is not None:
            # 뒤로 넘긴 작업의 예외는 아무도 보지 않으면 그대로 사라진다(절대규칙 9).
            log.error("%s 가 실패했다: %s: %s", task.get_name(), type(error).__name__, error)

    async def wait_idle(self) -> None:
        """뒤로 넘긴 작업들이 끝날 때까지 기다린다.

        테스트·시나리오가 "키프레임이 저장됐는가"를 볼 때, 그리고 서버가 내려갈 때
        쓴다. 평상시 경로에서는 부르지 않는다 — 부르면 다시 막히는 셈이 된다.
        """
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def _schedule(self, event_id: str) -> None:
        try:
            await self._store.update(event_id, {"clip_status": "pending"})
        except Exception:
            log.exception("클립 예약을 기록하지 못했다 — %s 의 클립이 뽑히지 않는다", event_id)
            return
        log.info(
            "클립 예약 — %s (%.0f초 뒤 실행: 사후 %.0fs + 여유 %.0fs)",
            event_id,
            self.delay_s,
            self._policies.clip_post_roll_s,
            self._margin_s,
        )

    async def _grab_keyframes(self, event_id: str, cam_id: int, confirmed_at: datetime) -> None:
        """확정 시각 주변 프레임 몇 장. 클립이 준비되기 전까지 화면이 보여줄 그림이다.

        시각을 **과거 쪽으로만** 잡는다(확정 시각과 그 1초 전). 미래 프레임은 아직
        녹화되지 않았고, 없는 시각을 요청하면 REC 이 `not_found` 를 낸다.
        """
        self.keyframes_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for index in range(KEYFRAME_COUNT):
            at = confirmed_at - timedelta(seconds=index)
            try:
                payload = await self._rec.keyframe(cam_id, at)
            except RecUnavailableError as exc:
                # 조용히 넘기지 않는다. 키프레임이 없으면 §5.2 `keyframe_url` 이 `null` 로
                # 나가고(그 자체는 계약에 맞다), 화면은 클립이 준비될 때까지 빈칸이 된다.
                log.warning("키프레임을 받지 못했다 — %s (%s): %s", event_id, at.isoformat(), exc)
                continue
            path = self.keyframes_dir / f"{event_id}_{index}.jpg"
            await asyncio.to_thread(path.write_bytes, payload)
            saved.append(str(path))
        if not saved:
            return
        try:
            await self._store.update(event_id, {"keyframe_paths": saved})
        except Exception:
            log.exception("키프레임 경로를 기록하지 못했다 — %s", event_id)
            return
        log.info("키프레임 %d장 저장 — %s", len(saved), event_id)

    # -- 예약 실행 --------------------------------------------------------

    async def run_due(self, now: datetime | None = None) -> list[str]:
        """실행 시각이 지난 예약을 전부 처리하고 처리한 이벤트 ID 를 돌려준다.

        **재시작 복구가 따로 없다.** 예약은 DB 에만 있으므로 이 조회가 곧 복구다 —
        서버가 죽어 있는 동안 실행 시각이 지난 잡도 여기서 함께 집힌다.
        """
        at = now if now is not None else self._clock.now()
        try:
            due = await self._store.find_due_clip_jobs(at, self.delay_s)
        except Exception:
            log.exception("클립 예약 목록을 읽지 못했다 — 다음 주기에 다시 시도한다")
            return []
        done: list[str] = []
        for event_id in due:
            if await self._extract(event_id):
                done.append(event_id)
        return done

    async def _extract(self, event_id: str) -> bool:
        event = await self._store.get(event_id)
        if event is None or event.confirmed_at is None:
            log.warning("클립 예약이 가리키는 이벤트가 없다: %s", event_id)
            return False

        request = ClipRequest.model_validate(
            {
                "cam_id": event.cam_id,
                "from": event.confirmed_at - timedelta(seconds=self._policies.clip_pre_roll_s),
                "to": event.confirmed_at + timedelta(seconds=self._policies.clip_post_roll_s),
                "event_id": event_id,
            }
        )
        try:
            response = await self._rec.create_clip(request)
        except RecUnavailableError as exc:
            # REC 에 닿지 못한 것은 **잡의 실패가 아니다.** `pending` 으로 두어 다음
            # 주기에 다시 시도한다 — `failed` 로 굳히면 REC 이 살아나도 아무도 다시
            # 부르지 않고, 그 이벤트는 영원히 증거 없이 남는다.
            log.warning("클립 추출을 나중에 다시 시도한다 — %s: %s", event_id, exc)
            return False

        if response.status != "ready" or not response.download_url:
            await self._fail(event, response)
            return True

        try:
            payload = await self._rec.download(response.download_url)
        except RecUnavailableError as exc:
            log.warning("클립 파일을 나중에 다시 받는다 — %s: %s", event_id, exc)
            return False

        self.clips_dir.mkdir(parents=True, exist_ok=True)
        path = self.clips_dir / f"{event_id}.mp4"
        await asyncio.to_thread(path.write_bytes, payload)
        await self._store.update(event_id, {"clip_status": "ready", "clip_path": str(path)})
        await self._emit(
            EventUpdatedMsg(
                event_id=event_id,
                status=event.status,
                clip_status="ready",
                clip_url=f"/media/clips/{path.name}",
            )
        )
        log.info(
            "클립 준비 — %s (%.1fKB, 실제 구간 %s ~ %s)",
            event_id,
            len(payload) / 1024,
            _stamp(response.actual_from),
            _stamp(response.actual_to),
        )
        return True

    async def _fail(self, event: EventDetail, response: ClipResponse) -> None:
        """`partial` · `not_found` — REC 은 정상 동작했고 원본이 없거나 모자랐다(§4.7).

        `reason` 을 반드시 남긴다. `status` 만으로는 "보존 기간이 지났다"와 "그 시각에
        녹화가 없었다"가 구분되지 않는데 대응이 다르다.

        ⚠ §6 `events` 에 사유를 담을 컬럼이 없어 `note` 에 `[클립]` 접두사로 적는다.
        관리자 메모와 한 칸을 쓰는 셈이라 `docs/INDEX.md` 「명세서 확인 필요」에
        올려 두었다. 기존 메모는 지우지 않고 앞에 덧붙인다.
        """
        reason = response.reason or f"REC 이 {response.status} 를 돌려주었다(사유 없음)"
        marker = f"[클립] {response.status}: {reason}"
        note = marker if not event.note else f"{marker}\n{event.note}"
        await self._store.update(event.event_id, {"clip_status": "failed", "note": note})
        await self._emit(
            EventUpdatedMsg(
                event_id=event.event_id,
                status=event.status,
                clip_status="failed",
                note=note,
            )
        )
        log.warning("클립 추출 실패 — %s: %s (%s)", event.event_id, response.status, reason)

    async def _emit(self, message: SpecModel) -> None:
        if self._publish is None:
            return
        await self._publish(message)


def _stamp(at: datetime | None) -> str:
    return "?" if at is None else at.isoformat()
