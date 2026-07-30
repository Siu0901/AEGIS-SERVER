/**
 * 오버레이 지연 버퍼와 트랙별 보간 (API명세서 §5 「오버레이 시간 정합」 · FN-UI-02).
 *
 * 여기서 잠그는 것은 **±100ms 정합이 성립하기 위한 계산**이다. 화면에서 박스가 사람보다
 * 앞서 가는지는 눈으로 보면 알 수 있지만, 왜 그런지(부호가 뒤집혔는가 · 보간이
 * 어긋났는가 · 낡은 좌표를 그대로 그렸는가)는 눈으로 구분할 수 없다.
 *
 * M2 에서는 이 성질들을 스크래치에서 `tsc` 로 컴파일해 node 로 돌려 확인했다.
 * 그 검증은 다음 사람이 반복할 수 없었다.
 */

import { describe, expect, it } from 'vitest'
import type { OverlayMsg, OverlayPerson, OverlayVehicle } from '../types/system'
import { OverlayBuffer, targetTimestamp } from './overlayBuffer'

const T0 = Date.parse('2026-08-14T05:37:00.000Z')

function person(trackId: number, x: number): OverlayPerson {
  return {
    class: 'person',
    track_id: trackId,
    bbox: [x, 0.3, x + 0.08, 0.76],
    foot_point: [x + 0.04, 0.76],
    posture: 'standing',
    in_zone: 'forklift_lane',
    helmet: 'off',
    violations: ['no_helmet'],
    event_ids: ['EV-20260814-0231'],
    alert_state: 'alerted',
    nearby: [],
  }
}

function vehicle(trackId: number, x: number): OverlayVehicle {
  return {
    class: 'vehicle',
    track_id: trackId,
    bbox: [x, 0.38, x + 0.24, 0.75],
    anchor: [x + 0.12, 0.75],
    moving: true,
    danger_radius_m: 3.0,
    violations: [],
    event_ids: [],
    alert_state: null,
    nearby: [],
  }
}

function frame(offsetMs: number, objects: OverlayMsg['objects']): OverlayMsg {
  return {
    type: 'overlay',
    cam_id: 1,
    ts: new Date(T0 + offsetMs).toISOString(),
    objects,
  }
}

describe('targetTimestamp', () => {
  it('버퍼를 뺀다 — 화면에 나가는 프레임은 그만큼 과거에 촬영됐다', () => {
    // 부호를 뒤집으면 박스가 지연의 **두 배**만큼 앞서 간다. 그 화면은
    // "정합이 조금 어긋났다"가 아니라 아예 다른 순간을 그리는 것이다.
    expect(targetTimestamp(T0, 300)).toBe(T0 - 300)
    expect(targetTimestamp(T0, 2800)).toBe(T0 - 2800)
  })
})

