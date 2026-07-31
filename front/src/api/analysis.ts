/**
 * 분석 화면 · 검색 · 챗봇이 쓰는 호출들 (API명세서 §4.2 · §4.3 · §4.4).
 *
 * **여기서 집계하지 않는다.** 시정률·판정 불가율·비율은 전부 서버가 낸 값을 그대로
 * 그린다 — 화면이 다시 계산하면 §6.7 의 규칙이 두 벌이 되고, 그때 개요와 분석 화면이
 * 서로 다른 숫자를 말하게 된다.
 *
 * **`null` 을 0으로 바꾸지 않는다.** 분모가 빈 구간의 비율은 `null` 이고 화면은 그것을
 * `–` 로 그린다(`formatRate`). 서버가 아예 점을 만들지 않은 버킷도 있는데, 그건
 * "그 구간에 판정 가능한 이벤트가 없었다"는 뜻이지 0% 가 아니다.
 */

import type {
  BriefingResponse,
  ChatRequest,
  ChatResponse,
  MetricsDistributionResponse,
  MetricsRepeatResponse,
  MetricsTimeseriesResponse,
  SceneSearchRequest,
  SceneSearchResponse,
} from '../types/contracts'
import { getJson, queryString, sendJson } from './client'

/** §4.2 `GET /metrics/timeseries` — 시정률 추이(FN-UI-05). */
export async function fetchTimeseries(
  params: { metric: string; bucket: string; from?: string; to?: string },
  signal?: AbortSignal,
): Promise<MetricsTimeseriesResponse> {
  return getJson<MetricsTimeseriesResponse>(
    `/metrics/timeseries${queryString({ ...params })}`,
    signal,
  )
}

/** §4.2 `GET /metrics/distribution` — 유형 분포 · 시간대 히트맵(FN-UI-05). */
export async function fetchDistribution(
  params: { by: string; from?: string; to?: string },
  signal?: AbortSignal,
): Promise<MetricsDistributionResponse> {
  return getJson<MetricsDistributionResponse>(
    `/metrics/distribution${queryString({ ...params })}`,
    signal,
  )
}

/** §4.2 `GET /metrics/repeat` — 반복 위반 순위(FN-EVT-06). */
export async function fetchRepeat(
  params: { days?: number; limit?: number } = {},
  signal?: AbortSignal,
): Promise<MetricsRepeatResponse> {
  return getJson<MetricsRepeatResponse>(`/metrics/repeat${queryString({ ...params })}`, signal)
}

/** §4.3 `POST /search/scenes` — 자연어 장면 검색(FN-UI-04). */
export async function searchScenes(
  body: SceneSearchRequest,
  signal?: AbortSignal,
): Promise<SceneSearchResponse> {
  const found = await sendJson<SceneSearchResponse>('POST', '/search/scenes', body, signal)
  if (!found) throw new Error('검색 응답이 비어 있다')
  return found
}

/** §4.4 `POST /assistant/chat` — 챗봇(FN-UI-06). */
export async function askAssistant(
  body: ChatRequest,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const answer = await sendJson<ChatResponse>('POST', '/assistant/chat', body, signal)
  if (!answer) throw new Error('답변이 비어 있다')
  return answer
}

/** §4.4 `POST /assistant/briefing` — 현장 브리핑(FN-AI-09). */
export async function fetchBriefing(
  camIds: number[],
  signal?: AbortSignal,
): Promise<BriefingResponse> {
  const brief = await sendJson<BriefingResponse>(
    'POST',
    '/assistant/briefing',
    { cam_ids: camIds },
    signal,
  )
  if (!brief) throw new Error('브리핑이 비어 있다')
  return brief
}

/** 생성 중인 주간 보고서 한 건(§4.4 + 조회 경로). */
export type WeeklyReport = {
  report_id: string
  status: string
  from: string
  to: string
  body: string | null
  stats?: { total_violations: number }
}

/** §4.4 `POST /reports/weekly` — 생성을 **예약**한다. 응답은 즉시 온다(FN-AI-10). */
export async function requestWeeklyReport(
  from: string,
  to: string,
  signal?: AbortSignal,
): Promise<string> {
  const started = await sendJson<{ report_id: string }>(
    'POST',
    '/reports/weekly',
    { from, to },
    signal,
  )
  if (!started) throw new Error('보고서 예약이 비어 있다')
  return started.report_id
}

/** 예약한 보고서를 받는다. 아직이면 `status = "generating"` 이다. */
export async function fetchReport(
  reportId: string,
  signal?: AbortSignal,
): Promise<WeeklyReport> {
  return getJson<WeeklyReport>(`/reports/${reportId}`, signal)
}
