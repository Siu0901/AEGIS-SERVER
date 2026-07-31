"""스냅샷 버퍼 — 최근 구간의 **압축 비트스트림**을 그대로 들고 있는다. FN-REC-03 (기능명세서 §4.4)

**키프레임은 세그먼트 파일에서 뽑지 않는다.** 확정 시점의 프레임은 아직 어떤 파일에도
기록되지 않았고, 세그먼트에서 뽑으려면 최대 세그먼트 길이만큼 기다려야 한다. 그동안
이벤트 상세 화면(FN-UI-03)에 보여줄 그림이 없다.

**지속 디코딩을 하지 않는 것이 이 모듈의 핵심이다.** 초당 1장이라도 1080p 를 계속
디코딩하면 카메라 2대에 코어 약 66% 를 상시 점유한다(실측 — `docs/INDEX.md` M6 절).
젯슨에서는 추론이 이미 예산의 절반 이상을 쓰고 있어 이 부하를 얹을 수 없다.

| 항목 | 값 |
|---|---|
| 보관 대상 | 메인 스트림의 **H.264 바이트 그대로** (`-c:v copy`) |
| 보관 길이 | 최근 60초 (`rec_snapshot_window_s`) |
| 메모리 | 2.5 Mbps × 60초 ≈ 카메라당 19MB |
| 디코딩 시점 | `GET /keyframe` 요청이 올 때만, **해당 1프레임만** |

요청이 오면 목표 시각 **직전 IDR 부터 목표 액세스 유닛까지만** 잘라 디코더에 넣는다.
GOP 가 2초면 최악의 경우 2초 분량을 푸는데, 이벤트 확정 시에만 일어나는 일회성
작업이므로 지속 비용을 사건 시점의 일회성 비용으로 옮긴 것이다.

**키프레임 근사를 쓰지 않는다.** 「가장 가까운 IDR」을 돌려주면 GOP 간격만큼(2초)
어긋난 그림이 이벤트 증거로 남는다. 요청한 시각의 프레임을 그대로 낸다.

---

**액세스 유닛 경계는 어떻게 아는가.** Annex-B 는 시작코드(`00 00 01`)로 NAL 을 나눈다.
NAL 헤더 하위 5비트가 유형이고, VCL 슬라이스(1 = 비-IDR · 5 = IDR)의 첫 문법 요소인
`first_mb_in_slice` 가 0이면 새 픽처의 시작이다. `ue(v)` 로 부호화된 0 은 비트 `1`
하나이므로 **페이로드 첫 바이트의 최상위 비트만 보면 된다.** SPS·PPS·SEI·AUD 는 뒤따르는
픽처에 속하므로 다음 VCL 이 나타날 때까지 모아 둔다.

**표시 순서 주의.** 액세스 유닛의 도착 순서는 디코드 순서다. B프레임이 있으면 표시
순서가 뒤바뀌어 「마지막 출력 프레임 = 목표 프레임」이 성립하지 않는다. 그래서 슬라이스
타입을 훑어 B슬라이스를 만나면 **경고를 남긴다** — 조용히 어긋난 그림을 내보내지 않는다
(CLAUDE.md 절대규칙 9). 저지연 CCTV 와 이 레포의 가짜 카메라(`deploy/fake_cams.py` 의
`-bf 0`)는 B프레임을 쓰지 않는다.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from aegis_vision.clock import Clock
from recorder.config import RecSettings
from recorder.ffmpeg import require_ffmpeg, run_bytes

__all__ = [
    "AccessUnit",
    "BitstreamBuffer",
    "BitstreamSlice",
    "BitstreamTap",
    "decode_slice",
    "split_access_units",
]

log = logging.getLogger("recorder.snapshots")

#: 한 번에 읽는 크기.
_CHUNK = 65536

#: 스냅샷 프로세스 재시작 백오프.
_BACKOFF_START_S = 1.0
_BACKOFF_MAX_S = 30.0

#: 아직 도착하지 않은 프레임을 요청했을 때 허용하는 앞당김(초).
#:
#: 이벤트 확정 시각은 사실상 「지금」이고, 그 순간의 프레임은 RTSP 전송·버퍼링 때문에
#: 아직 도착하지 않았을 수 있다. 이만큼 미래까지는 **가장 최신 프레임**으로 답한다.
#: 그보다 먼 미래는 존재하지 않는 것이므로 `None` 이다 — 세그먼트에도 없다.
_LIVE_EDGE_TOLERANCE_S = 1.0

#: NAL 유형. ITU-T H.264 표 7-1.
_NAL_SLICE = 1
_NAL_IDR = 5
_NAL_SPS = 7
_NAL_PPS = 8

#: `slice_type % 5` 가 B 슬라이스를 뜻하는 값 (표 7-6 — 1 과 6).
_B_SLICE_TYPE = 1


@dataclass(frozen=True, slots=True)
class AccessUnit:
    """픽처 한 장에 해당하는 바이트 묶음."""

    at: datetime
    """도착 시각. ffmpeg 은 파이프에 촬영 시각을 실어주지 않으므로 `Clock` 으로 찍는다."""
    payload: bytes
    """시작코드를 포함한 Annex-B 바이트."""
    is_idr: bool
    """이 유닛부터 디코딩을 시작할 수 있는가(IDR 슬라이스를 담고 있는가)."""


@dataclass(frozen=True, slots=True)
class BitstreamSlice:
    """직전 IDR 부터 목표 유닛까지 잘라낸 조각. 이것만 디코더에 들어간다."""

    payload: bytes
    frames: int
    """조각에 담긴 액세스 유닛 수. 목표 프레임의 인덱스는 `frames - 1` 이다."""
    at: datetime
    """목표 유닛의 도착 시각. 요청 시각과의 차이가 곧 그림의 오차다."""


class BitstreamBuffer:
    """카메라 한 대의 최근 비트스트림. **순수 자료구조 — I/O 가 없다.**

    시각은 넣는 쪽이 `Clock` 에서 얻어 함께 넘긴다(CLAUDE.md 절대규칙 1).
    """

    def __init__(self, *, window_s: float) -> None:
        if window_s <= 0:
            msg = f"window_s 는 0보다 커야 한다: {window_s!r}"
            raise ValueError(msg)
        self._window_s = window_s
        self._units: deque[AccessUnit] = deque()
        self._nbytes = 0
        self._parameter_sets = b""
        """가장 최근에 본 SPS·PPS. IDR 앞에 함께 실리지 않는 스트림을 위해 들고 있는다."""

    @property
    def count(self) -> int:
        return len(self._units)

    @property
    def nbytes(self) -> int:
        """지금 들고 있는 바이트 수. `GET /status` 의 `recording.snapshot_bytes` 다."""
        return self._nbytes

    @property
    def oldest_at(self) -> datetime | None:
        return self._units[0].at if self._units else None

    @property
    def newest_at(self) -> datetime | None:
        return self._units[-1].at if self._units else None

    def add(self, unit: AccessUnit) -> None:
        """액세스 유닛 하나. 창을 넘어선 것은 그때 버린다."""
        self._units.append(unit)
        self._nbytes += len(unit.payload)
        found = _parameter_sets(unit.payload)
        if found:
            self._parameter_sets = found
        cutoff = unit.at - timedelta(seconds=self._window_s)
        while self._units and self._units[0].at < cutoff:
            self._nbytes -= len(self._units.popleft().payload)

    def slice_for(self, at: datetime) -> BitstreamSlice | None:
        """요청 시각의 프레임을 디코딩하기 위한 최소 조각.

        **없는 것을 있는 척하지 않는다.** 버퍼가 담고 있는 구간 밖이거나 그 시각 앞에
        IDR 이 없으면 `None` 을 내고, 부르는 쪽이 세그먼트에서 뽑는다. 가장 가까운 것을
        무조건 돌려주면 한참 전 사건의 그림으로 지금을 설명하게 된다.
        """
        target = self._index_at(at)
        if target is None:
            return None
        start = self._last_idr_before(target)
        if start is None:
            # 버퍼가 GOP 중간부터 시작했다 — 그 구간은 단독으로 디코딩할 수 없다.
            return None
        units = list(self._units)[start : target + 1]
        head = b"" if _parameter_sets(units[0].payload) else self._parameter_sets
        return BitstreamSlice(
            payload=head + b"".join(unit.payload for unit in units),
            frames=len(units),
            at=units[-1].at,
        )

    def _index_at(self, at: datetime) -> int | None:
        """요청 시각에 가장 가까운 유닛의 인덱스."""
        if not self._units:
            return None
        oldest = self._units[0].at
        newest = self._units[-1].at
        if at < oldest:
            return None
        if at > newest + timedelta(seconds=_LIVE_EDGE_TOLERANCE_S):
            return None
        return min(range(len(self._units)), key=lambda i: abs(self._units[i].at - at))

    def _last_idr_before(self, index: int) -> int | None:
        for i in range(index, -1, -1):
            if self._units[i].is_idr:
                return i
        return None


def split_access_units(data: bytes) -> tuple[list[tuple[bytes, bool]], bytes]:
    """Annex-B 바이트를 액세스 유닛으로 나눈다. 남는 꼬리를 함께 돌려준다.

    **완결된 유닛만 낸다.** 마지막 유닛은 다음 픽처의 첫 VCL 이 나타나야 끝났음을 알 수
    있으므로 꼬리로 남기고, 다음 청크와 이어 붙여 다시 부른다.

    돌려주는 각 원소는 `(바이트, IDR 인가)` 다.
    """
    starts = _nal_offsets(data)
    if not starts:
        return [], data

    units: list[tuple[bytes, bool]] = []
    begin = starts[0][0]
    has_idr = False
    seen_vcl = False
    boundary: int | None = None
    """VCL 뒤에 처음 나타난 비-VCL 의 위치. 다음 유닛은 거기서 시작한다 —
    SPS·PPS·SEI 는 **뒤따르는** 픽처에 속하므로 앞 유닛에 붙이면 IDR 조각이
    파라미터 세트를 잃는다."""
    for offset, header_at in starts:
        nal_type = data[header_at] & 0x1F
        if nal_type not in (_NAL_SLICE, _NAL_IDR):
            if seen_vcl and boundary is None:
                boundary = offset
            continue
        if seen_vcl and _starts_picture(data, header_at):
            cut = offset if boundary is None else boundary
            units.append((data[begin:cut], has_idr))
            begin = cut
            has_idr = False
            boundary = None
        seen_vcl = True
        if nal_type == _NAL_IDR:
            has_idr = True
    return units, data[begin:]


def _nal_offsets(data: bytes) -> list[tuple[int, int]]:
    """`(시작코드 시작 위치, NAL 헤더 바이트 위치)` 목록."""
    found: list[tuple[int, int]] = []
    index = data.find(b"\x00\x00\x01")
    while index >= 0:
        start = index - 1 if index > 0 and data[index - 1] == 0 else index
        header_at = index + 3
        if header_at < len(data):
            found.append((start, header_at))
        index = data.find(b"\x00\x00\x01", index + 3)
    return found


def _starts_picture(data: bytes, header_at: int) -> bool:
    """`first_mb_in_slice == 0` 인가 — 즉 새 픽처의 첫 슬라이스인가.

    `ue(v)` 로 부호화된 0 은 비트 `1` 하나다. 그래서 슬라이스 헤더 첫 바이트의 최상위
    비트만 보면 된다.
    """
    payload_at = header_at + 1
    return payload_at < len(data) and bool(data[payload_at] & 0x80)


def has_b_slice(payload: bytes) -> bool:
    """이 액세스 유닛이 B 슬라이스를 담고 있는가.

    담고 있으면 표시 순서가 디코드 순서와 달라 「마지막 출력 = 목표 프레임」이 깨진다.
    """
    for _, header_at in _nal_offsets(payload):
        if (payload[header_at] & 0x1F) != _NAL_SLICE:
            continue
        slice_type = _slice_type(payload, header_at)
        # 5~9 는 0~4 와 같은 뜻에 "픽처 안의 모든 슬라이스가 같은 타입"이 붙은 값이다.
        if slice_type is not None and slice_type % 5 == _B_SLICE_TYPE:
            return True
    return False


def _slice_type(payload: bytes, header_at: int) -> int | None:
    """슬라이스 헤더의 `slice_type`. `first_mb_in_slice` 다음의 `ue(v)` 다."""
    reader = _BitReader(payload[header_at + 1 : header_at + 9])
    try:
        reader.ue()  # first_mb_in_slice
        return reader.ue()
    except IndexError:
        return None


class _BitReader:
    """Exp-Golomb 를 읽는 최소한의 비트 리더. 슬라이스 헤더 앞부분에만 쓴다."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._bit = 0

    def _read_bit(self) -> int:
        index, offset = divmod(self._bit, 8)
        if index >= len(self._data):
            raise IndexError
        self._bit += 1
        return (self._data[index] >> (7 - offset)) & 1

    def ue(self) -> int:
        zeros = 0
        while self._read_bit() == 0:
            zeros += 1
            if zeros > 32:
                raise IndexError
        value = 1
        for _ in range(zeros):
            value = (value << 1) | self._read_bit()
        return value - 1


