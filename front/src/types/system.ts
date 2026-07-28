/**
 * API명세서 §4.6 (`GET /system/status`) · §5.3 (`system`) 대응 타입.
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
 * `/ws/dashboard` 로 내려오는 메시지 (§5).
 *
 * M1 에서 실제로 흐르는 것은 `system` 하나다. `overlay` · `event_*` · `metric` 은
 * M2 이후에 붙으므로 지금은 판별만 하고 흘려보낸다.
 */
export type DashboardMessage = SystemMsg | EventCreatedMsg | { type: string }

export function isSystemMsg(message: DashboardMessage): message is SystemMsg {
  return message.type === 'system'
}

export function isCameraSystemMsg(message: SystemMsg): message is CameraSystemMsg {
  return message.component === 'camera'
}

export function isEventCreatedMsg(message: DashboardMessage): message is EventCreatedMsg {
  return message.type === 'event_created'
}
