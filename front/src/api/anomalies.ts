/**
 * 이상 탐지 (FN-AI-04 · API명세서 §5.3 `anomaly` · `GET /anomalies`).
 *
 * ★ **이것은 경고가 아니라 '주의'다.** 기능명세서 §4.5 가 못 박았다 — 경고 방송·경광등을
 * 발동하지 않고 대시보드 알림으로만 표시한다. 조명·날씨·평소 없던 자재 적재로도 점수가
 * 오르기 때문이고, 그때마다 스피커가 울리면 **현장이 경보를 무시하는 법을 배운다.**
 *
 * ---
 *
 * **두 경로가 같은 것을 나른다.**
 *
 * | 경로 | 언제 | 무엇이 빠지나 |
 * |---|---|---|
 * | `GET /anomalies` | 화면을 열 때 | 연 뒤에 생긴 것 |
 * | §5.3 `anomaly` | 생기는 순간 | 열기 전에 생긴 것 · 놓친 메시지 |
 *
 * 둘 중 하나만 쓰면 구멍이 생긴다 — WebSocket 만 보면 새로고침한 화면이 텅 비고,
 * 조회만 하면 보고 있는 동안 생긴 이상이 안 뜬다. `mergeAnomalies` 가 둘을 합치며,
 * **순수 함수라 클라우드 없이도 테스트가 잠근다**(`anomalies.test.ts`).
 */

import type { AnomalyListResponse, AnomalyItem, AnomalyMsg } from '../types/contracts'
import { getJson, queryString } from './client'

export type { AnomalyItem }

/** 화면이 한 번에 들고 있을 최대 개수. 넘치면 오래된 것부터 버린다. */
export const ANOMALY_KEEP = 50

/** `GET /anomalies` — 최근 이상 플래그. 화면을 열 때 한 번 읽는다. */
export async function fetchAnomalies(
  params: { days?: number; limit?: number } = {},
  signal?: AbortSignal,
): Promise<AnomalyItem[]> {
  const found = await getJson<AnomalyListResponse>(`/anomalies${queryString({ ...params })}`, signal)
  return found.items
}

/**
 * §5.3 `anomaly` 메시지를 목록 항목으로. **`type` 만 떼면 같은 모양이다.**
 *
 * 서버가 두 경로에 같은 필드를 싣기로 했으므로 여기서 변환이 필요 없다 — 만약
 * 나중에 갈라지면 이 함수가 컴파일되지 않아 그 사실이 드러난다.
 */
export function toItem(message: AnomalyMsg): AnomalyItem {
  const { type: _type, ...item } = message
  return item
}

/**
 * 이미 들고 있던 목록에 새 것들을 합친다. **최신 순 · 중복 없음 · 상한 있음.**
 *
 * `anomaly_id` 로 중복을 없애는 이유: 화면을 연 직후 조회 결과와 WebSocket 메시지가
 * 같은 플래그를 함께 나를 수 있다(조회 응답이 오는 사이에 발행된 것). 그때 같은
 * 이상이 두 줄로 보이면 사람은 두 번 일어난 일로 읽는다.
 *
 * **순수 함수다.** 이 파일에서 유일하게 판단이 있는 곳이고, 그래서 여기만 테스트한다.
 */
export function mergeAnomalies(
  current: readonly AnomalyItem[],
  incoming: readonly AnomalyItem[],
  keep: number = ANOMALY_KEEP,
): AnomalyItem[] {
  const byId = new Map<number, AnomalyItem>()
  // 나중에 넣은 것이 이긴다 — `incoming` 이 더 새로운 관측이다(설명이 붙었을 수 있다).
  for (const item of current) byId.set(item.anomaly_id, item)
  for (const item of incoming) byId.set(item.anomaly_id, item)
  return [...byId.values()]
    .sort((a, b) => b.detected_at.localeCompare(a.detected_at))
    .slice(0, keep)
}

/**
 * 점수를 사람이 읽는 등급으로. **위반 등급(§3 `level`)과 다른 축이다.**
 *
 * 이상 점수는 「평소와 얼마나 다른가」이지 「얼마나 위험한가」가 아니다. 그래서
 * `danger` 를 쓰지 않는다 — 화면에서 위반과 같은 적색이 되면 안 된다.
 */
export function anomalyTone(score: number): 'warn' | 'muted' {
  return score >= 0.5 ? 'warn' : 'muted'
}