def _parameter_sets(payload: bytes) -> bytes:
    """유닛 안의 SPS·PPS 바이트. 없으면 빈 바이트."""
    offsets = _nal_offsets(payload)
    chunks: list[bytes] = []
    for index, (start, header_at) in enumerate(offsets):
        if (payload[header_at] & 0x1F) not in (_NAL_SPS, _NAL_PPS):
            continue
        end = offsets[index + 1][0] if index + 1 < len(offsets) else len(payload)
        chunks.append(payload[start:end])
    return b"".join(chunks)


async def decode_slice(slice_: BitstreamSlice, *, ffmpeg: str, timeout_s: float = 20.0) -> bytes:
    """조각을 디코딩해 **목표 프레임 한 장**을 JPEG 으로 낸다.

    `select` 로 목표 인덱스 하나만 통과시키고 `-frames:v 1` 로 끊는다. 디코더는 목표
    프레임까지만 풀고 인코딩도 한 장만 한다 — 조각 전체를 JPEG 으로 뽑아 마지막만
    쓰는 것보다 GOP 길이만큼 싸다.
    """
    argv = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-f", "h264",
        "-i", "pipe:0",
        "-vf", f"select=eq(n\\,{slice_.frames - 1})",
        "-fps_mode", "passthrough",
        "-frames:v", "1",
        "-q:v", "2",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "pipe:1",
    ]  # fmt: skip
    payload = await run_bytes(argv, timeout_s=timeout_s, stdin=slice_.payload)
    if not payload:
        msg = "디코더가 프레임을 내지 못했다 — 조각에 목표 프레임이 없다"
        raise ValueError(msg)
    return payload


