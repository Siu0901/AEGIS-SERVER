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
 * **시연 한정 표기 — `vehicle` 을 「트럭」으로 띄운다.** 미니어처에 트럭과 지게차가
 * 함께 놓이는데 감지 모델은 둘을 구분하지 못한다(클래스가 `vehicle` 하나뿐이다).
 * 화면이 전부 「지게차」라고 말하면 트럭을 가리키고도 지게차라고 하는 셈이라, 모델이
 * 실제로 학습한 대상(`toy_truck`)에 맞춰 표시만 바꿨다. **바뀐 것은 이 표의 문자열뿐이고
 * `violation_type`(`proximity`)·계약 클래스(`vehicle`)·DB·API 는 그대로다** — 명세서
 * 용어는 여전히 「지게차 근접」이므로 문서를 고칠 때 이 문단을 함께 본다.
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
  // ★ 시안은 「중장비 근접」·명세서는 「지게차 근접」이다(부록 B).
  //   화면 표기만 「트럭 근접」이다 — 위 주석 참조.
  proximity: '트럭 근접',
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
 * 카메라 표시 이름의 **대체값**. 진짜 이름은 `GET /cameras` 의 `name` 이다(§4.5).
 *
 * ★ **코드에 이름 표를 두지 않는다**(절대규칙 6). 전에는 여기 `CAMERA_NAMES` 가 박혀
 * 있어서, 설정 화면은 DB 이름(「조립 라인」)을 쓰고 목록·개요·라이브는 코드의 이름
 * (「작업장 A」)을 써 **같은 카메라가 화면마다 다른 이름으로 보였다.** 설정에서 이름을
 * 바꿔도 반영되지 않았다.
 *
 * 이 함수는 목록을 아직 받지 못했을 때만 쓴다 — 자리를 비워 두면 화면이 흔들리고,
 * 없는 이름을 지어내면 그것이 진짜 이름처럼 읽힌다. `카메라 3` 은 둘 다 아니다.
 */
export function cameraFallbackName(camId: number): string {
  return `카메라 ${camId}`
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
 * 그대로 반올림하면 「0일」이 되어 "보존하지 않음"으로 읽힌다 — 실제로 개발 중
 * 사이드바에 「녹화 · 보존 0일」이 떠 있었다. **1일 미만은 시간 단위로 적는다.**
 * 1시간 미만이면 다시 분으로 내려간다.
 */
export function retentionLabel(days: number | null): string {
  if (days === null) return UNMEASURED
  if (days >= 1) return `${Math.round(days)}일`
  const hours = days * 24
  if (hours >= 1) return `${Math.round(hours)}시간`
  return `${Math.max(1, Math.round(hours * 60))}분`
}

/** `37초 만에 시정` 처럼 쓰는 소요 시간. */
export function durationLabel(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${seconds}초`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest === 0 ? `${minutes}분` : `${minutes}분 ${rest}초`
}
