/**
 * API명세서 §4.6 (`GET /system/status`) · §5.1 (`overlay`) · §5.3 (`system`) ·
 * §5.4 (`zone_updated`) · §4.5 (`zones` · `policies`) 대응 타입.
 *
 * **손으로 옮긴 임시 정의다.** 스키마의 원본은 `packages/contracts` 하나이며
 * (CLAUDE.md 절대규칙 5), M5 의 `uv run tasks.py types` 가 여기를 생성물로 대체한다.
 * 그때까지는 필드를 **필요한 만큼만** 옮겨 두고, 명세서에 없는 필드를 만들지 않는다.
 */

/** 카메라 **스트림** 상태. `ComponentState` 와 통합하지 않는다 (§4.6). */
export type StreamState = 'ok' | 'reconnecting' | 'down'

/** 카메라 외 구성요소 상태. */
export type ComponentState = 'ok' | 'degraded' | 'down'

/** `main` = 1920×1080 라이브·녹화(서버 관측) / `sub` = 640×360 추론(엣지 관측). */
export type StreamKind = 'main' | 'sub'

export type NonCameraComponent = 'edge' | 'mcu' | 'cloud_api' | 'storage' | 'db'

/**
 * **관측 주체가 없으면 `null` 이다** (§4.6 「관측 주체가 없을 때는 null 을 쓴다」).
 *
 * `0` 은 "관측했더니 0이었다"는 주장이라 실제 장애와 구분되지 않는다. 화면은 `null` 을
 * **"측정 불가"로, `0` 과 다르게** 그린다. 예외는 두 가지뿐이다 — 서버가 직접 세는
 * `edge.msg_rejected_total`(0 시작)과, "모름"이라는 값이 없는 `sub_state`(`down`).
 */
export interface CameraStatus {
  cam_id: number
  /** 서버가 보는 메인 스트림 상태. */
  main_state: StreamState
  /** 엣지가 보는 서브 스트림 상태. `heartbeat` 값을 그대로 전달. */
  sub_state: StreamState
  /** 엣지의 실제 처리 fps. **엣지가 붙기 전에는 `null`** — 0 으로 그리지 않는다. */
  fps: number | null
  /**
   * REC(§4.7)이 이 카메라를 녹화 중인지. **REC 값을 그대로 쓴다.**
   *
   * 라이브가 보인다고 녹화 중인 것이 아니다 — 둘은 다른 프로세스다. 추론으로 그리면
   * REC 이 그 카메라만 놓쳤을 때 화면은 계속 녹화 중이라고 말한다.
   * REC 미도달이면 `null`("알 수 없다") 이며 `false`("녹화 안 함")와 다르다.
   */
  recording: boolean | null
}

export interface EdgeStatus {
  online: boolean
  gpu_util: number | null
  cls_cache_hit_rate: number | null
  depth_calls_per_min: number | null
  /**
   * 스키마 검증에 실패해 거부된 엣지 메시지 누적 (FN-SYS-06). 0이 아니면 경고를 띄운다.
   * **여기만 `null` 이 아니다** — 서버가 직접 세므로 관측 주체가 항상 있다.
   */
  msg_rejected_total: number
}

export interface McuStatus {
  online: boolean
  last_seen: string | null
}

export interface CloudStatus {
  available: boolean
  quota_used: number | null
}

/**
 * REC(§4.7) `GET /status` 의 `storage` 절을 **5필드 그대로** 전달받은 값.
 * 닿지 못하면 전부 `null` — 서버 디스크 값으로 대신 채우지 않는다.
 */
export interface StorageStatus {
  total_gb: number | null
  used_gb: number | null
  free_gb: number | null
  retention_days: number | null
  /** 보존된 가장 오래된 세그먼트 시각. **영상 검색 가능 범위의 하한이다.** */
  oldest_segment_at: string | null
}

export interface TimeSyncStatus {
  edge_offset_ms: number | null
}

export interface SystemStatus {
  edge: EdgeStatus
  cameras: CameraStatus[]
  mcu: McuStatus
  cloud: CloudStatus
  storage: StorageStatus
  time_sync: TimeSyncStatus
}

/** §5.3 — `component === 'camera'` 면 `cam_id` 와 `stream` 이 필수다. */
export interface CameraSystemMsg {
  type: 'system'
  component: 'camera'
  cam_id: number
  stream: StreamKind
  state: StreamState
  detail: string
  at: string
}

