/**
 * 시스템 상태 하나를 앱 전체가 공유한다 (API명세서 §4.6 + §5.3).
 *
 * 사이드바와 실시간 관제가 각자 폴링하면 같은 순간에 서로 다른 상태를 표시하게 된다.
 * 어느 쪽이 맞는지 알 수 없는 화면은 상태 표시가 없는 화면보다 나쁘다.
 */

import { useEffect, useState } from 'react'
import type { SystemStatus } from '../types/system'
import { applySystemMsg, connectDashboard, fetchSystemStatus } from './system'

export type SystemStatusView = {
  status: SystemStatus | null
  /** `/ws/dashboard` 연결 여부. 끊겨 있으면 화면의 상태가 낡았을 수 있다. */
  connected: boolean
  error: string | null
}

export function useSystemStatus(): SystemStatusView {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()

    const load = () => {
      fetchSystemStatus(controller.signal)
        .then((next) => {
          setStatus(next)
          setError(null)
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return
          setError(cause instanceof Error ? cause.message : String(cause))
        })
    }

    load()

    const disconnect = connectDashboard({
      // 재접속했다면 그 사이의 변화를 놓쳤다. 스냅샷을 다시 받는다(§5.3).
      onOpen: () => {
        setConnected(true)
        load()
      },
      onClose: () => setConnected(false),
      onMessage: (message) => {
        setStatus((current) => (current ? applySystemMsg(current, message) : current))
      },
    })

    return () => {
      controller.abort()
      disconnect()
    }
  }, [])

  return { status, connected, error }
}