describe('OverlayBuffer.sample', () => {
  it('좌표가 없으면 null 이다 — 빈 배열이 아니다', () => {
    // "객체가 없다"(빈 배열)와 "아직 좌표를 받지 못했다"(null)는 화면에서 다르게
    // 다뤄야 한다. 후자는 오버레이를 그리지 않고 대기 표시를 낸다.
    const buffer = new OverlayBuffer()
    expect(buffer.sample(T0)).toBeNull()
  })

  it('가진 좌표보다 과거를 물으면 null 이다', () => {
    const buffer = new OverlayBuffer()
    buffer.push(frame(1000, [person(3, 0.2)]))
    expect(buffer.sample(T0 + 500)).toBeNull()
  })

  it('두 프레임 사이를 선형 보간한다 (박스 떨림 제거)', () => {
    const buffer = new OverlayBuffer()
    buffer.push(frame(0, [person(3, 0.2)]))
    buffer.push(frame(1000, [person(3, 0.4)]))

    const sample = buffer.sample(T0 + 250)
    expect(sample).not.toBeNull()
    expect(sample?.fraction).toBeCloseTo(0.25, 6)
    const drawn = sample?.objects[0] as OverlayPerson
    expect(drawn.bbox[0]).toBeCloseTo(0.25, 6)
    expect(drawn.foot_point[0]).toBeCloseTo(0.29, 6)
    // 보간은 **좌표만** 한다. 판정 값을 섞으면 클라이언트가 판정을 만들어내는 셈이다.
    expect(drawn.violations).toEqual(['no_helmet'])
    expect(drawn.alert_state).toBe('alerted')
  })

  it('양쪽에 모두 있는 트랙만 섞는다 — 없는 위치를 지어내지 않는다', () => {
    const buffer = new OverlayBuffer()
    buffer.push(frame(0, [person(3, 0.2), person(7, 0.6)]))
    buffer.push(frame(1000, [person(3, 0.4)]))

    const sample = buffer.sample(T0 + 500)
    const ids = sample?.objects.map((object) => object.track_id)
    // 7번은 다음 프레임에 없다. 그대로 남되 위치는 옛 값이다(퇴장은 그 프레임에서).
    expect(ids).toEqual([3, 7])
    const seven = sample?.objects[1] as OverlayPerson
    expect(seven.bbox[0]).toBeCloseTo(0.6, 6)
  })

  it('트랙 번호는 클래스별로만 유일하다 — person #3 과 vehicle #3 은 다른 대상이다', () => {
    const buffer = new OverlayBuffer()
    buffer.push(frame(0, [person(3, 0.2), vehicle(3, 0.7)]))
    buffer.push(frame(1000, [person(3, 0.4), vehicle(3, 0.5)]))

    const sample = buffer.sample(T0 + 500)
    const drawnPerson = sample?.objects[0] as OverlayPerson
    const drawnVehicle = sample?.objects[1] as OverlayVehicle
    expect(drawnPerson.bbox[0]).toBeCloseTo(0.3, 6)
    // 클래스를 무시하고 섞였다면 0.3 으로 끌려갔을 것이다.
    expect(drawnVehicle.bbox[0]).toBeCloseTo(0.6, 6)
    expect(drawnVehicle.anchor[0]).toBeCloseTo(0.72, 6)
  })

  it('가진 좌표보다 미래면 마지막 값을 유지하고 낡음을 알린다 (§5 5번)', () => {
    const buffer = new OverlayBuffer()
    buffer.push(frame(0, [person(3, 0.2)]))

    const sample = buffer.sample(T0 + 1500)
    // `overlay_stale_ms`(기본 1000) 와 비교할 값이 `ageMs` 다. 0 으로 내면 화면은
    // 1.5초 전 좌표를 최신인 것처럼 진하게 그린다.
    expect(sample?.ageMs).toBe(1500)
    expect(sample?.objects).toHaveLength(1)
  })

  it('순서가 뒤집혀 도착해도 제자리에 끼운다', () => {
    const buffer = new OverlayBuffer()
    buffer.push(frame(1000, [person(3, 0.4)]))
    buffer.push(frame(0, [person(3, 0.2)]))

    const sample = buffer.sample(T0 + 500)
    expect(sample?.fraction).toBeCloseTo(0.5, 6)
    expect((sample?.objects[0] as OverlayPerson).bbox[0]).toBeCloseTo(0.3, 6)
  })

  it('ts 를 해석할 수 없는 메시지는 버린다 — 지금 그리지 않는다', () => {
    const buffer = new OverlayBuffer()
    buffer.push({ ...frame(0, [person(3, 0.2)]), ts: '언제인지 모르겠다' })
    expect(buffer.size).toBe(0)
    expect(buffer.newestAt).toBeNull()
  })

  it('오래된 프레임을 버려도 재생 위치의 좌표는 남는다', () => {
    const buffer = new OverlayBuffer()
    for (let index = 0; index < 200; index += 1) {
      buffer.push(frame(index * 125, [person(3, 0.001 * index)]))
    }
    const sample = buffer.sample(T0 + 199 * 125)
    expect(sample).not.toBeNull()
    // 4초치 여유(EXTRA_HISTORY_MS)만 남으므로 200프레임(25초)이 그대로 쌓이지 않는다.
    expect(buffer.size).toBeLessThan(200)
  })
})
