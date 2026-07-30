`packages/contracts` 에서 생성되는 TypeScript 타입이 사는 자리다.

| 파일 | 성격 |
|---|---|
| `contracts.ts` | **생성물. 손으로 고치지 마라.** `uv run tasks.py types` 가 쓴다 |
| `system.ts` | 손으로 쓰는 얇은 층 — 생성물 재수출 + 런타임 판별 함수 + 표시 규약(`formatRate`) |
| `labels.ts` | 계약 열거형 → 화면 표기(기능명세서 부록 B 대조표) · 시각·소요시간 표기 |

`uv run tasks.py verify` 가 `contracts.ts` 를 재생성해 대조한다. 계약이 바뀌었는데
이 파일이 낡아 있으면 **검증이 실패한다** — M5 까지 §4.6 · §5.3 을 손으로 옮겨 두었고,
그 사본은 계약이 넓어져도 아무도 잡아주지 않았다.
