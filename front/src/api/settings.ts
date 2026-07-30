/**
 * 설정 API 클라이언트 (API명세서 §4.5 · FN-CFG-01 ~ 05).
 *
 * **좌표 변환을 여기서 하지 않는다.** 화면에서 그린 폴리곤은 정규화 픽셀 그대로
 * 보내고, 지면 좌표로 바꾸는 것은 서버(`packages/vision`)다 — 호모그래피를 푸는
 * 코드가 두 곳에 있으면 어느 쪽이 맞는지 알 수 없게 된다.
 *
 * `Partial<...Patch>` 를 쓰는 이유: 타입 생성기가 직렬화 모드라 요청 모델도 전부 필수로
 * 나온다(`docs/INDEX.md` M5 절). 부분 갱신은 **보내지 않은 키를 건드리지 않는 것**이
 * 요점이므로 여기서 좁힌다.
 *
 * 예외는 **그리기용 역변환** 하나다. 저장된 구역은 미터로 오므로 영상 위에 그리려면
 * 픽셀로 되돌려야 하는데, 그건 행렬 곱 한 번이지 캘리브레이션이 아니다.
 */

import type {
  AlertSound,
  AlertSoundPatch,
  CalibrationRequest,
  CalibrationResponse,
  CameraCalibration,
  Policies,
  PolicyPatch,
  VehicleClass,
  VehicleClassPatch,
  Zone,
  ZoneUpsertRequest,
} from '../types/contracts'
import { API_BASE, getJson, sendJson } from './client'

export type { AlertSound, CameraCalibration, VehicleClass }

export function fetchCameras(signal?: AbortSignal): Promise<CameraCalibration[]> {
  return getJson<CameraCalibration[]>('/cameras', signal)
}

export function fetchZones(signal?: AbortSignal): Promise<Zone[]> {
  return getJson<Zone[]>('/zones', signal)
}

export function fetchAlertSounds(signal?: AbortSignal): Promise<AlertSound[]> {
  return getJson<AlertSound[]>('/alert-sounds', signal)
}

export function fetchVehicleClasses(signal?: AbortSignal): Promise<VehicleClass[]> {
  return getJson<VehicleClass[]>('/vehicle-classes', signal)
}

export function fetchPolicies(signal?: AbortSignal): Promise<Policies> {
  return getJson<Policies>('/policies', signal)
}

/** FN-CFG-01 — 화면 4점 + 실측값 → 호모그래피. 응답의 재투영 오차를 화면에 띄운다. */
export async function calibrate(
  camId: number,
  body: CalibrationRequest,
): Promise<CalibrationResponse> {
  const response = await sendJson<CalibrationResponse>(
    'POST',
    `/cameras/${camId}/calibration`,
    body,
  )
  if (!response) throw new Error('캘리브레이션 응답이 비어 있다')
  return response
}

/** FN-CFG-02 — 화면에서 그린 폴리곤(정규화 픽셀)을 그대로 보낸다. 변환은 서버가 한다. */
export async function saveZone(body: ZoneUpsertRequest): Promise<Zone> {
  const response = await sendJson<Zone>('POST', '/zones', body)
  if (!response) throw new Error('구역 저장 응답이 비어 있다')
  return response
}

export async function deleteZone(zoneId: string, camId: number): Promise<void> {
  const response = await fetch(`${API_BASE}/zones/${encodeURIComponent(zoneId)}?cam_id=${camId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(body?.error?.message ?? `DELETE /zones/${zoneId} → HTTP ${response.status}`)
  }
}

/** FN-CFG-03 — 음원·등급·표시 이름. `fall` 을 3 미만으로 내리면 서버가 422 로 막는다(§3). */
export async function saveAlertSound(
  violationType: string,
  body: Partial<AlertSoundPatch>,
): Promise<AlertSound> {
  const response = await fetch(`${API_BASE}/alert-sounds/${encodeURIComponent(violationType)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const failure = (await response.json().catch(() => null)) as {
      error?: { message?: string }
    } | null
    throw new Error(failure?.error?.message ?? `PUT /alert-sounds → HTTP ${response.status}`)
  }
  return (await response.json()) as AlertSound
}

/** FN-CFG-04 — 지정한 키만. 응답은 갱신 후 **전량**이라 화면이 옛 값을 되돌려 쓰지 않는다. */
export async function savePolicies(body: Partial<PolicyPatch>): Promise<Policies> {
  const response = await sendJson<Policies>('PATCH', '/policies', body)
  if (!response) throw new Error('정책 저장 응답이 비어 있다')
  return response
}

/** FN-CFG-05 — 클래스별 위험 반경. 지게차 기본 3.0m. */
export async function saveVehicleClass(
  className: string,
  body: Partial<VehicleClassPatch>,
): Promise<VehicleClass> {
  const response = await sendJson<VehicleClass>(
    'PATCH',
    `/vehicle-classes/${encodeURIComponent(className)}`,
    body,
  )
  if (!response) throw new Error('위험 반경 저장 응답이 비어 있다')
  return response
}

/**
 * 지면 좌표 → 정규화 픽셀. **저장된 구역을 영상 위에 다시 그릴 때만 쓴다.**
 *
 * 호모그래피의 역행렬을 곱하는 것이 전부다 — 4점으로 행렬을 **푸는** 일(DLT)은
 * 서버에만 있다. `w` 가 0에 가까우면 그 점은 지평선 위라 화면에 대응하는 곳이 없으므로
 * `null` 을 돌려준다. 큰 수를 그리면 캔버스 어딘가에 엉뚱한 선이 생긴다.
 */
export function groundToPixel(
  homography: number[][],
  point: [number, number],
): [number, number] | null {
  const inverse = invert3(homography)
  if (!inverse) return null
  const [x, y] = point
  const w = inverse[2][0] * x + inverse[2][1] * y + inverse[2][2]
  if (Math.abs(w) < 1e-9) return null
  return [
    (inverse[0][0] * x + inverse[0][1] * y + inverse[0][2]) / w,
    (inverse[1][0] * x + inverse[1][1] * y + inverse[1][2]) / w,
  ]
}

function invert3(m: number[][]): number[][] | null {
  const [[a, b, c], [d, e, f], [g, h, i]] = m as [
    [number, number, number],
    [number, number, number],
    [number, number, number],
  ]
  const det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
  if (Math.abs(det) < 1e-15) return null
  return [
    [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
    [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
    [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det],
  ]
}
