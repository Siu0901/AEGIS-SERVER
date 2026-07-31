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
from scripts import gen_types


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


def test_types_check_fails_when_the_generated_file_is_stale() -> None:
    """★ 생성물이 낡으면 **통과하지 않는다** (M5 에서 생성기를 구현했다).

    M5 까지 이 테스트는 "미구현 태스크가 0을 돌려주지 않는가"를 봤다. 이제 봐야 하는
    것은 그다음 위험이다 — 계약이 바뀌었는데 `front/src/types/contracts.ts` 가 낡은
    상태로 통과하면, 손으로 옮긴 사본을 쓰던 시절과 똑같이 프론트가 계약과 갈린다.

    파일을 실제로 건드리지 않고 생성기의 판정만 본다 — 여기서 파일을 망가뜨리면
    같은 실행의 다른 단계가 그 상태를 물려받는다.
    """
    generated = gen_types.generate()
    current = gen_types.OUTPUT.read_text(encoding="utf-8")
    assert current == generated, (
        "front/src/types/contracts.ts 가 계약과 다르다. uv run tasks.py types 로 재생성해라."
    )


def test_types_generator_emits_the_whole_contract_surface() -> None:
    """생성 대상을 골라 쓰지 않는다 — 고르면 무엇이 빠졌는지 아무도 모른다.

    `MetricsSummary.suppressed`(§4.8)와 `MuteAlertResponse`(§4.5)는 이번에 생긴 것들이라,
    "새 모델이 자동으로 따라오는가"를 확인하는 표본으로 쓴다.
    """
    text = gen_types.generate()
    for name in ("MetricsSummary", "MuteAlertResponse", "EventDetail", "OverlayMsg", "Policies"):
        assert f"export interface {name} {{" in text, name
    assert "suppressed: number" in text
    # 열거형 별칭도 이름으로 나온다. 값 목록으로 펼쳐지면 프론트가 손으로 다시 적게 된다.
    assert "export type AlertState =" in text


def test_generated_fields_are_not_optional() -> None:
    """`?` 가 붙으면 `Policies.overlay_stale_ms` 가 `number | undefined` 가 된다.

    그 순간 프론트가 값을 코드에 적어 메우게 되고, 그것이 절대규칙 6 이 금지하는 것이다.
    nullable 은 `| null` 로 구분되므로 "없을 수 있다"는 정보는 잃지 않는다.
    """
    assert "?:" not in gen_types.generate()


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


# ---------------------------------------------------------------------------
# 포트 선점 가드 (`tasks.py dev`)
# ---------------------------------------------------------------------------
# ★ 경고가 아니라 중단이어야 한다. 이전 세션 프로세스가 살아 있으면 새 프로세스는
#   포트를 못 잡고 죽는데, 그동안 **옛 프로세스가 옛 코드로 정상 응답한다.**


def test_a_held_port_aborts_and_names_the_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tasks, "listeners_on", lambda port: [(4242, "python.exe")] if port == 8000 else []
    )
    with pytest.raises(tasks.TaskError) as caught:
        tasks.ensure_ports_free()
    message = str(caught.value)
    assert "8000" in message
    assert "4242" in message, "PID 를 알려주지 않으면 무엇을 죽여야 할지 알 수 없다"
    assert "python.exe" in message


def test_free_ports_pass_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "listeners_on", lambda port: [])
    tasks.ensure_ports_free()


def test_a_missing_probe_is_an_error_not_an_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """도구가 없으면 「비어 있다」가 아니라 오류다 (CLAUDE.md 절대규칙 9).

    빈 목록을 돌려주면 가드가 있으나 마나가 되고, 그 사실은 아무 데도 드러나지 않는다.
    """
    monkeypatch.setattr(tasks.shutil, "which", lambda name: None)
    with pytest.raises(tasks.TaskError, match="포트 점유를 확인할 도구가 없다"):
        tasks.listeners_on(8000)


def test_listeners_on_reports_a_real_listener() -> None:
    """가짜가 아니라 **실제로 연 소켓**을 찾아내는지 본다.

    파싱은 OS 도구 출력에 기대므로, 형식이 바뀌면 조용히 0건이 되어 가드가 죽는다.
    그때 이 검사만 실패해야 한다.
    """
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        found = tasks.listeners_on(port)

    import os

    assert [pid for pid, _ in found] == [os.getpid()], f"{port} 를 연 것은 이 프로세스다: {found}"
