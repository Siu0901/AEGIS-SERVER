"""태스크 러너가 '건너뛰기'로 통과하지 않는지 잠근다.

M0 에서 `make verify` 는 Windows 에 make 가 없어 한 번도 실행되지 않았고, 그 안의
`command -v npm || skip` 은 도구가 없으면 조용히 건너뛰었다. 양쪽 다 "통과"로
보고됐다. 그 두 가지가 다시 생기지 않게 막는 것이 이 파일의 목적이다.
"""

from __future__ import annotations

import sys

import pytest

import tasks
from deploy import fake_cams


def test_missing_executable_raises_not_skips() -> None:
    """없는 도구는 건너뛰기가 아니라 오류다. 이번 사고의 직접 원인이다."""
    with pytest.raises(tasks.TaskError, match="실행 파일을 찾을 수 없다"):
        tasks.executable("aegis-definitely-not-a-real-tool")


def test_run_raises_on_nonzero_exit() -> None:
    with pytest.raises(tasks.TaskError, match="종료코드 3"):
        tasks.run([sys.executable, "-c", "import sys; sys.exit(3)"], echo=False)


def test_run_returns_quietly_on_success() -> None:
    tasks.run([sys.executable, "-c", "pass"], echo=False)


def test_capture_raises_on_nonzero_exit() -> None:
    with pytest.raises(tasks.TaskError, match="종료코드 1"):
        tasks.capture([sys.executable, "-c", "import sys; sys.exit(1)"], echo=False)


def test_nothing_to_do_is_tracked_separately() -> None:
    """'대상 없음'은 통과로 세지 않는다. 세면 빈 단계가 통과로 둔갑한다."""
    step = tasks.Progress(total=1)
    step.nothing_to_do("빈 단계", "아직 대상이 없다")
    assert step.empty == ["빈 단계 - 아직 대상이 없다"]


def test_types_task_fails_until_implemented() -> None:
    """미구현 태스크가 0을 돌려주면 안 된다 (M5 에서 구현하면 이 테스트를 바꾼다)."""
    with pytest.raises(tasks.TaskError, match="M5"):
        tasks.task_types()


@pytest.mark.parametrize("size", ["640x640", "1024x1024", "800x600"])
def test_sub_stream_must_be_16_9(size: str) -> None:
    """서브를 정사각으로 두면 정규화 좌표가 어긋난다 (API명세서 §1.2)."""
    with pytest.raises(fake_cams.CamsError, match="16:9"):
        fake_cams.require_16_9("SUB_SIZE", size)


@pytest.mark.parametrize("size", ["1920x1080", "640x360", "1280x720"])
def test_16_9_sizes_pass(size: str) -> None:
    assert fake_cams.require_16_9("SUB_SIZE", size)


def test_malformed_size_is_rejected() -> None:
    with pytest.raises(fake_cams.CamsError, match="해상도 형식 오류"):
        fake_cams.require_16_9("SUB_SIZE", "640-360")
