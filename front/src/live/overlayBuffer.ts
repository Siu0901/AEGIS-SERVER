/**
 * 오버레이 지연 버퍼와 트랙별 보간 (API명세서 §5 「오버레이 시간 정합」 · FN-UI-02).
 *
 * **도착 즉시 그리지 않는다.** 영상은 1080p 메인 → 서버 재스트리밍 → 브라우저
 * 디코드를 거치고, 좌표는 640p 서브 → 엣지 → 서버 → WebSocket 을 거친다. 두 경로의
 * 지연이 다르므로 도착한 순간 그리면 박스가 사람보다 앞서 움직인다. NTP 동기화는
 * "같은 시계를 본다"는 보장일 뿐 도착 시점을 맞춰주지 않는다.
 *
 * 절차는 §5 그대로다.
 *
 *   1. 수신한 `overlay` 를 `ts` 키로 버퍼에 적재
 *   2. 재생 중인 프레임의 표시 시각 `t_video` 를 구한다
 *      (`requestVideoFrameCallback` 의 `expectedDisplayTime`)
 *   3. **`t_video − buffer`** 시각의 좌표를 꺼낸다. 그 프레임이 카메라에서 찍힌 시각이
 *      곧 그만큼 과거이기 때문이다. 정확히 맞는 항목이 없으면 앞뒤를 선형 보간한다
 *   4. `buffer` 는 재생 경로별로 다르다 — `overlay_buffer_webrtc_ms`(400) ·
 *      `overlay_buffer_hls_ms`(2800). M1 실측이 0.3초 대 2.5초라 단일 값으로는 못 맞춘다
 *   5. `overlay_stale_ms`(1000) 이상 갱신이 없으면 흐리게 표시한다
 *
 * 정합 오차 목표는 **±100ms**다.
 */

import type { OverlayMsg, OverlayNearby, OverlayObject } from '../types/system'

/** 버퍼가 붙들고 있는 최대 시간(ms). 지연 버퍼 위에 얹는 여유다. */
const EXTRA_HISTORY_MS = 4_000

/** 한 카메라가 붙들 수 있는 최대 프레임 수. 시계가 어긋나도 메모리가 새지 않게 한다. */
const MAX_FRAMES = 600

export type Sample = {
  objects: OverlayObject[]
  /** 마지막 좌표가 얼마나 낡았는가(ms). `overlay_stale_ms` 초과면 흐리게 그린다. */
  ageMs: number
  /** 보간에 쓴 두 프레임 사이의 위치 0~1. 진단용. */
  fraction: number
}

type Entry = { at: number; message: OverlayMsg }

/**
 * 카메라 한 대의 오버레이 지연 버퍼.
 *
 * 시각은 전부 **epoch ms**로 다룬다. `overlay.ts` 는 UTC 문자열이고 영상 표시 시각은
 * `performance.timeOrigin + expectedDisplayTime` 이라 둘 다 벽시계로 환산해야 뺄 수 있다.
 */
export class OverlayBuffer {
  private entries: Entry[] = []

  /** 마지막으로 **수신**한 시각. 도착이 끊긴 것을 재생 위치와 무관하게 알기 위한 값. */
  private lastArrivalAt: number | null = null

  push(message: OverlayMsg): void {
    const at = Date.parse(message.ts)
    if (Number.isNaN(at)) {
      // `ts` 없이는 어느 프레임에 그릴지 정할 수 없다. 조용히 지금 그리면 안 된다.
      console.warn('[overlay] ts 를 해석할 수 없어 버린다', message.ts)
      return
    }
    this.lastArrivalAt = at
    // 거의 항상 뒤에 붙는다. 순서가 뒤집혀 오면 제자리에 끼운다.
    this.entries.splice(this.lastIndexAtOrBefore(at) + 1, 0, { at, message })
    if (this.entries.length > MAX_FRAMES) this.entries.splice(0, this.entries.length - MAX_FRAMES)
  }

  get newestAt(): number | null {
    return this.lastArrivalAt
  }

  get size(): number {
    return this.entries.length
  }

  clear(): void {
    this.entries = []
    this.lastArrivalAt = null
  }

