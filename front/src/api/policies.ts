/**
 * 정책값 조회 (API명세서 §4.5 `GET /policies`).
 *
 * **임계값을 프론트에 적지 않는다** (CLAUDE.md 절대규칙 6). 오버레이 지연 버퍼
 * (`overlay_buffer_webrtc_ms` · `overlay_buffer_hls_ms`)와 `overlay_stale_ms` 는
 * 현장에서 조정되는 값이고, 원본은 DB `policies` 테이블 하나다. 여기 기본값을
 * 적어두면 두 값이 갈라지는 순간 화면은 정상으로 보이는데 정합만 어긋난다 —
 * 그건 눈으로 못 잡는다.
 *
 * 그래서 **읽지 못하면 박스를 그리지 않는다.** "버퍼를 모른 채 대충 그린 박스"는
 * 틀린 위치에 있는 박스이고, 없는 박스보다 나쁘다.
 */

import type { OverlayPolicies } from '../types/system'

const API_BASE = '/api/v1'

/** 실패 시 재시도 간격. 정책값은 자주 변하지 않으므로 급하게 다시 묻지 않는다. */
const RETRY_MS = 5_000

type Listener = (policies: OverlayPolicies | null) => void

let cached: OverlayPolicies | null = null
let inflight: Promise<void> | null = null
const listeners = new Set<Listener>()

async function load(): Promise<void> {
  const response = await fetch(`${API_BASE}/policies`)
  if (!response.ok) {
    throw new Error(`GET ${API_BASE}/policies → ${response.status}`)
  }
  cached = (await response.json()) as OverlayPolicies
  listeners.forEach((listener) => listener(cached))
}

function ensure(): void {
  if (cached || inflight) return
  inflight = load()
    .catch((error: unknown) => {
      // 삼키지 않는다. 오버레이가 안 뜨는 이유가 여기 있을 수 있다.
      console.warn('[policies] 정책값을 읽지 못했다 — 재시도한다:', error)
      window.setTimeout(() => {
        inflight = null
        if (listeners.size > 0) ensure()
      }, RETRY_MS)
    })
    .then(() => {
      if (cached) inflight = null
    })
}

/**
 * 정책값을 구독한다. 이미 받아둔 값이 있으면 즉시 한 번 부른다.
 *
 * 화면마다 따로 부르지 않고 하나를 공유한다 — 두 타일이 서로 다른 버퍼로 그리면
 * 무엇이 맞는지 판단할 근거가 사라진다.
 */
export function subscribePolicies(listener: Listener): () => void {
  listeners.add(listener)
  if (cached) listener(cached)
  ensure()
  return () => {
    listeners.delete(listener)
  }
}
