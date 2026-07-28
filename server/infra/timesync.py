"""시각 동기화 확인 (FN-SYS-02).

**클립 구간 정합의 전제다.** 엣지가 `2026-08-14T05:36:53Z` 에 위반을 확정했다고 알려도,
서버 시계가 2초 어긋나 있으면 REC 에서 잘라오는 10초가 통째로 밀린다. 그러면 증거
영상에 위반 장면이 없다. 이 실패는 조용하다 — 클립은 정상적으로 만들어지고 재생도
되기 때문에, 사람이 영상을 열어보기 전까지 아무도 모른다. 그래서 기동 시 재서 남긴다.

SNTP(RFC 4330) 요청 하나를 직접 만든다. 라이브러리를 붙이지 않는 이유는 필요한 것이
"패킷 하나 보내고 타임스탬프 넷을 빼는 것"뿐이고, 그 정도에 의존성을 늘리면 젯슨
이식 때 짐이 되기 때문이다.

엣지 오프셋(`time_sync.edge_offset_ms`)은 여기서 재지 않는다. 그쪽은 `heartbeat`(§2.4)로
받으며 M2 소관이다.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import struct
from dataclasses import dataclass

from aegis_vision.clock import Clock

__all__ = ["TimeSyncReading", "check_time_sync", "measure_ntp_offset"]

log = logging.getLogger("server.timesync")

#: NTP 에포크(1900-01-01)와 유닉스 에포크(1970-01-01)의 차이. RFC 4330.
_NTP_UNIX_DELTA = 2_208_988_800

#: LI=0(경고 없음) · VN=4 · Mode=3(클라이언트). 첫 바이트만 채우면 되는 최소 요청이다.
_CLIENT_PACKET = bytes([0x23]) + b"\0" * 47


@dataclass(frozen=True, slots=True)
class TimeSyncReading:
    """한 번의 측정 결과."""

    server: str
    offset_ms: float | None
    """서버 시계 - NTP 시계 (밀리초). 양수면 우리 시계가 앞서 있다.
    측정에 실패하면 `None` — **0 으로 채우지 않는다.** 0 은 "완벽히 동기화됨"이라는
    강한 주장이고, 재지 못했다는 사실과 정반대다."""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.offset_ms is not None


def _to_ntp_seconds(value: float) -> float:
    return value + _NTP_UNIX_DELTA


def _from_ntp_fixed(seconds: int, fraction: int) -> float:
    """NTP 64비트 고정소수점 → 유닉스 에포크 초."""
    return seconds - _NTP_UNIX_DELTA + fraction / 2**32


def _query(server: str, timeout_s: float, t1: float) -> tuple[float, float, float]:
    """블로킹 SNTP 왕복. (T2, T3, 왕복시간) 을 유닉스 에포크 초로 돌려준다."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout_s)
        sock.sendto(_CLIENT_PACKET, (server, 123))
        data, _ = sock.recvfrom(48)
    if len(data) < 48:
        msg = f"SNTP 응답이 {len(data)}바이트다 (48 필요)"
        raise OSError(msg)
    fields = struct.unpack("!12I", data)
    receive = _from_ntp_fixed(fields[8], fields[9])
    transmit = _from_ntp_fixed(fields[10], fields[11])
    return receive, transmit, t1


async def measure_ntp_offset(
    server: str,
    clock: Clock,
    *,
    timeout_s: float = 3.0,
) -> TimeSyncReading:
    """NTP 서버와의 시계 차이를 잰다. 실패해도 예외를 올리지 않는다.

    인터넷이 끊긴 현장에서도 안전 기능은 완결되어야 하므로(기능명세서 §7), 측정
    실패가 서버 기동을 막으면 안 된다. 대신 **실패했다는 사실을 남긴다** —
    조용히 0으로 채우면 어긋난 시계를 정상으로 보고하게 된다.
    """
    t1 = clock.now().timestamp()
    try:
        receive, transmit, _ = await asyncio.to_thread(_query, server, timeout_s, t1)
    except (OSError, struct.error) as exc:
        return TimeSyncReading(server=server, offset_ms=None, error=str(exc))
    t4 = clock.now().timestamp()

    # RFC 4330 §5. 왕복 지연의 절반을 빼서 편도 지연을 보정한다.
    offset_s = ((receive - t1) + (transmit - t4)) / 2.0
    # 부호는 "우리 시계가 얼마나 앞서 있는가" 로 맞춘다.
    return TimeSyncReading(server=server, offset_ms=-offset_s * 1000.0)


async def check_time_sync(
    server: str,
    clock: Clock,
    *,
    warn_offset_ms: float = 100.0,
    timeout_s: float = 3.0,
) -> TimeSyncReading:
    """기동 시 1회 확인하고 로그를 남긴다.

    `server` 가 비어 있으면 **확인을 끈 것**으로 본다. 인터넷이 없는 현장이 실제로
    있으므로 필요한 선택지지만, 껐다는 사실은 경고로 남긴다 — 가드가 조용히 꺼지는
    것이 이 프로젝트에서 가장 피하려는 실패다(CLAUDE.md 절대규칙 9).
    """
    if not server.strip():
        log.warning(
            "FN-SYS-02 시각 동기화 확인이 꺼져 있다 (NTP_SERVER 비어 있음). "
            "서버 시계가 어긋나면 이벤트 클립 구간이 그만큼 밀린다."
        )
        return TimeSyncReading(
            server=server, offset_ms=None, error="확인 안 함 (NTP_SERVER 비어 있음)"
        )

    reading = await measure_ntp_offset(server, clock, timeout_s=timeout_s)
    if reading.offset_ms is None:
        log.warning(
            "FN-SYS-02 시각 동기화를 확인하지 못했다 (%s): %s. "
            "클립 구간 정합이 서버 시계에 걸려 있으므로 오프라인 현장이 아니라면 확인이 필요하다.",
            server,
            reading.error,
        )
        return reading

    if abs(reading.offset_ms) >= warn_offset_ms:
        log.warning(
            "FN-SYS-02 서버 시계가 %s 기준 %+.1fms 어긋나 있다 (허용 %.0fms). "
            "이대로면 이벤트 클립 구간이 그만큼 밀린다.",
            server,
            reading.offset_ms,
            warn_offset_ms,
        )
    else:
        log.info("FN-SYS-02 시각 동기화 확인 — %s 기준 %+.1fms", server, reading.offset_ms)
    return reading
