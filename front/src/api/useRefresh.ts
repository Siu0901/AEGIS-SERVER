/**
 * 다시 읽기 요청을 **모아서 한 번만** 보낸다.
 *
 * `/ws/dashboard` 는 한 시나리오에서 `event_updated` 를 여러 번 보내고(확정 · 경고 ·
 * 재경고 · 해소 · 클립 준비), 화면들은 그때마다 목록과 지표를 다시 읽는다. 그대로 두면
 * 전이 하나에 요청이 서너 개씩 붙어 **서버 접근 로그가 그것으로 가득 찬다** — 동작은
 * 하지만 정작 봐야 할 로그를 덮어버려서, 무언가 잘못됐을 때 원인을 찾을 수 없게 된다.
 *
 * 짧은 창 안의 요청을 하나로 접고, **마지막 것을 보낸다**(앞의 것을 보내면 가장 최신
 * 상태를 놓친다). 지연은 사람이 못 느끼는 수준으로 둔다 — 관제 화면에서 상태가 늦게
 * 보이는 것은 이 파일이 해결하려는 문제보다 훨씬 나쁘다.
 */

import { useCallback, useEffect, useRef } from 'react'

/** 기본 병합 창(ms). 한 전이가 만들어내는 메시지들이 이 안에 들어온다. */
export const MERGE_WINDOW_MS = 400

/**
 * `fn` 을 병합해 부르는 함수를 돌려준다. 컴포넌트가 사라지면 예약된 호출도 취소된다.
 *
 * `fn` 은 ref 로 붙들어 매 렌더마다 타이머를 다시 걸지 않는다 — 다시 걸면 갱신이
 * 계속 미뤄져 화면이 영영 낡은 채로 남을 수 있다.
 */
export function useMergedRefresh(fn: () => void, windowMs: number = MERGE_WINDOW_MS): () => void {
  const latest = useRef(fn)
  latest.current = fn
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    return () => window.clearTimeout(timer.current)
  }, [])

  return useCallback(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => latest.current(), windowMs)
  }, [windowMs])
}
