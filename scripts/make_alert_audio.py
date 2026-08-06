"""경고 음원 wav 를 만든다. **일회성 저작 도구이며 런타임은 이것을 쓰지 않는다.**

    uv run python -m scripts.make_alert_audio --list     # 문구와 현재 상태만 본다
    uv run python -m scripts.make_alert_audio            # 무음 자리표만 채운다
    uv run python -m scripts.make_alert_audio --force    # 실제 녹음까지 덮어쓴다

★ **경고 방송은 런타임 TTS 가 아니다**(CLAUDE.md · 기능명세서 §4.3). 위반이 확정되면
「확정 → 경고 1초 이내」를 맞춰야 하는데, 그때 음성을 생성하면 그 지연이 그대로 들어온다.
그래서 재생 경로는 **완성된 wav 를 열기만** 한다. 이 스크립트는 그 wav 를 **미리** 만드는
저작 단계이고, 서버는 이 스크립트의 존재를 모른다.

`scripts/seed_sounds.py` 가 깔아 두는 것은 **길이만 있는 무음**이다. 재생 경로·매핑·백엔드를
먼저 검증하려는 의도인데, 그 상태로 두면 스피커를 연결해도 아무 소리가 나지 않는다.
여기서 그 자리표를 실제 음성으로 바꾼다.

**가장 좋은 것은 사람이 녹음한 파일이다.** 현장 안내 방송은 억양과 속도가 전달력을
좌우한다. 이 스크립트가 만드는 것은 그것을 넣기 전까지 쓸 수 있는, 무음보다 나은 음원이다.
그래서 **무음이 아닌 파일은 기본적으로 건드리지 않는다** — 녹음을 합성음으로 덮어쓰는
사고를 막는다.

Windows SAPI(`System.Speech`)를 쓴다. 오프라인이고 윈도우에 이미 들어 있어 의존성이
늘지 않는다. 한국어 음성(예: Microsoft Heami)이 설치돼 있어야 한다.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

__all__ = ["PHRASES", "is_silent", "main", "synthesize"]

#: 레포 루트. `scripts/make_alert_audio.py` 기준 한 단계 위다.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: 음원이 사는 곳. `scripts/seed_sounds.py` 와 같은 자리를 본다.
AUDIO_DIR = REPO_ROOT / "assets" / "audio"

#: 안내 문구. 파일 이름과 등급의 원천은 `seed_sounds.DEFAULT_SOUNDS` 이고 DB 다.
#: 여기 있는 것은 **문구뿐**이다(기능명세서 §4.3 「음원 예」).
#:
#: ★ `fall` 만 성격이 다르다. 쓰러진 사람은 스스로 시정할 수 없으므로 **시정 유도가
#:   아니라 구조 안내**여야 한다(§4.1). 주위 사람에게 말하는 문장이다.
PHRASES: dict[str, str] = {
    "no_helmet": "안전모를 착용해 주십시오.",
    "zone_intrusion": "위험구역입니다. 즉시 이탈하십시오.",
    "proximity": "지게차 작업 반경입니다. 물러나 주십시오.",
    "fall": "쓰러진 작업자가 있습니다. 즉시 확인해 주십시오.",
    "custom_notice": "관리자 안내 방송입니다.",
}

#: 출력 규격. `seed_sounds` 의 무음과 같게 맞춘다 — 16kHz · 16bit · 모노.
#: 재생기(winsound · ffplay · aplay · paplay)가 전부 무난히 연다.
SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2
CHANNELS = 1

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _say(message: str = "") -> None:
    print(message, flush=True)


def is_silent(path: Path) -> bool:
    """전 구간이 0 인가.

    `seed_sounds` 의 자리표를 알아보는 데 쓴다. 길이가 있어도 소리가 없으면 스피커를
    연결해도 아무 일이 없으므로, **파일 존재만으로 「음원이 있다」고 보지 않는다.**
    """
    if not path.is_file():
        return False
    try:
        with wave.open(str(path), "rb") as source:
            frames = source.readframes(source.getnframes())
    except (OSError, wave.Error):
        return False
    return not frames.strip(b"\x00")


def synthesize(text: str, target: Path) -> None:
    """Windows SAPI 로 `text` 를 `target` wav 에 쓴다.

    파이썬에서 SAPI 를 직접 부르려면 `pywin32` 가 필요한데, 음원 몇 개를 만들자고
    의존성을 늘리지 않는다. PowerShell 을 한 번 부르는 편이 가볍다.

    스크립트를 임시 파일로 넘긴다 — 명령줄에 한글을 실으면 콘솔 코드페이지에서 깨진다.
    """
    if sys.platform != "win32":
        msg = (
            "이 스크립트는 Windows SAPI 를 쓴다. 다른 OS 에서는 음원을 직접 녹음하거나 "
            "가진 TTS 로 만들어 assets/audio 에 넣어라 (16kHz · 16bit · 모노 wav)."
        )
        raise SystemExit(msg)

    target.parent.mkdir(parents=True, exist_ok=True)
    script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$ko = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'ko*' }}
if (-not $ko) {{ throw '한국어 SAPI 음성이 없다. 설정 > 시간 및 언어 > 음성 에서 추가해라.' }}
$s.SelectVoice($ko[0].VoiceInfo.Name)
$s.Rate = -1
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    {SAMPLE_RATE},
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile('{target}', $fmt)
$s.Speak('{text}')
$s.Dispose()
"""
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".ps1",
        delete=False,
        encoding="utf-8-sig",
    ) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    if result.returncode != 0:
        msg = f"SAPI 합성이 실패했다 (코드 {result.returncode})\n{result.stderr.strip()}"
        raise SystemExit(msg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="make_alert_audio",
        description="경고 음원 wav 생성 (일회성 저작 · 런타임 TTS 가 아니다)",
    )
    parser.add_argument("--list", action="store_true", help="문구와 현재 상태만 본다")
    parser.add_argument(
        "--force",
        action="store_true",
        help="무음이 아닌 파일도 덮어쓴다 (사람이 녹음한 것을 지울 수 있다)",
    )
    args = parser.parse_args(argv)

    _say("[audio] assets/audio")
    for key, text in PHRASES.items():
        path = AUDIO_DIR / f"{key}.wav"
        if not path.is_file():
            state = "없음"
        elif is_silent(path):
            state = "무음 자리표"
        else:
            state = "음원 있음"
        _say(f"  · {key:<15} [{state}]  {text}")
    if args.list:
        return 0

    _say()
    made, kept = 0, 0
    for key, text in PHRASES.items():
        path = AUDIO_DIR / f"{key}.wav"
        if path.is_file() and not is_silent(path) and not args.force:
            _say(f"  · {key}: 이미 음원이 있다 — 건드리지 않는다 (--force 로 덮어쓴다)")
            kept += 1
            continue
        synthesize(text, path)
        # ★ **만들었다고 곧바로 성공으로 보고하지 않는다.** SAPI 가 조용히 빈 파일을
        #   남기는 경우가 있고, 그러면 무음을 무음으로 바꾸고 성공했다고 말하게 된다
        #   (절대규칙 9).
        if is_silent(path):
            msg = f"{key}: 합성 결과가 무음이다 — 한국어 음성 설치와 출력 장치를 확인해라"
            raise SystemExit(msg)
        with wave.open(str(path), "rb") as check:
            seconds = check.getnframes() / check.getframerate()
        _say(f"  · {key}: {path.name}  {seconds:.1f}초  {path.stat().st_size:,} bytes")
        made += 1

    _say()
    _say("=" * 34)
    _say(f"음원 {made}개 생성 · {kept}개 유지")
    if made:
        _say("합성음이다. 시연 전에 사람 녹음으로 바꾸는 편이 전달력이 좋다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