class BitstreamTap:
    """카메라 한 대의 메인 스트림을 리먹스로 받아 버퍼를 채운다.

    **디코딩하지 않는다.** `-c:v copy` 라 녹화 프로세스와 같은 부하(리먹스)만 든다.
    녹화와 프로세스를 나눈 이유는, 이것이 죽어도 증거 영상은 계속 쌓여야 하기 때문이다 —
    그림을 잃는 것과 녹화를 잃는 것은 무게가 다르다.
    """

    def __init__(self, cam_id: int, settings: RecSettings, clock: Clock) -> None:
        self._cam_id = cam_id
        self._settings = settings
        self._clock = clock
        self._buffer = BitstreamBuffer(window_s=float(settings.rec_snapshot_window_s))
        self._process: asyncio.subprocess.Process | None = None
        self._stopping = False
        self._warned_b_slice = False

    @property
    def buffer(self) -> BitstreamBuffer:
        return self._buffer

    def _argv(self, ffmpeg: str) -> list[str]:
        return [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "warning",
            "-rtsp_transport", "tcp",
            "-i", self._settings.main_stream_url(self._cam_id),
            "-an",
            # **리먹스.** 디코딩은 `GET /keyframe` 이 왔을 때만 한다(기능명세서 §4.4).
            "-c:v", "copy",
            "-f", "h264",
            "pipe:1",
        ]  # fmt: skip

    def _keep_running(self) -> bool:
        return not self._stopping

    async def run(self) -> None:
        """죽으면 백오프를 두고 다시 띄운다. 취소될 때까지 돈다."""
        ffmpeg = require_ffmpeg()
        backoff = _BACKOFF_START_S
        while self._keep_running():
            try:
                await self._run_once(ffmpeg)
            except asyncio.CancelledError:
                await self._terminate()
                raise
            if not self._keep_running():
                return
            # 스냅샷이 끊긴 것은 녹화가 끊긴 것과 다르다 — 경고로 남기되 녹화 감독
            # 루프처럼 시끄럽게 굴지 않는다.
            log.warning(
                "cam%d 스냅샷 프로세스가 끝났다. %.1f초 뒤 재시도한다.", self._cam_id, backoff
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_S)

    async def _run_once(self, ffmpeg: str) -> None:
        self._process = await asyncio.create_subprocess_exec(
            *self._argv(ffmpeg),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=dict(os.environ),
        )
        log.info(
            "cam%d 스냅샷 비트스트림 시작 — 최근 %d초 보관 (디코딩 없음)",
            self._cam_id,
            self._settings.rec_snapshot_window_s,
        )
        if self._process.stdout is not None:
            await self._consume(self._process.stdout)
        await self._process.wait()

    async def _consume(self, stream: asyncio.StreamReader) -> None:
        """Annex-B 스트림을 액세스 유닛 단위로 잘라 버퍼에 넣는다.

        **한 번 읽으면 여러 유닛이 함께 나온다.** 64KB 는 2.5 Mbps 에서 대략 0.2초,
        15fps 기준 3장이다. 셋 모두에 「지금」을 찍으면 그만큼 시각이 뭉개지므로,
        직전 읽기 시각과 지금 사이에 **고르게 펴서** 배정한다. 스트림이 CFR 이므로
        이 근사의 오차는 프레임 간격 이내다.
        """
        pending = b""
        previous = self._clock.now()
        while True:
            chunk = await stream.read(_CHUNK)
            if not chunk:
                return
            units, pending = split_access_units(pending + chunk)
            now = self._clock.now()
            span = (now - previous) / max(len(units), 1)
            for index, (payload, is_idr) in enumerate(units, start=1):
                self._buffer.add(
                    AccessUnit(at=previous + span * index, payload=payload, is_idr=is_idr)
                )
                self._check_b_slice(payload)
            previous = now

    def _check_b_slice(self, payload: bytes) -> None:
        """B프레임이 섞이면 한 번만 경고한다. 조용히 어긋난 그림을 내지 않기 위해서다."""
        if self._warned_b_slice or not has_b_slice(payload):
            return
        self._warned_b_slice = True
        log.warning(
            "cam%d 스트림에 B프레임이 있다 — 키프레임이 표시 순서로 최대 재정렬 깊이만큼 "
            "어긋날 수 있다. 카메라를 저지연(B프레임 없음) 설정으로 두어라.",
            self._cam_id,
        )

    async def stop(self) -> None:
        self._stopping = True
        await self._terminate()

    async def _terminate(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        process.kill()
        with contextlib.suppress(ProcessLookupError):
            await process.wait()