  /**
   * `targetAt`(= 재생 중인 프레임의 촬영 시각) 에 그릴 좌표를 꺼낸다.
   *
   * @returns 그릴 것이 없으면 `null`. **빈 배열이 아니다** — "객체가 없다"와
   *   "아직 좌표가 없다"는 화면에서 다르게 다뤄야 한다.
   */
  sample(targetAt: number): Sample | null {
    this.trim(targetAt)
    if (this.entries.length === 0) return null

    const first = this.entries[0]
    const last = this.entries[this.entries.length - 1]

    // 재생 위치가 가진 좌표보다 과거다. 아직 그 시각의 좌표를 받은 적이 없다.
    if (targetAt < first.at) return null

    // 재생 위치가 가진 좌표보다 미래다. 마지막 좌표를 유지하되 낡음을 알린다(§5 5번).
    if (targetAt >= last.at) {
      return { objects: last.message.objects, ageMs: targetAt - last.at, fraction: 1 }
    }

    const index = this.lastIndexAtOrBefore(targetAt)
    const before = this.entries[index]
    const after = this.entries[index + 1]
    const span = after.at - before.at
    const fraction = span > 0 ? (targetAt - before.at) / span : 0
    return {
      objects: interpolate(before.message.objects, after.message.objects, fraction),
      ageMs: 0,
      fraction,
    }
  }

  /** `at` 이하인 마지막 항목의 인덱스. 없으면 -1. (`findLastIndex` 는 ES2023 이다.) */
  private lastIndexAtOrBefore(at: number): number {
    for (let index = this.entries.length - 1; index >= 0; index -= 1) {
      if (this.entries[index].at <= at) return index
    }
    return -1
  }

  private trim(targetAt: number): void {
    const cutoff = targetAt - EXTRA_HISTORY_MS
    let keep = 0
    while (keep + 1 < this.entries.length && this.entries[keep + 1].at < cutoff) keep += 1
    if (keep > 0) this.entries.splice(0, keep)
  }
}

/**
 * 재생 시각에서 좌표 시각을 얻는다.
 *
 * 화면에 나가는 프레임은 `bufferMs` 만큼 **과거에 촬영된** 것이다. 그래서 빼는 것이지
 * 더하는 것이 아니다 — 부호를 뒤집으면 박스가 지연의 두 배만큼 앞서 간다.
 */
export function targetTimestamp(displayAtMs: number, bufferMs: number): number {
  return displayAtMs - bufferMs
}

/**
 * 트랙별 선형 보간. 양쪽에 **모두 있는 트랙만** 섞는다.
 *
 * 프레임 간 박스 떨림을 없애기 위한 것이며(FN-UI-02 표), 없는 트랙의 위치를 지어내지는
 * 않는다. 등장·퇴장은 그 프레임에서 그대로 일어난다.
 */
function interpolate(
  before: OverlayObject[],
  after: OverlayObject[],
  fraction: number,
): OverlayObject[] {
  const later = new Map(after.map((object) => [key(object), object]))
  return before.map((object) => {
    const next = later.get(key(object))
    if (!next) return object
    if (object.class === 'person' && next.class === 'person') {
      return {
        ...object,
        bbox: lerp4(object.bbox, next.bbox, fraction),
        foot_point: lerp2(object.foot_point, next.foot_point, fraction),
        nearby: lerpNearby(object.nearby, next.nearby, fraction),
      }
    }
    if (object.class === 'vehicle' && next.class === 'vehicle') {
      return {
        ...object,
        bbox: lerp4(object.bbox, next.bbox, fraction),
        anchor: lerp2(object.anchor, next.anchor, fraction),
      }
    }
    return object
  })
}

function lerpNearby(
  before: OverlayNearby[],
  after: OverlayNearby[],
  fraction: number,
): OverlayNearby[] {
  const later = new Map(after.map((item) => [item.track_id, item]))
  return before.map((item) => {
    const next = later.get(item.track_id)
    if (!next) return item
    return {
      ...item,
      dist_m: item.dist_m + (next.dist_m - item.dist_m) * fraction,
      anchor: lerp2(item.anchor, next.anchor, fraction),
    }
  })
}

/** 트랙 번호는 클래스별로만 유일하다 — `person #3` 과 `vehicle #3` 은 다른 대상이다. */
function key(object: OverlayObject): string {
  return `${object.class}:${object.track_id}`
}

function lerp2(a: [number, number], b: [number, number], t: number): [number, number] {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}

function lerp4(
  a: [number, number, number, number],
  b: [number, number, number, number],
  t: number,
): [number, number, number, number] {
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
    a[3] + (b[3] - a[3]) * t,
  ]
}
