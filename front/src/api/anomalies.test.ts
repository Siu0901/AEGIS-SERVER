/**
 * 이상 탐지 목록 병합 (FN-AI-04).
 *
 * ★ **여기가 클라우드 없이 잠글 수 있는 유일한 지점이다.** 이상 탐지 자체는 임베딩이
 * 필요해 API 키 없이는 돌지 않지만, 「두 경로로 들어온 같은 플래그를 어떻게 합치는가」는
 * 순수 함수라 지금 검증할 수 있다. 그 판단이 틀리면 같은 이상이 두 줄로 보이거나
 * 새로고침한 화면이 텅 빈다.
 */

import { describe, expect, it } from 'vitest'
import { anomalyTone, mergeAnomalies, toItem } from './anomalies'
import type { AnomalyItem, AnomalyMsg } from '../types/contracts'

function item(id: number, at: string, score = 0.42): AnomalyItem {
  return { anomaly_id: id, cam_id: 1, score, detected_at: at, note: null, keyframe_url: null }
}

describe('mergeAnomalies', () => {
  it('최신 순으로 정렬한다', () => {
    const merged = mergeAnomalies(
      [item(1, '2026-08-14T01:00:00Z')],
      [item(2, '2026-08-14T03:00:00Z'), item(3, '2026-08-14T02:00:00Z')],
    )
    expect(merged.map((row) => row.anomaly_id)).toEqual([2, 3, 1])
  })

  it('★ 같은 플래그가 두 경로로 와도 한 줄이다', () => {
    // 화면을 연 직후, 조회 응답이 오는 사이에 발행된 메시지가 같은 것을 나른다.
    // 두 줄로 보이면 사람은 두 번 일어난 일로 읽는다.
    const merged = mergeAnomalies(
      [item(7, '2026-08-14T01:00:00Z')],
      [item(7, '2026-08-14T01:00:00Z')],
    )
    expect(merged).toHaveLength(1)
  })

  it('★ 나중에 온 것이 이긴다 — 설명이 뒤늦게 붙을 수 있다', () => {
    const withNote: AnomalyItem = { ...item(7, '2026-08-14T01:00:00Z'), note: '조명이 꺼져 있다' }
    const merged = mergeAnomalies([item(7, '2026-08-14T01:00:00Z')], [withNote])
    expect(merged[0].note).toBe('조명이 꺼져 있다')
  })

  it('상한을 넘으면 오래된 것부터 버린다', () => {
    const many = Array.from({ length: 5 }, (_, index) =>
      item(index, `2026-08-14T0${index}:00:00Z`),
    )
    const merged = mergeAnomalies([], many, 3)
    expect(merged.map((row) => row.anomaly_id)).toEqual([4, 3, 2])
  })

  it('빈 입력에도 터지지 않는다', () => {
    expect(mergeAnomalies([], [])).toEqual([])
  })
})

describe('toItem', () => {
  it('§5.3 메시지에서 type 만 떼면 목록 항목이다', () => {
    const message: AnomalyMsg = {
      type: 'anomaly',
      anomaly_id: 91,
      cam_id: 2,
      score: 0.71,
      detected_at: '2026-08-14T02:14:00Z',
      note: '평소와 다른 상황',
      keyframe_url: null,
    }
    expect(toItem(message)).toEqual({
      anomaly_id: 91,
      cam_id: 2,
      score: 0.71,
      detected_at: '2026-08-14T02:14:00Z',
      note: '평소와 다른 상황',
      keyframe_url: null,
    })
  })
})

describe('anomalyTone', () => {
  it('★ 위험색을 쓰지 않는다 — 이상은 위반이 아니다', () => {
    // 점수는 「평소와 얼마나 다른가」이지 「얼마나 위험한가」가 아니다.
    // 위반과 같은 적색으로 그리면 사람이 둘을 같은 신뢰도로 읽는다(FN-AI-04).
    expect(anomalyTone(0.99)).toBe('warn')
    expect(anomalyTone(0.2)).toBe('muted')
  })
})
