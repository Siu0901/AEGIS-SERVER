/**
 * 계약 타입의 **화면용 얇은 층** — 생성물 재수출 + 판별 함수 + 표시 헬퍼.
 *
 * 타입 정의는 여기 없다. 원본은 `packages/contracts` 이고 그것이
 * `contracts.ts` 로 생성된다(`uv run tasks.py types` · CLAUDE.md 절대규칙 5).
 * M5 까지는 §4.6 · §5.3 을 **손으로 옮겨** 두었고, 그 사본은 계약이 넓어져도 아무도
 * 잡아주지 않았다 — 이제 `verify` 가 재생성해 대조한다.
 *
 * 여기 남는 것은 **생성할 수 없는 것들**뿐이다.
 *
 *   · 런타임 판별 함수 (`isOverlayMsg` 등) — JSON Schema 에는 없다
 *   · 표시 규약 (`formatRate` · `RATE_UNAVAILABLE`) — 명세서 §6.7 의 `–` 규칙
 *   · 화면이 쓰는 이름 별칭 (`OverlayPolicies` 등)
 */

import type {
  AnomalyMsg,
  CameraSystemMsg,
  ComponentSystemMsg,
  EventCreatedMsg,
  EventUpdatedMsg,
  MetricMsg,
  MetricsSummary,
  OverlayMsg,
  OverlayPerson,
  OverlayVehicle,
  Policies,
  ZoneUpdatedMsg,
} from './contracts'

export type {
  AlertLevel,
  AlertState,
  AnomalyMsg,
  CameraStatus,
  CameraSystemMsg,
  ClipStatus,
  CloudStatus,
  ComponentSystemMsg,
  EdgeStatus,
  EventCreatedMsg,
  EventDetail,
  EventListResponse,
  EventStatus,
  EventSummary,
  EventUpdatedMsg,
  HelmetState,
  ManualAlertRequest,
  ManualAlertResponse,
  McuStatus,
  MetricMsg,
  MetricsSummary,
  MuteAlertRequest,
  MuteAlertResponse,
  NearbySnapshot,
  NonCameraComponent,
  OverlayMsg,
  OverlayNearby,
  OverlayPerson,
  OverlayVehicle,
  Policies,
  Posture,
  RegulationRef,
  SimilarIncident,
  StorageStatus,
  StreamKind,
  StreamState,
  SystemStatus,
  TimeSyncStatus,
  TimelineEntry,
  ViolationType,
  Zone,
  ZoneUpdatedMsg,
} from './contracts'

/** §5.3 `system` — 카메라 스트림과 그 밖의 구성요소는 값 집합이 다르다(§4.6). */
export type SystemMsg = CameraSystemMsg | ComponentSystemMsg

/**
 * §5.1 `overlay.objects[]` 의 한 항목.
 *
 * 파이썬 쪽에서도 모델이 아니라 합집합 별칭이라 생성물에 이름이 남지 않는다.
 * **박스는 `person` 과 `vehicle` 에만 그린다** — 안전모는 별도 박스가 없고 사람
 * 박스의 색과 라벨로 표현한다(기능명세서 §4.6 표시 규칙).
 */
export type OverlayObject = OverlayPerson | OverlayVehicle

/**
 * `/ws/dashboard` 로 내려오는 메시지 전량(§5).
 *
 * 마지막 갈래(`{ type: string }`)를 남겨 둔다 — 계약이 새 메시지를 추가했을 때
 * 화면이 죽지 않고 무시할 수 있어야 한다. 그 대신 **판별 함수를 통과하지 못하므로**
 * 조용히 잘못된 필드를 읽는 일은 생기지 않는다.
 */
export type DashboardMessage =
  | SystemMsg
  | EventCreatedMsg
  | EventUpdatedMsg
  | MetricMsg
  | AnomalyMsg
  | OverlayMsg
  | ZoneUpdatedMsg
  | { type: string }

