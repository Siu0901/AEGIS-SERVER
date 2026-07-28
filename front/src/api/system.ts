/**
 * 시스템 상태 구독 (API명세서 §4.6 + §5.3).
 *
 * 규약은 §5.3 에 적힌 그대로다.
 *
 *   1. `GET /system/status` 로 **전체 스냅샷**을 한 번 받는다
 *   2. `/ws/dashboard` 의 `system` 은 **변화한 구성요소 하나**만 오므로 캐시를 갱신한다
 *
 * WebSocket 만으로 화면을 그리려 하면 접속 전에 일어난 변화를 영영 모르고, 반대로
 * 폴링만 하면 카메라가 끊긴 것을 늦게 안다. 둘을 같이 쓰는 이유다.
 */

import type { DashboardMessage, StreamState, SystemStatus } from '../types/system'
import { isCameraSystemMsg, isSystemMsg } from '../types/system'

const API_BASE = '/api/v1'
const WS_PATH = '/ws/dashboard'

export async function fetchSystemStatus(signal?: AbortSignal): Promise<SystemStatus> {
  const response = await fetch(`${API_BASE}/system/status`, { signal })
  if (!response.ok) {
    throw new Error(`GET ${API_BASE}/system/status → ${response.status}`)
  }
  return (await response.json()) as SystemStatus
}

/** 캐시된 스냅샷에 `system` 메시지 하나를 반영한다. 원본은 건드리지 않는다. */
export function applySystemMsg(status: SystemStatus, message: DashboardMessage): SystemStatus {
  if (!isSystemMsg(message) || !isCameraSystemMsg(message)) {
    return status
  }
  const key = message.stream === 'main' ? 'main_state' : 'sub_state'
  const cameras = status.cameras.map((camera) =>
    camera.cam_id === message.cam_id
      ? { ...camera, [key]: message.state as StreamState }
      : camera,
  )
  return { ...status, cameras }
}

export type DashboardHandlers = {
  onMessage: (message: DashboardMessage) => void
  onOpen?: () => void
  onClose?: () => void
}

/**
 * `/ws/dashboard` 에 붙고, 끊기면 지수 백오프로 다시 붙는다.
 *
 * 재연결을 넣지 않으면 서버를 한 번 재시작한 뒤로 대시보드가 **조용히 멈춘 화면**을
 * 계속 보여준다. 그 상태는 "아무 일도 없음"과 구분되지 않아서 가장 위험하다.
 */
export function connectDashboard(handlers: DashboardHandlers): () => void {
  let socket: WebSocket | null = null
  let retryMs = 500
  let timer: number | undefined
  let closed = false

  const open = () => {
    if (closed) return
    const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${WS_PATH}`
    socket = new WebSocket(url)

    socket.onopen = () => {
      retryMs = 500
      handlers.onOpen?.()
    }
    socket.onmessage = (event) => {
      try {
        handlers.onMessage(JSON.parse(event.data as string) as DashboardMessage)
      } catch {
        // 계약(§5)에 없는 메시지다. 화면을 죽이지 않되 삼키지도 않는다.
        console.warn('[ws] 해석할 수 없는 메시지', event.data)
      }
    }
    socket.onclose = () => {
      handlers.onClose?.()
      if (closed) return
      timer = window.setTimeout(open, retryMs)
      retryMs = Math.min(retryMs * 2, 10_000)
    }
    socket.onerror = () => socket?.close()
  }

  open()

  return () => {
    closed = true
    window.clearTimeout(timer)
    socket?.close()
  }
}
