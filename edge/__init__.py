"""AEGIS 엣지 러너 — 디코드 · 감지 · 추적 · 분류 · 뎁스 → `/ws/edge`.

**엣지는 판단하지 않는다**(CLAUDE.md 절대규칙 3). 규칙에 걸리면 후보(`candidate`)만
올리고 확정·경고·시정판정·재결합은 전부 서버가 한다. `sim/edge_sim` 이 지키는 규칙과
같으며, 서버 입장에서 둘은 구분되지 않아야 한다.

| 모듈 | 역할 |
|---|---|
| `config` | `edge/config.yaml` 로딩 — 모델 경로·백엔드·입력 형태 |
| `letterbox` | 모델 입력 좌표 ↔ 정규화 프레임 좌표 (순수 계산) |
| `detect` | seg 추론 — 박스와 마스크 윤곽 |
| `classify` | 안전모 2단계 분류 — 크기·신뢰도 게이팅과 캐시 |
| `depth` | 온디맨드 뎁스 — `aegis_vision.DepthProbe` 구현 |
| `track` | ByteTrack — `track_id` 부여와 소실 통지 |
| `gauges` | 마스크 → 접지점·자세·거리 (`packages/vision` 호출) |
| `client` | `/ws/edge` 송신 · REST 로 호모그래피·구역·정책 조회 |
| `runner` | 카메라 한 대의 루프 |

**계산에 쓰는 마스크는 밖으로 나가지 않는다.** 계약에 마스크 필드가 없다.
"""
