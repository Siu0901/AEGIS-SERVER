"""보존 정책 — 7일 링버퍼와 용량 관리 (FN-REC-02 · FN-REC-05).

두 가지 이유로 지운다.

1. **나이** — `REC_RETENTION_DAYS` 를 넘긴 세그먼트
2. **용량** — 총합이 `REC_MAX_DISK_GB` 를 넘으면, 보존 기간 이내라도 오래된 것부터

둘 다 **오래된 것부터** 지운다. 링버퍼이므로 최신 영상이 늘 남아야 한다.

지울 대상을 고르는 계산(`plan_deletions`)과 실제 삭제(`enforce`)를 나눠 둔다.
파일을 지우는 코드는 테스트가 실수를 눈감아 주면 안 되는 자리라, 판단 부분만 따로
검증할 수 있게 만든다.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from recorder.segments import Segment, scan_segments

__all__ = ["RetentionPlan", "enforce", "plan_deletions"]

log = logging.getLogger("recorder.retention")


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    """무엇을 왜 지울지."""

    expired: list[Segment] = field(default_factory=list)
    """보존 기간을 넘긴 것."""
    over_quota: list[Segment] = field(default_factory=list)
    """용량 상한을 넘겨 밀려난 것."""

    @property
    def doomed(self) -> list[Segment]:
        return [*self.expired, *self.over_quota]


def plan_deletions(
    segments: list[Segment],
    *,
    now: datetime,
    retention_seconds: float,
    max_bytes: int,
    keep_newest: int = 1,
) -> RetentionPlan:
    """지울 세그먼트를 고른다. 파일은 건드리지 않는다.

    `segments` 는 전 카메라를 합쳐 **시작 시각 오름차순**으로 들어와야 한다.
    용량은 카메라별이 아니라 디스크 전체에 걸리는 제약이므로 합쳐서 본다.

    `keep_newest` — 카메라별로 최신 몇 개는 나이·용량과 무관하게 남긴다. 기록 중인
    세그먼트를 지우면 ffmpeg 이 쓰고 있는 파일이 사라져 그 카메라의 녹화가 깨진다.
    """
    protected = _newest_per_cam(segments, keep_newest)

    cutoff = now - timedelta(seconds=retention_seconds)
    expired: list[Segment] = []
    survivors: list[Segment] = []
    for segment in segments:
        if segment.path in protected:
            survivors.append(segment)
        elif segment.start_at < cutoff:
            expired.append(segment)
        else:
            survivors.append(segment)

    # 살아남은 것만으로도 상한을 넘으면 오래된 쪽부터 더 밀어낸다.
    total = sum(item.size_bytes for item in survivors)
    over_quota: list[Segment] = []
    for segment in survivors:
        if total <= max_bytes:
            break
        if segment.path in protected:
            continue
        over_quota.append(segment)
        total -= segment.size_bytes

    return RetentionPlan(expired=expired, over_quota=over_quota)


def _newest_per_cam(segments: list[Segment], keep_newest: int) -> set[Path]:
    """카메라별 최신 `keep_newest` 개의 경로."""
    if keep_newest <= 0:
        return set()
    by_cam: dict[int, list[Segment]] = {}
    for segment in segments:
        by_cam.setdefault(segment.cam_id, []).append(segment)
    protected: set[Path] = set()
    for items in by_cam.values():
        for segment in sorted(items, key=lambda item: item.start_at)[-keep_newest:]:
            protected.add(segment.path)
    return protected


def enforce(
    root: Path,
    cam_ids: list[int],
    *,
    now: datetime,
    retention_seconds: float,
    max_bytes: int,
) -> RetentionPlan:
    """정책을 적용하고 실제로 지운다. 지운 목록을 돌려준다."""
    segments: list[Segment] = []
    for cam_id in cam_ids:
        segments.extend(scan_segments(root, cam_id))
    segments.sort(key=lambda item: item.start_at)

    plan = plan_deletions(
        segments,
        now=now,
        retention_seconds=retention_seconds,
        max_bytes=max_bytes,
    )
    for segment in plan.doomed:
        try:
            segment.path.unlink()
        except OSError as exc:
            # 지우지 못한 것을 지웠다고 하지 않는다. 다음 스윕에서 다시 시도한다.
            log.warning("세그먼트 삭제 실패 %s — %s", segment.path, exc)

    if plan.expired:
        log.info("보존 기간 초과 %d개 삭제", len(plan.expired))
    if plan.over_quota:
        log.info("용량 상한 초과 %d개 삭제", len(plan.over_quota))

    _prune_empty_dirs(root, cam_ids, now=now)
    return plan


def _prune_empty_dirs(root: Path, cam_ids: list[int], *, now: datetime) -> None:
    """세그먼트가 전부 빠진 **지난** 날짜 디렉토리를 치운다.

    비워두면 7일이 지날수록 빈 디렉토리가 쌓여 인덱스 스캔이 느려진다.
    카메라 디렉토리 자체는 남긴다 — 녹화가 언제든 다시 시작될 자리다.

    **오늘과 그 이후 디렉토리는 비어 있어도 건드리지 않는다.**
    ffmpeg 의 `segment` muxer 에는 디렉토리 생성 기능이 없어서 `capture.py` 가 미리
    만들어 두는데, 기동 직후에는 아직 파일이 하나도 없다. 그때 스윕이 "빈 디렉토리"로
    보고 지우면 ffmpeg 이 `Failed to open segment` 로 즉사한다. 실제로 REC 을 새로
    띄울 때마다 첫 시도가 실패하고 재시도로 넘어가고 있었다.
    """
    today = now.astimezone(UTC).strftime("%Y-%m-%d")
    for cam_id in cam_ids:
        cam_path = root / str(cam_id)
        if not cam_path.is_dir():
            continue
        for day in cam_path.iterdir():
            if not day.is_dir() or day.name >= today:
                continue
            if any(day.iterdir()):
                continue
            # 실패해도 기능에는 영향이 없다. 다음 스윕에서 다시 본다.
            with contextlib.suppress(OSError):
                day.rmdir()
