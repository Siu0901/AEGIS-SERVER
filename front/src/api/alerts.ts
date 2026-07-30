/**
 * 수동 방송과 경고 일시중지 (API명세서 §4.5 · FN-ALM-04 · FN-ALM-05).
 *
 * **일시중지 상태를 조회할 수 있다는 것이 핵심이다.** 응답이 없던 시절에는 새로고침
 * 한 번에 "경고가 꺼져 있다"는 사실이 화면에서 사라졌다. 꺼둔 것을 잊는 순간 감시가
 * 조용히 멎으므로 그 상태는 오탐보다 위험하다.
 */

import type { ManualAlertResponse, MuteAlertResponse } from '../types/system'
import type { AlertLevel } from '../types/contracts'
import { getJson, queryString, sendJson } from './client'

/**
 * `POST /alerts/manual` (§4.5).
 *
 * `sound` 를 생략하면 서버가 기본 안내 음원을 고른다 — **파일명을 프론트가 알지
 * 못하게** 하려는 것이다(절대규칙 6). `notify_device` 가 참이면 `level` 로 경광등도 켠다.
 */
export async function postManualAlert(
  input: { cam_id: number; sound?: string | null; level: AlertLevel; notify_device: boolean },
  signal?: AbortSignal,
): Promise<ManualAlertResponse | null> {
  return sendJson<ManualAlertResponse>(
    'POST',
    '/alerts/manual',
    { sound: null, ...input },
    signal,
  )
}

/**
 * `POST /alerts/mute` (§4.5).
 *
 * `minutes: 0` 은 즉시 해제다. `minutes` 를 `null` 로 두면 서버가 정책값
 * (`mute_default_duration_s`)을 붙인다 — 기한 없는 중지는 만들 수 없다.
 * `cam_id: null` 은 전체 카메라 대상이다.
 */
export async function postMute(
  input: { cam_id: number | null; minutes: number | null; reason: string },
  signal?: AbortSignal,
): Promise<MuteAlertResponse | null> {
  return sendJson<MuteAlertResponse>('POST', '/alerts/mute', input, signal)
}

/**
 * `GET /alerts/mute` (§4.5) — `POST` 와 같은 형태를 돌려준다.
 *
 * `cam_id` 를 주면 **그 카메라에 실제로 걸리는** 창을 본다. 전체 대상 중지가 켜져
 * 있으면 카메라별 창이 없어도 조용하므로, 화면이 "이 카메라는 안 멈췄다"고 표시하면
 * 안 되는 상황이 그것이다.
 */
export async function fetchMuteState(
  camId: number | null,
  signal?: AbortSignal,
): Promise<MuteAlertResponse> {
  return getJson<MuteAlertResponse>(`/alerts/mute${queryString({ cam_id: camId })}`, signal)
}