/**
 * 오버레이가 쓰는 정책값만 골라낸 것(§4.5).
 *
 * **값을 여기 적지 않는다** — 원본은 DB `policies` 테이블이고 서버가 그대로 내려준다
 * (CLAUDE.md 절대규칙 6).
 */
export type OverlayPolicies = Pick<
  Policies,
  'overlay_buffer_webrtc_ms' | 'overlay_buffer_hls_ms' | 'overlay_stale_ms'
>

export function isSystemMsg(message: DashboardMessage): message is SystemMsg {
  return message.type === 'system'
}

export function isCameraSystemMsg(message: SystemMsg): message is CameraSystemMsg {
  return message.component === 'camera'
}

export function isEventCreatedMsg(message: DashboardMessage): message is EventCreatedMsg {
  return message.type === 'event_created'
}

export function isEventUpdatedMsg(message: DashboardMessage): message is EventUpdatedMsg {
  return message.type === 'event_updated'
}

export function isMetricMsg(message: DashboardMessage): message is MetricMsg {
  return message.type === 'metric'
}

export function isOverlayMsg(message: DashboardMessage): message is OverlayMsg {
  return message.type === 'overlay'
}

export function isZoneUpdatedMsg(message: DashboardMessage): message is ZoneUpdatedMsg {
  return message.type === 'zone_updated'
}

// ---------------------------------------------------------------------------
// 표시 규약
// ---------------------------------------------------------------------------

/** 비율이 `null`(모집단 없음)일 때 화면에 찍는 글자. 0% 와 같아 보이면 안 된다. */
export const RATE_UNAVAILABLE = '–'

/** 관측 주체가 없어 값이 `null` 인 자리(§4.6). **0 과 다르게 그린다.** */
export const UNMEASURED = '측정 불가'

/**
 * 비율 지표를 화면 문자열로 (§6.7).
 *
 * `null` 은 **`–`** 다. `0%` 로 접으면 판정 불가만 있던 구간이 "아무도 시정하지
 * 않았다"로 읽히는데, 두 상황은 대응이 정반대다.
 *
 * 시정률은 판정 불가율과 **항상 병기**한다 — `방송 후 시정률 87% (판정 불가 5%)`.
 * 그 병기 형식을 만드는 것이 `formatRatePair` 다.
 */
export function formatRate(value: number | null): string {
  return value === null ? RATE_UNAVAILABLE : `${Math.round(value * 100)}%`
}

/**
 * §4.8 · §6.7 「표기 규칙」 — 지표를 단독으로 제시하지 않는다.
 *
 * 판정 불가율은 그 자체로 설치 품질 지표이기도 하지만, 여기서 병기하는 이유는
 * **시정률이 무엇을 세지 않았는지**를 같은 자리에서 보여주기 위해서다.
 */
export function formatRatePair(correction: number | null, undetermined: number | null): string {
  return `${formatRate(correction)} (판정 불가 ${formatRate(undetermined)})`
}

/**
 * 지표 응답의 검산 — 네 버킷의 합이 `total_violations` 인가(§4.2).
 *
 * 화면이 서버가 보낸 비율을 검산 없이 믿지 않게 하려고 §5.3 이 `resolved_late` 를
 * 실어 보낸다. 어긋나면 개요 화면이 그 사실을 표시한다 — 숫자가 맞지 않는 지표를
 * 그대로 보여주는 것이 이 프로젝트에서 가장 하면 안 되는 일이다.
 *
 * **`suppressed` 는 합에 넣지 않는다.** 방송이 없었던 건은 모집단이 아니라 별도
 * 집계이므로 `total_violations` 밖에 있다(§4.8).
 */
export function metricsAddUp(summary: MetricsSummary | MetricMsg): boolean {
  const denominator = summary.resolved + summary.resolved_late + summary.unresolved
  return denominator + summary.undetermined === summary.total_violations
}
