/**
 * 지표 표시 규약 (API명세서 §6.7 · 기능명세서 §4.8).
 *
 * 여기서 잠그는 것은 **`null` 과 `0` 이 화면에서 다르게 보이는가**다. 이 프로젝트의
 * 유일한 차별점이 「방송 후 시정률」이고, 그 숫자가 "0%"로 보이느냐 "판정할 수 없음"으로
 * 보이느냐는 현장 대응이 정반대인 두 상황을 가른다.
 */

import { describe, expect, it } from 'vitest'
import type { MetricsSummary } from './contracts'
import { RATE_UNAVAILABLE, formatRate, formatRatePair, metricsAddUp } from './system'

describe('formatRate', () => {
  it('null 은 0% 가 아니라 – 다 (§6.7)', () => {
    // 분모가 0이면 서버가 `null` 을 보낸다. `0%` 로 접으면 "판정 가능한 이벤트가
    // 없다"가 "아무도 시정하지 않았다"로 읽힌다.
    expect(formatRate(null)).toBe(RATE_UNAVAILABLE)
    expect(formatRate(0)).toBe('0%')
    expect(formatRate(null)).not.toBe(formatRate(0))
  })

  it('비율을 퍼센트 정수로 반올림한다', () => {
    expect(formatRate(0.87)).toBe('87%')
    expect(formatRate(1)).toBe('100%')
    expect(formatRate(0.005)).toBe('1%')
    expect(formatRate(0.004)).toBe('0%')
  })
})

describe('formatRatePair', () => {
  it('시정률과 판정 불가율을 항상 병기한다 (§4.8 표기 규칙)', () => {
    expect(formatRatePair(0.87, 0.05)).toBe('87% (판정 불가 5%)')
  })

  it('한쪽만 null 이어도 두 숫자가 모두 자리를 지킨다', () => {
    // 판정 불가만 있는 구간이 이 모양이다. 시정률 자리가 비면 화면에서 지표가
    // 사라진 것처럼 보이므로 `–` 를 찍어 "판정할 수 없었다"를 드러낸다.
    expect(formatRatePair(null, 1)).toBe('– (판정 불가 100%)')
    expect(formatRatePair(1, null)).toBe('100% (판정 불가 –)')
  })
})

describe('metricsAddUp', () => {
  const base: MetricsSummary = {
    period: 'today',
    correction_rate: 0.87,
    undetermined_rate: 0.05,
    total_violations: 24,
    resolved: 20,
    resolved_late: 1,
    unresolved: 2,
    undetermined: 1,
    suppressed: 0,
    avg_resolution_sec: 41,
    fall_events: 0,
    anomaly_flags: 1,
  }

  it('네 버킷의 합이 total_violations 면 참이다 (§4.2 예시)', () => {
    expect(metricsAddUp(base)).toBe(true)
  })

  it('한 건이 사라지면 거짓이다 — 화면이 그 사실을 표시할 수 있어야 한다', () => {
    expect(metricsAddUp({ ...base, total_violations: 23 })).toBe(false)
  })

  it('suppressed 는 합에 들어가지 않는다 (§4.8 별도 집계)', () => {
    // 방송이 없었던 건은 모집단이 아니다. `total_violations` 에 더해지면 분모가
    // 다시 오염되므로, 늘어나도 검산은 그대로 성립해야 한다.
    expect(metricsAddUp({ ...base, suppressed: 7 })).toBe(true)
  })
})
