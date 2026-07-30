"""이벤트 클립·키프레임 예약 추출. FN-REC-03 (기능명세서 §4.4 · API명세서 §4.7)

```
confirmed_at                 키프레임 즉시 추출 (REC 스냅샷 버퍼에서 나온다)
                             clip_status = pending  · 예약 등록
+ clip_post_roll_s           사후 구간이 스트림에는 흘렀으나 그 구간을 담은
                             세그먼트 파일은 아직 열려 있다
+ rec_segment_seconds        해당 세그먼트가 닫힌다  ← REC 의 GET /status 가 보고
+ clip_extract_margin_s      예약 실행 → POST /clips → 서버 저장소에 영구 보관
                             clip_status = ready · §5.2 event_updated 로 clip_url 발행
```

**확정 즉시 추출하지 않는다.** 그 순간에는 사후 구간이 아직 녹화되지 않아 앞부분만
담긴 클립이 나오고, 그 실패는 되돌릴 수 없다 — 시간이 지난 뒤 다시 뽑으려 해도 이미
`ready` 로 기록되어 아무도 다시 부르지 않는다.

**세그먼트 길이를 반드시 더한다.** REC 은 벽시계 격자로 세그먼트를 닫으므로
(`-segment_atclocktime`), `confirmed_at + post_roll` 시점을 담은 파일은 그때 아직
기록 중이다. 이 항을 빼면 뒤쪽 구간이 잘려 `partial` 이 된다 — 실측으로 세그먼트 10초
환경에서 margin 2초만 두었을 때 뒤 2.9초가 비었다. 그리고 그 길이는 **서버가 상수로
들고 있지 않는다.** REC 설정을 바꿨을 때 서버가 모른 채 잘못된 시각에 추출하기 때문이다.

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
    ) -> None:
        self._rec = rec
        self._store = store
        self._clock = clock
        self._media_root = media_root
        self._policies = policies or Policies()
        self._publish = publish
        self._segment_s: float | None = None
        """REC 이 보고한 세그먼트 길이(초). **서버가 정하지 않는다**(기능명세서 §4.4).

        아직 한 번도 못 들었으면 `None` 이고, 그동안 예약은 실행하지 않는다 — 모르는
        값을 그럴듯한 기본값(10초)으로 메우면 REC 설정이 다를 때 조용히 뒤가 잘린
        클립이 `ready` 로 기록된다."""
        self._tasks: set[asyncio.Task[None]] = set()
        """뒤로 넘긴 키프레임 추출들. 참조를 놓으면 GC 가 중간에 회수한다."""

    def set_policies(self, policies: Policies) -> None:
        """`clip_pre_roll_s` · `clip_post_roll_s` · `clip_extract_margin_s` 는 DB 에서 온다.

        CLAUDE.md 절대규칙 6. 여유(margin)도 §4.5 정책 키가 되면서 서버 설정에서
        떨어져 나왔다 — 세 값이 한 곳에서 오지 않으면 사전·사후 구간과 여유가 서로 다른
        시점의 값으로 섞여 계산된다.
        """
        self._policies = policies

    def set_segment_seconds(self, seconds: float) -> None:
        """REC 의 `GET /status`(§4.7 `recording.segment_seconds`)가 보고한 값.

        상태 폴링이 이미 10초마다 REC 을 부르므로 그 응답을 여기로 흘려보낸다 —
        같은 값을 얻자고 요청을 한 번 더 보내지 않는다.
        """
        if seconds <= 0:
            log.warning("REC 이 보고한 세그먼트 길이가 %.1f초다 — 무시한다", seconds)
            return
        if self._segment_s != seconds:
            log.info(
                "세그먼트 길이 %.1f초 — 클립 예약 실행은 확정 %.1f초 뒤다",
                seconds,
                self._delay(seconds),
            )
        self._segment_s = seconds

    @property
    def segment_seconds(self) -> float | None:
        return self._segment_s

    @property
    def delay_s(self) -> float | None:
        """확정 → 예약 실행까지의 대기.

        `clip_post_roll_s + rec_segment_seconds + clip_extract_margin_s`(기능명세서 §4.4).
        세그먼트 길이를 아직 못 들었으면 `None` 이다.
        """
        return None if self._segment_s is None else self._delay(self._segment_s)

    def _delay(self, segment_s: float) -> float:
        post_roll = self._policies.clip_post_roll_s
        return post_roll + segment_s + self._policies.clip_extract_margin_s

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

        **키프레임은 기다리지 않는다.** REC 의 `GET /keyframe` 은 ffmpeg 자식 프로세스
        하나를 띄우는 작업이라 실측 **한 장에 약 390ms**다(M5 에서 불필요한 ffprobe 를
        없애 약 590ms 에서 내렸다. 그중 190ms 가 프로세스 기동이라 더 줄일 여지가 없다).
        확정 시 두 장을 뽑으므로 약 0.8초이고, 그동안 이 코루틴을 잡고 있으면 같은
        루프에서 도는 `/ws/edge` 수신이 그만큼 멈춘다 — 8fps 기준 6프레임이 밀리고,
        **밀린 만큼 다른 이벤트의 타이머가 늦게 흐른다.**

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
        segment = "?" if self._segment_s is None else f"{self._segment_s:.0f}"
        delay = self.delay_s
        log.info(
            "클립 예약 — %s (%s초 뒤 실행: 사후 %.0fs + 세그먼트 %ss + 여유 %.0fs)",
            event_id,
            "?" if delay is None else f"{delay:.0f}",
            self._policies.clip_post_roll_s,
            segment,
            self._policies.clip_extract_margin_s,
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
        delay = self.delay_s if self.delay_s is not None else await self._ask_segment_seconds()
        if delay is None:
            # 세그먼트 길이를 모르면 **실행하지 않는다.** 예약은 DB 에 남아 있으므로
            # REC 이 살아나는 순간 다음 주기에 집힌다. 기본값으로 추측해 뽑으면 뒤가
            # 잘린 클립이 `ready` 로 굳어 되돌릴 수 없다.
            return []
        try:
            due = await self._store.find_due_clip_jobs(at, delay)
        except Exception:
            log.exception("클립 예약 목록을 읽지 못했다 — 다음 주기에 다시 시도한다")
            return []
        done: list[str] = []
        for event_id in due:
            if await self._extract(event_id):
                done.append(event_id)
        return done

    async def _ask_segment_seconds(self) -> float | None:
        """상태 폴링이 아직 값을 주지 않았으면 직접 묻는다(§4.7 `GET /status`).

        기동 직후 첫 이벤트가 이 경로를 탄다. REC 에 닿지 못하면 `None` 을 돌려주고
        예약은 그대로 남는다 — REC 이 없으면 어차피 추출도 못 한다.
        """
        try:
            status = await self._rec.status()
        except RecUnavailableError as exc:
            log.warning("세그먼트 길이를 아직 모른다 — 클립 예약을 미룬다: %s", exc)
            return None
        self.set_segment_seconds(float(status.recording.segment_seconds))
        return self.delay_s

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

        **`events.clip_error` 에 적는다**(§6). `note` 에 `[클립]` 접두사로 끼워 넣던
        임시 처리를 없앴다 — 관리자 메모와 기계가 남긴 사유가 한 칸을 쓰면 사람이 쓴
        문장이 덮이거나 사유가 메모처럼 읽힌다.
        """
        reason = response.reason or f"REC 이 {response.status} 를 돌려주었다(사유 없음)"
        detail = f"{response.status}: {reason}"
        await self._store.update(event.event_id, {"clip_status": "failed", "clip_error": detail})
        await self._emit(
            EventUpdatedMsg(
                event_id=event.event_id,
                status=event.status,
                clip_status="failed",
            )
        )
        log.warning("클립 추출 실패 — %s: %s (%s)", event.event_id, response.status, reason)

    async def _emit(self, message: SpecModel) -> None:
        if self._publish is None:
            return
        await self._publish(message)


def _stamp(at: datetime | None) -> str:
    return "?" if at is None else at.isoformat()
