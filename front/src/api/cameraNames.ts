/**
 * 카메라 표시 이름 — **단일 원천은 `GET /cameras` 의 `name` 이다** (API명세서 §4.5).
 *
 * ★ 전에는 `types/labels.ts` 에 이름 표가 박혀 있었다. 그래서 설정 화면은 DB 이름
 * (「1번 카메라 · 조립 라인」)을, 목록·개요·라이브는 코드의 이름(「카메라 1 · 작업장 A」)을
 * 써서 **같은 카메라가 화면마다 다른 이름으로 보였다.** 설정에서 이름을 바꿔도
 * 반영되지 않았고, 그 사실은 두 화면을 나란히 놓기 전까지 드러나지 않는다.
 * 임계값과 같은 이유로 이름도 코드에 두지 않는다(CLAUDE.md 절대규칙 6).
 *
 * **한 번만 받아 캐시한다.** 카메라 이름은 매 화면 전환마다 변하지 않는다. 화면마다
 * 따로 부르면 같은 응답을 대여섯 번 받게 되고, 그 사이 값이 갈릴 여지도 생긴다 —
 * `subscribeDashboard` 가 소켓 하나를 화면 밖에서 유지하는 것과 같은 이유다.
 *
 * 아직 못 받았으면 `카메라 {id}` 로 그린다(`cameraFallbackName`). 자리를 비우면 화면이
 * 흔들리고, 없는 이름을 지어내면 그것이 진짜 이름처럼 읽힌다.
 */

import { useEffect, useState } from 'react'
import { cameraFallbackName } from '../types/labels'
import { fetchCameras } from './settings'

type Names = Record<number, string>

let cache: Names | null = null
let inflight: Promise<Names> | null = null
const listeners = new Set<(names: Names) => void>()

async function load(): Promise<Names> {
  const cameras = await fetchCameras()
  const names: Names = {}
  for (const camera of cameras) {
    // 이름이 비어 있는 행은 건너뛴다 — 빈 문자열을 이름으로 쓰면 화면에 카메라가
    // 사라진 것처럼 보인다. 그때는 대체값이 그린다.
    if (camera.name) names[camera.cam_id] = camera.name
  }
  cache = names
  for (const listen of listeners) listen(names)
  return names
}

/** 캐시를 버린다. 설정 화면에서 이름을 바꾼 뒤 부른다 — 다음 조회가 새 값을 받는다. */
export function invalidateCameraNames(): void {
  cache = null
  inflight = null
  void ensureCameraNames()
}

function ensureCameraNames(): Promise<Names> {
  if (cache !== null) return Promise.resolve(cache)
  inflight ??= load().catch((reason: unknown) => {
    // 조용히 빈 값으로 두지 않는다 — 이름이 전부 「카메라 1」로 보이는 이유가 여기다.
    console.warn('[cameras] 표시 이름을 읽지 못했다:', reason)
    inflight = null
    return {}
  })
  return inflight
}

/**
 * `cam_id → 표시 이름` 함수. 응답이 오면 다시 그린다.
 *
 * 컴포넌트가 `const name = useCameraName()` 로 받아 `name(camId)` 로 쓴다.
 */
export function useCameraName(): (camId: number) => string {
  const [names, setNames] = useState<Names>(() => cache ?? {})

  useEffect(() => {
    let alive = true
    const listen = (next: Names) => {
      if (alive) setNames(next)
    }
    listeners.add(listen)
    void ensureCameraNames().then(listen)
    return () => {
      alive = false
      listeners.delete(listen)
    }
  }, [])

  return (camId: number) => names[camId] ?? cameraFallbackName(camId)
}
