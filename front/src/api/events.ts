/**
 * 이벤트 조회와 수동 정정 (API명세서 §4.1 · FN-UI-03 · FN-EVT-05).
 *
 * 목록은 **커서 페이징**이다(`next_cursor`). 오프셋 페이징을 쓰면 새 이벤트가 들어오는
 * 동안 페이지 경계가 밀려 같은 이벤트가 두 번 보이거나 빠진다.
 */

import type { EventDetail, EventListResponse, EventStatus, ViolationType } from '../types/system'
import { getJson, queryString, sendJson } from './client'

/** `GET /events` 쿼리(§4.1). 화면이 쓰는 것만 노출한다. */
export type EventQuery = {
  from?: string | null
  to?: string | null
  cam_id?: number | null
  type?: ViolationType | null
  status?: EventStatus | null
  zone_id?: string | null
  limit?: number | null
  cursor?: string | null
}

export async function fetchEvents(
  query: EventQuery = {},
  signal?: AbortSignal,
): Promise<EventListResponse> {
  return getJson<EventListResponse>(`/events${queryString({ ...query })}`, signal)
}

export async function fetchEvent(eventId: string, signal?: AbortSignal): Promise<EventDetail> {
  return getJson<EventDetail>(`/events/${encodeURIComponent(eventId)}`, signal)
}

/**
 * `PATCH /events/{id}` — 오탐 표시 · 강제 종결 · 메모(§4.1 · FN-EVT-05).
 *
 * `Partial` 을 쓴다. 계약 모델은 세 필드를 전부 요구하지만(생성기가 직렬화 기준으로
 * 낸다) **일부만 보내는 것이 이 요청의 용법**이다 — 서버는 `None` 인 필드를 건드리지
 * 않는다. 메모만 고치려는데 `is_false_positive: null` 을 함께 보내야 하는 것은
 * 계약이 아니라 생성기의 부작용이다.
 */
export type EventPatch = {
  is_false_positive?: boolean
  note?: string
  force_resolve?: boolean
}

export async function patchEvent(
  eventId: string,
  patch: EventPatch,
  signal?: AbortSignal,
): Promise<EventDetail | null> {
  return sendJson<EventDetail>('PATCH', `/events/${encodeURIComponent(eventId)}`, patch, signal)
}

/**
 * `GET /events/{id}/clip` 의 URL. 화면은 `<video src>` 로 그대로 쓴다.
 *
 * `clip_url`(`/media/clips/...`)이 아니라 이 경로를 쓰는 이유: `clip_status` 가
 * `pending` 인 동안 서버가 **404 로 없는 것을 없다고** 말해준다(§4.1). 정적 경로로
 * 직접 붙으면 그 구분이 없어 브라우저가 조용히 재생에 실패한다.
 */
export function clipSrc(eventId: string): string {
  return `/api/v1/events/${encodeURIComponent(eventId)}/clip`
}
