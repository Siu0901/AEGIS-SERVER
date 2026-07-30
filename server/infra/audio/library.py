"""음원 이름 → 실제 파일 · 위험 등급 · 표시 이름. FN-ALM-01 · FN-CFG-03

매핑은 **DB(`alert_sounds`)에서 읽는다**(CLAUDE.md 절대규칙 6). 파일명을 코드에 박으면
설정 화면(FN-CFG-03 · M6)에서 음원을 바꿀 수 없고, 현장마다 다른 안내 문구를 쓸 수도 없다.
기능명세서 §6 이 이 테이블을 정의하면서 **등급(`level`)까지 관리자가 바꾸는 값**이 됐다.

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

from aegis_contracts.enums import AlertLevel
from server.domain.alerts import SoundEntry

__all__ = ["DEFAULT_MANUAL_SOUND", "SoundLibrary", "SoundNotFoundError", "SoundReader"]

log = logging.getLogger("server.audio")

#: 수동 방송(§4.5)에서 `sound` 를 생략했을 때 쓰는 **키**.
#:
#: 파일명이 아니라 키다 — 키 → 파일 매핑은 그대로 DB 에 있으므로 절대규칙 6 을 지킨다.
#: §4.5 예시가 쓰는 이름이 그대로 `custom_notice` 이며, `scripts/seed_sounds.py` 가
#: 같은 키를 시드한다. 이 행이 없으면 수동 방송은 실패로 집계되고 조용히 성공하지 않는다.
DEFAULT_MANUAL_SOUND = "custom_notice"


class SoundNotFoundError(LookupError):
    """그 이름의 음원이 등록되지 않았거나 파일이 없다."""


class SoundReader(Protocol):
    """`server.domain.repository.SoundRepository` 중 이 모듈이 쓰는 부분."""

    async def load_sounds(self) -> dict[str, SoundEntry]: ...


class SoundLibrary:
    """`{키: SoundEntry}` 매핑과 음원 디렉토리를 묶어 경로·등급을 내어준다."""

    def __init__(self, root: Path, reader: SoundReader | None = None) -> None:
        self._root = root
        self._reader = reader
        self._mapping: dict[str, SoundEntry] = {}
        self._loaded = False

    @property
    def root(self) -> Path:
        return self._root

    @property
    def keys(self) -> list[str]:
        return sorted(self._mapping)

    @property
    def entries(self) -> dict[str, SoundEntry]:
        """읽어 둔 매핑 전량. 설정 화면(FN-CFG-03 · M6)과 등급 주입이 쓴다."""
        return dict(self._mapping)

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
            entry.file_path
            for entry in sorted(mapping.values(), key=lambda item: item.file_path)
            if not self._resolved(entry.file_path).is_file()
        ]
        if missing:
            log.error(
                "등록된 음원 파일이 없다 (%s): %s — 그 유형은 방송되지 않는다",
                self._root,
                ", ".join(missing),
            )

    def path_for(self, key: str) -> Path:
        """`key` 의 음원 파일 경로. 없으면 `SoundNotFoundError`.

        경로 조합에 `key` 를 쓰지 않는다 — 파일 위치는 DB 가 준 값만 쓰고, 그 값이
        음원 루트를 벗어나면 거부한다. 수동 방송(§4.5 `sound`)의 이름이 바깥에서
        오므로, 그것이 경로가 되면 서버 파일 아무거나 열 수 있다.
        """
        entry = self._mapping.get(key)
        if entry is None:
            known = ", ".join(self.keys) or "(비어 있음)"
            state = "" if self._loaded else " (매핑을 아직 읽지 못했다)"
            msg = f"등록된 음원이 없다: {key!r}{state}. 등록된 이름: {known}"
            raise SoundNotFoundError(msg)
        path = self._resolved(entry.file_path)
        if not self._inside_root(path):
            # §6 이 컬럼 이름을 `file_path` 로 정했으므로 하위 디렉토리는 허용한다.
            # 허용하지 않는 것은 **루트 밖으로 나가는 것**이다 — `..` 든 절대경로든.
            msg = f"음원 경로가 {self._root} 밖을 가리킨다: {entry.file_path!r}"
            raise SoundNotFoundError(msg)
        if not path.is_file():
            msg = f"음원 파일이 없다: {path}"
            raise SoundNotFoundError(msg)
        return path

    def level_for(self, key: str) -> AlertLevel | None:
        """등록된 위험 등급. 등록되지 않은 키면 `None`.

        **`2` 로 대신 채우지 않는다.** 없는 값을 그럴듯한 기본값으로 메우면 시드가
        빠진 상태와 관리자가 2로 정한 상태가 같아 보인다. 부르는 쪽이 그 차이를
        알고 대응한다(`AlertService` 는 상태머신 기본표를 유지한다).
        """
        entry = self._mapping.get(key)
        return None if entry is None else entry.level

    def _resolved(self, file_path: str) -> Path:
        return (self._root / file_path).resolve()

    def _inside_root(self, path: Path) -> bool:
        return path == self._root.resolve() or self._root.resolve() in path.parents
