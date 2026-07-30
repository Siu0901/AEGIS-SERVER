"""REC 실행체 — 녹화 감독자들과 보존 스윕을 묶어 상태를 보고한다."""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime

from aegis_contracts import (
    RecCameraStatus,
    RecRecordingStatus,
    RecStatusResponse,
    RecStorageStatus,
)
from aegis_vision.clock import Clock
from recorder import retention
from recorder.capture import CameraRecorder
from recorder.config import RecSettings
from recorder.segments import Segment, scan_segments
from recorder.snapshots import SnapshotBuffer, SnapshotSampler

__all__ = ["RecorderService"]

log = logging.getLogger("recorder.service")

_GB = float(1024**3)


class RecorderService:
    """카메라별 녹화 프로세스와 보존 정책을 함께 돌린다."""

    def __init__(self, settings: RecSettings, clock: Clock) -> None:
        self._settings = settings
        self._clock = clock
        self._recorders = {
            cam_id: CameraRecorder(cam_id, settings, clock) for cam_id in settings.rec_cam_ids
        }
        self._samplers = {
            cam_id: SnapshotSampler(cam_id, settings, clock) for cam_id in settings.rec_cam_ids
        }
        """카메라별 스냅샷 버퍼(기능명세서 §4.4). 녹화와 **별도 프로세스**다 —
        리먹스 녹화는 디코딩하지 않으므로 같은 ffmpeg 에서 JPEG 을 뽑을 수 없다."""
        self._tasks: list[asyncio.Task[None]] = []
        self._snapshot: dict[int, list[Segment]] | None = None
        """스윕이 남겨두는 카메라별 세그먼트 목록. `GET /status` 가 이걸 읽는다."""

    @property
    def settings(self) -> RecSettings:
        return self._settings

    async def start(self) -> None:
        self._settings.rec_media_root.mkdir(parents=True, exist_ok=True)
        for cam_id, recorder in self._recorders.items():
            self._tasks.append(asyncio.create_task(recorder.run(), name=f"rec-cam{cam_id}"))
        for cam_id, sampler in self._samplers.items():
            self._tasks.append(asyncio.create_task(sampler.run(), name=f"rec-snap{cam_id}"))
        self._tasks.append(asyncio.create_task(self._sweep_loop(), name="rec-sweep"))
        log.info(
            "REC 기동 — cams=%s root=%s 보존 %.4g일 / 상한 %.1fGB",
            list(self._recorders),
            self._settings.rec_media_root,
            self._settings.rec_retention_days,
            self._settings.rec_max_disk_gb,
        )

    def snapshots(self, cam_id: int) -> SnapshotBuffer | None:
        """카메라의 스냅샷 버퍼. 등록되지 않은 카메라면 `None`."""
        sampler = self._samplers.get(cam_id)
        return None if sampler is None else sampler.buffer

    async def stop(self) -> None:
        for sampler in self._samplers.values():
            await sampler.stop()
        for recorder in self._recorders.values():
            await recorder.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # -- 보존 스윕 ---------------------------------------------------------

    async def _sweep_loop(self) -> None:
        """보존 정책을 주기적으로 적용한다.

        날짜 디렉토리 미리 만들기도 여기서 같이 한다. UTC 자정을 넘길 때 디렉토리가
        없으면 ffmpeg 이 즉사하는데, 그 사고가 하루에 한 번 정확히 자정에만 나면
        재현이 어렵다.
        """
        while True:
            try:
                for recorder in self._recorders.values():
                    recorder.ensure_day_dirs()
                # 디스크를 훑는 작업이라 스레드로 보낸다. 여기서 이벤트 루프를 막으면
                # 같은 루프에서 도는 녹화 감독 코루틴이 그동안 함께 멈춘다.
                await asyncio.to_thread(self._sweep_and_snapshot)
            except asyncio.CancelledError:
                raise
            except Exception:
                # 스윕이 한 번 실패했다고 루프를 죽이면 그 뒤로 디스크가 조용히 찬다.
                log.exception("보존 스윕 실패 — 다음 주기에 다시 시도한다")
            await asyncio.sleep(self._settings.rec_sweep_seconds)

    def _sweep_and_snapshot(self) -> retention.RetentionPlan:
        """보존 정책을 적용하고, 그 직후 상태를 스냅샷으로 남긴다.

        스윕은 어차피 디스크를 훑는다. 그때 만든 목록을 버리지 않고 `GET /status` 가
        쓰게 두면 상태 조회가 공짜가 된다.
        """
        plan = self.sweep()
        self._snapshot = self._scan()
        return plan

    def sweep(self) -> retention.RetentionPlan:
        """보존 정책 1회 적용. 테스트와 스윕 루프가 함께 쓴다."""
        return retention.enforce(
            self._settings.rec_media_root,
            list(self._recorders),
            now=self._clock.now(),
            retention_seconds=self._settings.retention_seconds,
            max_bytes=self._settings.max_disk_bytes,
        )

    # -- 상태 --------------------------------------------------------------

    async def status(self) -> RecStatusResponse:
        """`GET /status` (API명세서 §4.7).

        **요청마다 디스크를 훑지 않는다.** 스윕이 남겨둔 스냅샷을 쓴다.
        서버는 이 API 를 10초마다 부르고 대시보드를 열 때도 부르는데, 세그먼트가
        12만 개(7일 × 2채널)까지 쌓이면 매번 훑는 비용이 응답 시간을 넘어선다.
        실제로 여기서 ReadTimeout 이 나 대시보드의 저장소 칸이 비어 있었다.

        스냅샷이 아직 없으면(기동 직후) 그때만 한 번 만든다. 그 스캔도 별도 스레드로
        보낸다 — 이벤트 루프를 막으면 그 사이 녹화 감독 코루틴이 함께 멈춘다.
        """
        snapshot = self._snapshot
        if snapshot is None:
            snapshot = await asyncio.to_thread(self._scan)
            self._snapshot = snapshot
        return self._build_status(snapshot)

    def _scan(self) -> dict[int, list[Segment]]:
        """디스크를 훑어 카메라별 세그먼트 목록을 만든다. 블로킹."""
        return {
            cam_id: scan_segments(self._settings.rec_media_root, cam_id)
            for cam_id in self._recorders
        }

    def _build_status(self, per_cam: dict[int, list[Segment]]) -> RecStatusResponse:
        cameras: list[RecCameraStatus] = []
        for cam_id, recorder in self._recorders.items():
            last_at = _last_start(per_cam[cam_id])
            cameras.append(
                RecCameraStatus(
                    cam_id=cam_id,
                    recording=recorder.is_recording(last_at),
                    last_segment_at=last_at,
                )
            )

        all_segments = [item for items in per_cam.values() for item in items]
        used_bytes = sum(item.size_bytes for item in all_segments)
        oldest = min((item.start_at for item in all_segments), default=None)

        return RecStatusResponse(
            cameras=cameras,
            storage=self._storage(used_bytes, oldest),
            recording=self._recording(),
        )

    def _recording(self) -> RecRecordingStatus:
        """§4.7 `recording` — 서버가 클립 예약 시각을 계산하는 데 쓰는 값들.

        **서버에 같은 상수를 두지 않기 위해 보고한다**(기능명세서 §4.4). 세그먼트 길이를
        양쪽에 적어 두면 REC 설정을 바꿨을 때 서버가 모른 채 아직 열려 있는 파일을
        잘라내고, 그 클립은 뒤가 잘린 채 `partial` 로 남는다.
        """
        return RecRecordingStatus(
            segment_seconds=self._settings.rec_segment_seconds,
            snapshot_fps=self._settings.rec_snapshot_fps,
            snapshot_window_s=self._settings.rec_snapshot_window_s,
        )

    def _storage(self, used_bytes: int, oldest: datetime | None) -> RecStorageStatus:
        """§4.7 `storage`.

        **예산 기준으로 보고한다.** `total_gb` 는 물리 디스크 전체가 아니라 REC 이 실제로
        쓸 수 있는 상한(`REC_MAX_DISK_GB`)이고, 물리 여유가 그보다 적으면 그쪽으로 줄인다.
        물리 용량을 그대로 싣지 않는 이유는 개발 노트북(1TB)과 운용 젯슨(500GB 전용
        SSD)에서 같은 숫자가 전혀 다른 뜻이 되기 때문이다. 세 값은 항상
        `used + free == total` 을 만족한다.

        `used_gb` 는 **세그먼트 합계**다. 보존 정책이 관리하는 대상과 같은 집합이라야
        "상한을 넘었는데 왜 안 지우나" 같은 어긋남이 생기지 않는다.
        """
        try:
            physical_free = shutil.disk_usage(self._settings.rec_media_root).free
        except OSError:
            physical_free = 0
        budget = min(self._settings.max_disk_bytes, used_bytes + physical_free)
        return RecStorageStatus(
            total_gb=round(budget / _GB),
            used_gb=round(used_bytes / _GB),
            free_gb=round(max(budget - used_bytes, 0) / _GB),
            retention_days=round(self._settings.rec_retention_days),
            oldest_segment_at=oldest,
        )


def _last_start(segments: list[Segment]) -> datetime | None:
    return segments[-1].start_at if segments else None