export interface ComponentSystemMsg {
  type: 'system'
  component: NonCameraComponent
  state: ComponentState
  detail: string
  at: string
}

export type SystemMsg = CameraSystemMsg | ComponentSystemMsg

/** §3 `AlertCommand.level` 과 동일한 척도이며 같은 값을 쓴다 (§5.2). */
export type AlertLevel = 1 | 2 | 3

/** §5.2 — 신규 확정 이벤트. 필요한 필드만 옮겼다(`uv run tasks.py types` 가 대체한다). */
export interface EventCreatedMsg {
  type: 'event_created'
  event_id: string
  cam_id: number
  violation_type: string
  severity: AlertLevel
  confirmed_at: string
}

/**
 * §5.3 `metric` — 종결이 일어나 지표가 바뀌었다.
 *
 * **`correction_rate` 와 `undetermined_rate` 는 `null` 이 될 수 있다** (§6.7).
 * 분모(해소 + 늦은 시정 + 미시정)가 0이면 서버가 `null` 을 보낸다. `0` 으로 그리면
 * "시정률 0%"라는 주장이 되는데, 실제로는 "판정 가능한 이벤트가 없다"는 뜻이다.
 * 화면은 `formatRate` 로 `–` 를 찍고 **0% 와 다르게** 그린다.
 *
 * `resolved` · `resolved_late` · `unresolved` 는 서로 배타적이고, 셋에 `undetermined`
 * 를 더하면 `total_violations` 다. 화면은 이 검산이 성립하는지 볼 수 있다.
 */
export interface MetricMsg {
  type: 'metric'
  period: string
  correction_rate: number | null
  undetermined_rate: number | null
  total_violations: number
  resolved: number
  /** 해소됐으나 `resolve_window_s` 초과. **분모에만** 들어간다 (§6.7). */
  resolved_late: number
  unresolved: number
  undetermined: number
  avg_resolution_sec: number
  fall_events: number
  anomaly_flags: number
}

/**
 * `/ws/dashboard` 로 내려오는 메시지 (§5).
 *
 * M2 에서 흐르는 것은 `system` 과 `overlay` 다. `event_*` 와 `metric` 은 확정 판정과
 * 지표 집계가 생기는 M3 부터 흐른다(표시는 개요 화면 FN-UI-01 · M5).
 */
export type DashboardMessage =
  | SystemMsg
  | EventCreatedMsg
  | MetricMsg
  | OverlayMsg
  | ZoneUpdatedMsg
  | { type: string }

export function isSystemMsg(message: DashboardMessage): message is SystemMsg {
  return message.type === 'system'
}

export function isCameraSystemMsg(message: SystemMsg): message is CameraSystemMsg {
  return message.component === 'camera'
}

export function isEventCreatedMsg(message: DashboardMessage): message is EventCreatedMsg {
  return message.type === 'event_created'
}

export function isMetricMsg(message: DashboardMessage): message is MetricMsg {
  return message.type === 'metric'
}

/** 비율이 `null`(모집단 없음)일 때 화면에 찍는 글자. 0% 와 같아 보이면 안 된다. */
export const RATE_UNAVAILABLE = '–'

/**
 * 비율 지표를 화면 문자열로 (§6.7).
 *
 * `null` 은 **`–`** 다. `0%` 로 접으면 판정 불가만 있던 구간이 "아무도 시정하지
 * 않았다"로 읽히는데, 두 상황은 대응이 정반대다.
 *
 * 시정률은 판정 불가율과 **항상 병기**한다 — `방송 후 시정률 87% (판정 불가 5%)`.
 */
export function formatRate(value: number | null): string {
  return value === null ? RATE_UNAVAILABLE : `${Math.round(value * 100)}%`
}

// ---------------------------------------------------------------------------
// §5.1 overlay · §5.4 zone_updated · §4.5 zones · policies
// ---------------------------------------------------------------------------

/** 위반 유형. `person`/`vehicle` 2클래스와 달리 이쪽은 4종이다 (§2.2 · §4.1). */
export type ViolationType = 'no_helmet' | 'zone_intrusion' | 'proximity' | 'fall'

