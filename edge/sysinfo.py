"""프로세스 자원 사용량. `heartbeat.mem_used_mb`(API명세서 §2.4)가 읽는다.

의존성을 늘리지 않으려고 표준 라이브러리만 쓴다 — 노트북(Windows)과 젯슨(Linux)이
**같은 코드로** 돌아야 하므로 두 경로를 모두 둔다.

**모르면 0 을 돌려주되 한 번은 알린다.** 조용히 0 을 보고하면 대시보드에는 「메모리를
쓰지 않는 엣지」가 보인다(절대규칙 9).
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from pathlib import Path

__all__ = ["memory_used_mb"]

log = logging.getLogger(__name__)

_BYTES_PER_MB = 1024 * 1024
_warned = False


def memory_used_mb() -> int:
    """이 프로세스의 상주 메모리(MB)."""
    try:
        return _windows_rss_mb() if sys.platform == "win32" else _linux_rss_mb()
    except (OSError, ValueError, AttributeError, IndexError):
        global _warned
        if not _warned:
            _warned = True
            log.warning("메모리 사용량을 읽지 못했다 — heartbeat 에 0 으로 나간다")
        return 0


class _ProcessMemoryCounters(ctypes.Structure):
    """`PROCESS_MEMORY_COUNTERS` (psapi.h). `WorkingSetSize` 가 RSS 다."""

    _fields_ = (
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    )


def _windows_rss_mb() -> int:
    """`GetProcessMemoryInfo` 의 `WorkingSetSize`.

    `ctypes.windll` 을 `getattr` 로 꺼낸다 — 리눅스(젯슨)에서 타입 검사를 돌릴 때
    이 속성이 없어서, 직접 쓰면 플랫폼마다 다른 `type: ignore` 가 필요해진다.
    """
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        msg = "windll 이 없다 — 윈도우가 아니다"
        raise OSError(msg)

    # ★ **반환형을 지정해야 한다.** `GetCurrentProcess` 는 HANDLE(포인터 크기)을
    # 돌려주는데 ctypes 기본 반환형은 `c_int`(32비트)라 64비트에서 잘린다. 잘린 값을
    # 넘기면 `GetProcessMemoryInfo` 가 조용히 0을 돌려주고, heartbeat 의
    # `mem_used_mb` 가 계속 0으로 나간다.
    get_current = windll.kernel32.GetCurrentProcess
    get_current.restype = ctypes.c_void_p
    get_current.argtypes = []
    info = windll.psapi.GetProcessMemoryInfo
    info.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
    info.restype = wintypes.BOOL

    if not info(get_current(), ctypes.byref(counters), counters.cb):
        # `get_last_error` 도 윈도우 스텁에만 있다 — `windll` 과 같은 이유로 `getattr` 다.
        last_error = getattr(ctypes, "get_last_error", None)
        code = last_error() if last_error is not None else "?"
        msg = f"GetProcessMemoryInfo 실패 (GetLastError={code})"
        raise OSError(msg)
    return int(counters.WorkingSetSize) // _BYTES_PER_MB


def _linux_rss_mb() -> int:
    """`/proc/self/status` 의 `VmRSS`. **이미 kB 단위라 페이지 크기가 필요 없다.**

    `statm` 은 페이지 수라 `resource.getpagesize()` 가 필요한데, 그 모듈은 윈도우에
    없어서 타입 검사가 플랫폼을 탄다. 여기서는 파일 하나만 읽으면 끝난다.
    """
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) // 1024
    msg = "/proc/self/status 에 VmRSS 가 없다"
    raise OSError(msg)
