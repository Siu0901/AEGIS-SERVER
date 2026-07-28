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

export interface CameraStatus {
  cam_id: number
  /** 서버가 보는 메인 스트림 상태. */
  main_state: StreamState
  /** 엣지가 보는 서브 스트림 상태. `heartbeat` 값을 그대로 전달. */
  sub_state: StreamState
  /** 엣지의 실제 처리 fps. **엣지가 붙기 전에는 `null`** — 0 으로 그리지 않는다. */
  fps: number | null
}

export interface EdgeStatus {
  online: boolean
  gpu_util: number
  cls_cache_hit_rate: number
  depth_calls_per_min: number
  /** 스키마 검증에 실패해 거부된 엣지 메시지 누적 (FN-SYS-06). 0이 아니면 경고를 띄운다. */
  msg_rejected_total: number
}

export interface McuStatus {
  online: boolean
  last_seen: string | null
}

export interface CloudStatus {
  available: boolean
  quota_used: number
}

/** REC(§4.7)에서 온 값. 닿지 못하면 `null` — 서버 디스크 값으로 대신 채우지 않는다. */
export interface StorageStatus {
  retention_days: number | null
  free_gb: number | null
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

/**
 * `/ws/dashboard` 로 내려오는 메시지 (§5).
 *
 * M1 에서 실제로 흐르는 것은 `system` 하나다. `overlay` · `event_*` · `metric` 은
 * M2 이후에 붙으므로 지금은 판별만 하고 흘려보낸다.
 */
export type DashboardMessage = SystemMsg | { type: string }

export function isSystemMsg(message: DashboardMessage): message is SystemMsg {
  return message.type === 'system'
}

export function isCameraSystemMsg(message: SystemMsg): message is CameraSystemMsg {
  return message.component === 'camera'
}