/**
 * 오버레이 박스의 경고 단계 (§5.1).
 *
 * **`candidate` 와 `null` 은 다르다.** `candidate` 는 위반 조건이 관측됐으나 아직
 * 확정 전이고, `null` 은 이 트랙에 진행 중 이벤트가 아예 없다는 뜻이다. 대시보드는
 * `candidate` 를 **위반 색(적색)으로 그리지 않는다** — 확정 전이므로 위반으로 단정할
 * 수 없다. 다만 확정 진행 중임은 구분 가능하게 표시한다.
 */
export type AlertState = 'candidate' | 'active' | 'alerted' | 're_alerted' | 'lost'

/** 2단계 분류 결과. `unknown` 은 존재하지 않는다 (§6.3). */
export type HelmetState = 'on' | 'off'

export type Posture = 'standing' | 'fallen' | 'unknown'

/** 거리선의 반대편 끝점과 라벨 (§5.1 `objects[].nearby[]`). */
export interface OverlayNearby {
  class: 'vehicle'
  track_id: number
  /** 사람↔차량 지면 거리. **거리 라벨의 원천이다.** */
  dist_m: number
  /** 상대 차량의 **정규화** 접지 좌표. */
  anchor: [number, number]
  in_danger_zone: boolean
}

interface OverlayCommon {
  track_id: number
  /** **`[x1, y1, x2, y2]`** 좌상단·우하단 정규화 좌표 (§1.2). `[x, y, w, h]` 가 아니다. */
  bbox: [number, number, number, number]
  /**
   * 현재 이 트랙에 걸려 있는 위반. **박스 색을 결정한다.**
   * `helmet` 값으로 유추하지 마라 — `proximity` · `fall` 을 놓친다.
   */
  violations: ViolationType[]
  event_ids: string[]
  alert_state: AlertState | null
  nearby: OverlayNearby[]
}

export interface OverlayPerson extends OverlayCommon {
  class: 'person'
  /** 엣지가 마스크에서 계산한 접지점 (§6.1). */
  foot_point: [number, number]
  posture: Posture
  /** 구역 밖이면 `null`. 필드 자체는 항상 실린다. */
  in_zone: string | null
  /** 게이트 미통과 · 캐시 없음이면 **필드가 아예 없다** (§2.1 · §6.3). */
  helmet?: HelmetState
}

export interface OverlayVehicle extends OverlayCommon {
  class: 'vehicle'
  /** **정규화** 접지 좌표. `frame` 의 `anchor_m`(미터)과 다르다. */
  anchor: [number, number]
  moving: boolean
  danger_radius_m: number
}

export type OverlayObject = OverlayPerson | OverlayVehicle

export interface OverlayMsg {
  type: 'overlay'
  cam_id: number
  /** **원본 프레임 시각.** 시간 정합의 기준이다 — 도착 시각으로 대신하면 안 된다. */
  ts: string
  objects: OverlayObject[]
}

/** `GET /zones` 응답 원소 (§4.5). */
export interface Zone {
  zone_id: string
  cam_id: number
  name: string
  /** **지면 실좌표(m)** 꼭짓점. 화면 픽셀이 아니다. */
  polygon_m: [number, number][]
  buffer_m: number
  active: boolean
}

/** `zone_updated.zone` — `GET /zones` 원소에서 `cam_id` 를 뺀 형태 (§5.4). */
export type ZonePayload = Omit<Zone, 'cam_id'>

export interface ZoneUpdatedMsg {
  type: 'zone_updated'
  cam_id: number
  action: 'upsert' | 'delete'
  zone: Partial<ZonePayload> & { zone_id: string }
}

/**
 * `GET /policies` 중 오버레이가 쓰는 것만 (§4.5).
 *
 * **값을 여기 적지 않는다** — 정책값의 원본은 DB `policies` 테이블이고
 * 서버가 그대로 내려준다 (CLAUDE.md 절대규칙 6).
 */
export interface OverlayPolicies {
  overlay_buffer_webrtc_ms: number
  overlay_buffer_hls_ms: number
  overlay_stale_ms: number
}

export function isOverlayMsg(message: DashboardMessage): message is OverlayMsg {
  return message.type === 'overlay'
}

export function isZoneUpdatedMsg(message: DashboardMessage): message is ZoneUpdatedMsg {
  return message.type === 'zone_updated'
}
