/**
 * REST 호출의 공통 부분 (API명세서 §1.1 Base URL · §1.4 오류 봉투).
 *
 * **오류를 삼키지 않는다.** 서버는 실패를 `{"error": {"code", "message", "detail"}}`
 * 로 내려주므로(§1.4) 그 `message` 를 그대로 올려보낸다. `Error: 500` 만 남기면
 * 화면에 "실패했다"는 사실만 뜨고 왜 실패했는지가 사라진다 — 시연 중에 그걸 알아내려면
 * 서버 로그를 뒤져야 한다.
 */

import type { ErrorResponse } from '../types/contracts'

export const API_BASE = '/api/v1'

/** §1.4 봉투를 읽어 사람이 볼 문장으로. 봉투가 아니면 상태 코드만이라도 남긴다. */
async function describe(response: Response, path: string): Promise<string> {
  try {
    const body = (await response.json()) as Partial<ErrorResponse>
    if (body.error?.message) {
      return `${body.error.code}: ${body.error.message}`
    }
  } catch {
    // JSON 이 아니다(프록시 오류 페이지 등). 상태 코드로 대신한다.
  }
  return `${path} → HTTP ${response.status}`
}

/** GET 하나. `AbortSignal` 을 받아 화면이 사라질 때 취소할 수 있게 한다. */
export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal })
  if (!response.ok) throw new Error(await describe(response, path))
  return (await response.json()) as T
}

/** 본문이 있는 요청(POST · PATCH). 응답이 비어 있으면 `null` 을 돌려준다. */
export async function sendJson<T>(
  method: 'POST' | 'PATCH',
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T | null> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) throw new Error(await describe(response, path))
  if (response.status === 204) return null
  const text = await response.text()
  return text ? (JSON.parse(text) as T) : null
}

/** 쿼리 문자열. `null` · `undefined` · 빈 문자열은 아예 싣지 않는다. */
export function queryString(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}
