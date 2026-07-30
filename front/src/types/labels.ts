/**
 * 계약 열거형 → 화면 표기. **기능명세서 부록 B 대조표를 따른다.**
 *
 * 시안(`docs/AEGIS_front_design.pdf`)은 건설현장 시절에 작성되어 라벨이 낡았다.
 * 레이아웃·정보구조·색상은 시안을 따르되 **텍스트와 도메인 용어는 명세서**다.
 *
 * | 시안 | 실제 구현 |
 * |---|---|
 * | 굴착기 | 지게차 (`vehicle`) |
 * | 굴착 구역 | 지게차 통행로 (`forklift_lane`) |
 * | 중장비 근접 | **지게차 근접** (`proximity`) |
 *
 * 한 곳에 모아 두는 이유: 같은 값에 화면마다 다른 이름을 붙이면 시연 중에 관제
 * 화면과 이벤트 화면이 서로 다른 위반을 말하는 것처럼 보인다.
 */

import type { ClipStatus, EventStatus, ViolationType } from './contracts'
import { UNMEASURED } from './system'

/** 위반 유형 4종(§2.2 · §4.1). `person`/`vehicle` 2클래스와는 다른 축이다. */
export const VIOLATION_LABEL: Record<ViolationType, string> = {
  no_helmet: '안전모 미착용',
  zone_intrusion: '금지구역 침입',
  // ★ 시안의 「중장비 근접」이 아니다(부록 B).
  proximity: '지게차 근접',
  fall: '쓰러짐',
}

/** 상태머신 값(기능명세서 §4.2). 사람이 읽는 짧은 이름. */
export const STATUS_LABEL: Record<EventStatus, string> = {
  candidate: '확정 중',
  active: '확정',
  alerted: '경고 방송',
  re_alerted: '재경고',
  lost: '추적 끊김',
  resolved: '시정됨',
  // 「미시정」이 아니다 — 시정 여부를 관측하지 못한 것이다(§6.7).
  expired: '판정 불가',
  dropped: '확정 전 소멸',
}

/**
 * 상태별 색 계열. `resolved` 만 정상(청록)이고 진행 중은 위험(적색) 쪽이다.
 *
 * `expired` · `dropped` 를 위험색으로 그리지 않는다 — 둘은 위반이 계속되고 있다는
 * 뜻이 아니라 판정을 못 했다는 뜻이다.
 */
export const STATUS_TONE: Record<EventStatus, 'ok' | 'warn' | 'danger' | 'muted'> = {
  candidate: 'warn',
  active: 'warn',
  alerted: 'danger',
  re_alerted: 'danger',
  lost: 'warn',
  resolved: 'ok',
  expired: 'muted',
  dropped: 'muted',
}

/** FN-REC-03 클립 예약 상태(§6 `events.clip_status`). */
export const CLIP_STATUS_LABEL: Record<ClipStatus, string> = {
  pending: '추출 대기',
  ready: '준비됨',
  failed: '추출 실패',
}

/**
 * 카메라 표시 이름. 실제 설치 위치명은 M6 설정 화면(FN-CFG)에서 관리한다.
 *
 * 시안의 「자재 야적장」·「굴착 구역」이 아니라 제조현장 이름을 쓴다(부록 B).
 */
export const CAMERA_NAMES: Record<number, string> = {
  1: '카메라 1 · 작업장 A',
  2: '카메라 2 · 지게차 통행로',
}

export function cameraName(camId: number): string {
  return CAMERA_NAMES[camId] ?? `카메라 ${camId}`
}

export function violationLabel(value: string): string {
  return VIOLATION_LABEL[value as ViolationType] ?? value
}

export function statusLabel(value: string): string {
  return STATUS_LABEL[value as EventStatus] ?? value
}

/** `2026-08-14T05:37:03Z` → `14:37:03`. 저장은 UTC, **표시만 로컬**이다(§1.2). */
export function clockTime(value: string | null): string {
  if (!value) return '—'
  const at = new Date(value)
  return Number.isNaN(at.getTime()) ? value : at.toLocaleTimeString()
}

/** 날짜까지 필요한 자리(이벤트 상세 · 저장소 최고 시각). */
export function stamp(value: string | null): string {
  if (!value) return '—'
  const at = new Date(value)
  return Number.isNaN(at.getTime()) ? value : at.toLocaleString()
}

/** `방금` · `2분 전` · `11분 전`. 시안 1·2페이지의 상대 시각 표기다. */
export function relativeTime(value: string | null, now: number = Date.now()): string {
  if (!value) return '—'
  const at = new Date(value).getTime()
  if (Number.isNaN(at)) return value
  const seconds = Math.max(0, Math.round((now - at) / 1000))
  if (seconds < 30) return '방금'
  if (seconds < 3600) return `${Math.round(seconds / 60)}분 전`
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}시간 전`
  return `${Math.round(seconds / 86_400)}일 전`
}

/**
 * 보존 기간(일). **개발 환경은 1시간(`REC_RETENTION_DAYS=0.0417`)으로 낮춰 쓴다.**
 *
 * 그대로 반올림하면 「0일」이 되어 "보존하지 않음"으로 읽힌다. 운용 값(7일)과
 * 개발 값이 화면에서 구분되어야 하므로 1일 미만을 따로 적는다.
 */
export function retentionLabel(days: number | null): string {
  if (days === null) return UNMEASURED
  return days < 1 ? '1일 미만' : `${Math.round(days)}일`
}

/** `37초 만에 시정` 처럼 쓰는 소요 시간. */
export function durationLabel(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${seconds}초`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest === 0 ? `${minutes}분` : `${minutes}분 ${rest}초`
}
