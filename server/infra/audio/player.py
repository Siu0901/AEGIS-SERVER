"""서버 직결 스피커로 wav 를 재생한다. FN-ALM-01 (기능명세서 §4.3)

**TTS 가 아니다.** 위반 유형별로 **사전 녹음된 wav** 를 틀며, 요구는 확정 시점부터
방송 시작까지 **1초 이내**다. 문장을 생성하는 순간 그 예산이 사라진다.

**재생은 기다리지 않는다.** 음원 길이가 2~3초인데 그동안 코루틴을 잡고 있으면 같은
루프에서 도는 `/ws/edge` 수신이 멈춘다 — 경고 하나가 다음 프레임들을 밀어낸다.
그래서 모든 백엔드는 "재생을 **시작**시키고 즉시 돌아온다".

| 플랫폼 | 백엔드 | 이유 |
|---|---|---|
| Windows (개발) | `winsound.PlaySound(..., SND_ASYNC)` | 표준 라이브러리, 외부 프로세스 없음 |
| Linux (젯슨 · 운용) | `ffplay` → `aplay` → `paplay` | ffmpeg 은 이미 쓰는 의존성이다 |

**도구가 없으면 통과가 아니라 오류다**(CLAUDE.md 절대규칙 9). 재생할 방법을 찾지 못하면
`SilentPlayer` 가 그 자리를 대신하되, 조용히 성공한 척하지 않고 **매번 ERROR 를 남기고
실패로 집계**한다. 경고음이 나가지 않은 것은 감지가 실패한 것과 같은 급의 사건이다.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

__all__ = [
    "POSIX_PLAYERS",
    "CommandPlayer",
    "SilentPlayer",
    "SoundPlayer",
    "WinsoundPlayer",
    "resolve_player",
]

log = logging.getLogger("server.audio")

#: 리눅스에서 찾아볼 재생기와 인자. 앞에서부터 PATH 에 있는 것을 쓴다.
#:
#: `ffplay` 가 먼저인 것은 ffmpeg 이 이미 이 프로젝트의 의존성이기 때문이다
#: (`deploy/fake_cams.py` · `recorder/ffmpeg.py`). 젯슨에 따로 깔 것이 늘지 않는다.
POSIX_PLAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ffplay", ("-nodisp", "-autoexit", "-loglevel", "quiet")),
    ("aplay", ("-q",)),
    ("paplay", ()),
)


class SoundPlayer(Protocol):
    """재생을 **시작**시키고 즉시 돌아온다. 끝날 때까지 기다리지 않는다."""

    @property
    def name(self) -> str:
        """진단용 백엔드 이름. `GET /system/status` 나 로그에 찍힌다."""
        ...

    def play(self, path: Path) -> None:
        """`path` 의 wav 재생을 시작한다. 실패하면 예외를 낸다."""
        ...


class WinsoundPlayer:
    """Windows 표준 라이브러리. `SND_ASYNC` 라 호출이 즉시 돌아온다."""

    name = "winsound"

    def play(self, path: Path) -> None:
        # ★ **`getattr` 로 꺼낸다.** `winsound` 스텁은 윈도우에서만 속성을 갖는다. 점으로
        #   직접 쓰면 macOS·리눅스에서 mypy 가 `PlaySound`·`SND_*` 를 못 찾고, 그렇다고
        #   `sys.platform` 으로 감싸면 반대편 플랫폼에서 그 블록이 도달 불가가 되어
        #   `warn_unreachable` 이 잡는다(실측). 어느 쪽에서도 조용하지 않은 방법은 이것뿐이다.
        #   플랫폼 판단은 `resolve_player` 가 이미 한다.
        import winsound

        # SND_FILENAME: 인자를 파일 경로로 읽는다 / SND_ASYNC: 기다리지 않는다
        # SND_NODEFAULT: 파일을 못 읽어도 기본 삑 소리로 대신하지 않는다 —
        # 그 대체음이 나면 "경고가 나갔다"로 착각하게 된다.
        play_sound = getattr(winsound, "PlaySound")  # noqa: B009
        flags = (
            getattr(winsound, "SND_FILENAME")  # noqa: B009
            | getattr(winsound, "SND_ASYNC")  # noqa: B009
            | getattr(winsound, "SND_NODEFAULT")  # noqa: B009
        )
        play_sound(str(path), flags)


class CommandPlayer:
    """외부 재생기를 띄운다(리눅스 · 젯슨).

    `Popen` 으로 띄우고 기다리지 않는다. 자식이 끝나면 좀비로 남는데, 경고는 드문
    사건이고 프로세스는 짧게 산다 — 그래도 목록을 들고 있다가 다음 재생 때 걷어낸다.
    """

    def __init__(self, executable: str, args: tuple[str, ...]) -> None:
        self._executable = executable
        self._args = args
        self._running: list[subprocess.Popen[bytes]] = []

    @property
    def name(self) -> str:
        return Path(self._executable).stem

    def play(self, path: Path) -> None:
        self._reap()
        self._running.append(
            # 경로도 인자도 서버가 만든 값이다 — 사용자 입력이 셸로 가지 않는다.
            subprocess.Popen(
                [self._executable, *self._args, str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        )

    def _reap(self) -> None:
        self._running = [proc for proc in self._running if proc.poll() is None]


class SilentPlayer:
    """재생 수단이 없다. **성공한 척하지 않는다.**

    `verify` 가 도는 CI 나 사운드 장치가 없는 기계에서 서버가 뜨지 못하면 곤란하므로
    기동은 막지 않되, 재생을 요구받을 때마다 예외를 낸다. 집행 계층이 그것을 잡아
    ERROR 로 남기고 실패로 집계한다 — 「경고음이 나갔다」는 기록이 남지 않는다.
    """

    name = "none"

    def play(self, path: Path) -> None:
        msg = f"재생 수단이 없어 경고음을 내지 못했다: {path.name}"
        raise RuntimeError(msg)


def resolve_player(backend: str = "auto") -> SoundPlayer:
    """플랫폼에 맞는 재생기를 고른다.

    Args:
        backend: `auto` (기본) · `winsound` · `ffplay`/`aplay`/`paplay` · `none`.
            `.env` 의 `AUDIO_BACKEND` 로 주입한다 — 사운드 장치가 없는 기계에서
            `none` 을 **명시적으로** 고르게 하기 위한 자리다.

    `none` 을 자동으로 고르지 않는다. 재생 수단이 없는 것은 **설정으로 선언해야 하는
    사실**이지, 서버가 알아서 조용해질 근거가 아니다.
    """
    if backend == "none":
        log.warning("AUDIO_BACKEND=none — 경고 방송을 내지 않는다. 실물 운용 설정이 아니다")
        return SilentPlayer()

    if backend in {"auto", "winsound"} and sys.platform == "win32":
        return WinsoundPlayer()
    if backend == "winsound":
        msg = "AUDIO_BACKEND=winsound 는 Windows 에서만 쓸 수 있다"
        raise RuntimeError(msg)

    wanted = (
        POSIX_PLAYERS
        if backend == "auto"
        else tuple(item for item in POSIX_PLAYERS if item[0] == backend)
    )
    if not wanted:
        msg = f"알 수 없는 AUDIO_BACKEND: {backend!r}"
        raise RuntimeError(msg)
    for executable, args in wanted:
        found = shutil.which(executable)
        if found is not None:
            return CommandPlayer(found, args)

    names = ", ".join(name for name, _ in wanted)
    log.error(
        "재생기를 찾지 못했다 (%s). 경고 방송이 나가지 않는다 — 설치하거나 "
        "AUDIO_BACKEND=none 으로 명시해라",
        names,
    )
    return SilentPlayer()


async def play_async(player: SoundPlayer, path: Path) -> None:
    """재생 시작을 이벤트 루프 밖으로 보낸다.

    `winsound.PlaySound` 는 `SND_ASYNC` 라도 장치를 열 때 수 ms~수십 ms 를 쓰고,
    `Popen` 은 프로세스를 만드는 동안 블로킹한다. 그 시간에 `/ws/edge` 가 멈추면
    다음 프레임의 관측 시각이 밀려 **타이머가 그만큼 늦게 흐른다.**
    """
    await asyncio.to_thread(player.play, path)
