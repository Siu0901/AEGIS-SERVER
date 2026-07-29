# assets

위반 유형별 사전 녹음 경고 음원 wav(FN-ALM-01 · TTS 아님), 규정 매핑 테이블(FN-AI-06),
사고사례 시드 데이터(FN-AI-07)를 둔다.

## audio/ — 경고 음원 (FN-ALM-01)

기능명세서 §4.3 이 정한 음원 넷과 수동 방송(FN-ALM-04) 예시 하나가 있다.

| 파일 | 안내 문구 |
|---|---|
| `no_helmet.wav` | "안전모를 착용해 주십시오" |
| `zone_intrusion.wav` | "위험구역입니다. 즉시 이탈하십시오" |
| `proximity.wav` | "중장비 작업 반경입니다. 물러나 주십시오" |
| `fall.wav` | 구조 안내 — **시정 유도 문구가 아니다.** 쓰러진 사람은 방송을 듣고 스스로 시정할 수 없다(§4.1) |
| `custom_notice.wav` | 수동 방송 예시 (`POST /alerts/manual` 의 `sound`) |

**지금 들어 있는 것은 2초짜리 무음이다.** `uv run tasks.py migrate` 가 파일이 없을 때
자동으로 만든 자리표시자이며, **실제 녹음으로 그대로 덮어쓰면 된다** — 시드는 이미 있는
파일을 건드리지 않는다.

**파일명을 코드에서 찾지 마라.** 유형 → 파일 매핑은 DB `alert_sounds` 테이블에 있고
(절대규칙 6 · FN-CFG-03), 기본값의 원천은 `scripts/seed_sounds.py` 다. 다른 파일명을
쓰고 싶으면 그 테이블을 고친다.

규격: 16kHz · 16bit · 모노 wav. 재생은 `server/infra/audio/player.py` 가 하며 Windows 는
`winsound`, 리눅스·젯슨은 `ffplay`/`aplay`/`paplay` 를 쓴다.
