/**
 * 지표 조회 (API명세서 §4.2 `GET /metrics/summary` · FN-SYS-04 · FN-SYS-05).
 *
 * **`metric`(§5.3) 을 받으면 다시 조회한다.** 그 메시지에는 `suppressed` 가 없어서
 * (§5.3 페이로드가 §4.2 의 부분집합이다) WebSocket 값만으로 화면을 갱신하면
 * 「방송 없이 확정된 건수」가 낡은 채 남는다. 그 숫자는 **분모가 왜 줄었는지**를
 * 설명하는 값이므로 시정률과 함께 움직여야 한다.
 *
 * 종결 전이마다 한 번 더 묻는 셈이지만, 카메라 2대 규모에서 그 빈도는 분당 몇 건이다.
 */

import type { MetricsSummary } from '../types/system'
import { getJson, queryString } from './client'

/**
 * `period` 를 주지 않으면 서버가 **「오늘」**로 답한다(§4.2).
 *
 * ★ **기간을 고를 수 있는 화면은 반드시 넘겨야 한다.** 예전에는 이 함수가 기간을
 *   아예 받지 못해서, 분석 화면에서 7일·30일을 골라도 요약 네 칸만 「오늘」을 보고
 *   있었다. 추이 그래프와 유형 분포는 기간을 따라가는데 그 위의 시정률·모집단만
 *   0 과 `–` 로 남아, 화면 하나가 서로 다른 두 기간을 동시에 말했다.
 */
export async function fetchMetricsSummary(
  period: { from?: string; to?: string } = {},
  signal?: AbortSignal,
): Promise<MetricsSummary> {
  return getJson<MetricsSummary>(`/metrics/summary${queryString({ ...period })}`, signal)
}
