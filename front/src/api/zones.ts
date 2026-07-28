/**
 * 금지구역 캐시 (API명세서 §4.5 `GET /zones` + §5.4 `zone_updated`).
 *
 * **폴리곤은 `overlay` 에 실리지 않는다** (§5.1). 매 프레임 변하지 않으므로 한 번
 * 조회해 캐시하고, 설정 화면에서 구역이 바뀌면 `zone_updated` 로 갱신한다.
 * 캘리브레이션이 바뀌면 지면 좌표계가 통째로 바뀌므로 그 카메라의 모든 구역에
 * `upsert` 가 순차로 온다 — 그래서 갱신은 구역 단위 교체다.
 *
 * `upsert` 인데 `polygon_m` 이 없으면 **수신 측에서 거부한다**(§5.4). 반쪽짜리
 * 구역으로 캐시를 덮으면 화면의 금지구역이 조용히 사라진다.
 */

import type { DashboardMessage, Zone } from '../types/system'
import { isZoneUpdatedMsg } from '../types/system'

const API_BASE = '/api/v1'

export async function fetchZones(signal?: AbortSignal): Promise<Zone[]> {
  const response = await fetch(`${API_BASE}/zones`, { signal })
  if (!response.ok) {
    // 빈 배열로 대신하지 않는다 — "구역이 없다"와 "못 읽었다"는 다른 사실이다.
    throw new Error(`GET ${API_BASE}/zones → ${response.status}`)
  }
  return (await response.json()) as Zone[]
}

/** 캐시에 `zone_updated` 하나를 반영한다. 원본 배열은 건드리지 않는다. */
export function applyZoneUpdate(zones: Zone[], message: DashboardMessage): Zone[] {
  if (!isZoneUpdatedMsg(message)) return zones

  const { cam_id, action, zone } = message
  if (action === 'delete') {
    return zones.filter((item) => item.zone_id !== zone.zone_id)
  }

  if (!zone.polygon_m || !zone.name || zone.buffer_m === undefined || zone.active === undefined) {
    console.warn('[zones] polygon_m 없는 upsert 는 캐시를 손상시킨다 — 거부한다', message)
    return zones
  }

  const next: Zone = {
    zone_id: zone.zone_id,
    // `cam_id` 는 메시지 최상위에만 있다(§5.4 — 중복 방지).
    cam_id,
    name: zone.name,
    polygon_m: zone.polygon_m,
    buffer_m: zone.buffer_m,
    active: zone.active,
  }
  const without = zones.filter((item) => item.zone_id !== zone.zone_id)
  return [...without, next]
}
