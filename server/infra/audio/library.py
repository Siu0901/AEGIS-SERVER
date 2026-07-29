"""음원 이름 → 실제 파일. FN-ALM-01 · FN-CFG-03

매핑은 **DB(`alert_sounds`)에서 읽는다**(CLAUDE.md 절대규칙 6). 파일명을 코드에 박으면
설정 화면(FN-CFG-03 · M6)에서 음원을 바꿀 수 없고, 현장마다 다른 안내 문구를 쓸 수도 없다.

**매번 DB 를 읽지 않는다.** 경고는 확정과 같은 순간에 나가야 하고(1초 이내), 그 경로에
DB 왕복을 넣으면 그만큼이 예산에서 빠진다. 기동 시 한 번 읽고, 이후 주기적으로 새로
읽는다 — 정책값(`POLICY_REFRESH_SECONDS`)과 같은 방식이다.

**파일이 없으면 조용히 넘어가지 않는다.** 등록된 파일이 디스크에 없으면 그 사실을
`missing` 으로 남기고 재생 요청 때 예외를 낸다. "재생했다"는 기록만 남고 아무 소리도
나지 않는 상태가 가장 위험하다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

__all__ = ["SoundLibrary", "SoundNotFoundError", "SoundReader"]

log = logging.getLogger("server.audio")


class SoundNotFoundError(LookupError):
    """그 이름의 음원이 등록되지 않았거나 파일이 없다."""


class SoundReader(Protocol):
    """`server.domain.repository.SoundRepository` 중 이 모듈이 쓰는 부분."""

    async def load_sounds(self) -> dict[str, str]: ...


class SoundLibrary:
    """`{key: 파일명}` 매핑과 음원 디렉토리를 묶어 경로를 내어준다."""

    def __init__(self, root: Path, reader: SoundReader | None = None) -> None:
        self._root = root
        self._reader = reader
        self._mapping: dict[str, str] = {}
        self._loaded = False

    @property
    def root(self) -> Path:
        return self._root

    @property
    def keys(self) -> list[str]:
        return sorted(self._mapping)

    async def refresh(self) -> None:
        """DB 에서 매핑을 다시 읽는다. 실패해도 **직전 매핑을 유지한다.**

        DB 가 잠깐 끊겼다고 경고음이 멎으면, 데이터베이스 장애가 안전 기능 정지로
        번진다. 이 방향은 FN-SYS-03 이 클라우드에 대해 요구하는 격리와 같은 이유다.
        """
        if self._reader is None:
            return
        try:
            mapping = await self._reader.load_sounds()
        except Exception:
            log.exception(
                "음원 매핑을 읽지 못했다 — 직전 매핑(%d건)으로 계속한다", len(self._mapping)
            )
            return
        if not mapping:
            log.error(
                "alert_sounds 테이블이 비어 있다 — 경고 방송이 나가지 않는다. "
                "uv run python -m scripts.seed_sounds 로 시드해라"
            )
        self._mapping = mapping
        self._loaded = True
        missing = [
            name for name in sorted(set(mapping.values())) if not (self._root / name).is_file()
        ]
        if missing:
            log.error(
                "등록된 음원 파일이 없다 (%s): %s — 그 유형은 방송되지 않는다",
                self._root,
                ", ".join(missing),
            )

    def path_for(self, key: str) -> Path:
        """`key` 의 음원 파일 경로. 없으면 `SoundNotFoundError`.

        경로 조합에 `key` 를 쓰지 않는다 — 파일명은 DB 가 준 값만 쓰고, 그 값에
        디렉토리 구분자가 섞여 있으면 거부한다. 수동 방송(§4.5 `sound`)의 이름이
        바깥에서 오므로, 그것이 경로가 되면 서버 파일 아무거나 열 수 있다.
        """
        filename = self._mapping.get(key)
        if filename is None:
            known = ", ".join(self.keys) or "(비어 있음)"
            state = "" if self._loaded else " (매핑을 아직 읽지 못했다)"
            msg = f"등록된 음원이 없다: {key!r}{state}. 등록된 이름: {known}"
            raise SoundNotFoundError(msg)
        if Path(filename).name != filename:
            msg = f"음원 파일명에 경로가 섞여 있다: {filename!r}"
            raise SoundNotFoundError(msg)
        path = self._root / filename
        if not path.is_file():
            msg = f"음원 파일이 없다: {path}"
            raise SoundNotFoundError(msg)
        return path
