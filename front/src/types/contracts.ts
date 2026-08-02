/**
 * 자동 생성 파일 — 손으로 고치지 마라.
 *
 *     uv run tasks.py types
 *
 * 원본은 `packages/contracts` 이고 그 원본은 `docs/AEGIS_API명세서.md` 다
 * (CLAUDE.md 절대규칙 5). 이 파일을 고치면 다음 생성에서 지워진다.
 *
 * `uv run tasks.py verify` 가 재생성해 이 파일과 대조하므로, 계약이 바뀌었는데
 * 여기가 낡아 있으면 검증이 실패한다.
 *
 * 각 타입의 주석은 계약 모델 docstring 의 **첫 단락**이다. 전문은 파이썬 쪽에 있다.
 */

/* eslint-disable */

export type AlertLevel = 1 | 2 | 3

export type AlertState = 'candidate' | 'active' | 'alerted' | 're_alerted' | 'lost'

export type AttachmentKind = 'clip' | 'image' | 'table' | 'event_ref'

export type ChatRoute = 'sql' | 'vector' | 'vision'

export type ClipExtractStatus = 'ready' | 'partial' | 'not_found'

export type ClipStatus = 'pending' | 'ready' | 'failed'

export type ComponentState = 'ok' | 'degraded' | 'down'

export type DistanceMethod = 'bbox_center' | 'mask_nearest'

export type DistributionBy = 'violation_type' | 'zone' | 'camera' | 'hour_of_day'

export type HelmetState = 'on' | 'off'

export type MetricBucket = 'hour' | 'day' | 'week'

export type MetricName = 'violations' | 'correction_rate' | 'avg_resolution_sec' | 'undetermined_rate'

export type NearbyBasis = 'mask_nearest' | 'anchor'

export type NonCameraComponent = 'edge' | 'mcu' | 'cloud_api' | 'storage' | 'db'

export type ObjectClass = 'person' | 'vehicle'

export type Posture = 'standing' | 'fallen' | 'unknown'

export type RepeatSubject = 'zone' | 'camera' | 'track'

export type SearchMode = 'sql' | 'vector' | 'hybrid'

export type StreamKind = 'main' | 'sub'

export type StreamState = 'ok' | 'reconnecting' | 'down'

export type SystemComponent = 'edge' | 'camera' | 'mcu' | 'cloud_api' | 'storage' | 'db'

export type TrackLostReason = 'occluded' | 'out_of_view' | 'low_conf'

export type ZoneAction = 'upsert' | 'delete'

/**
 * `aegis/alert` 페이로드. API명세서 §3
 */
export interface AlertCommand {
  event_id: string
  type: ViolationType | 'manual'
  level: 1 | 2 | 3
  zone_id: string | null
  duration_s: number
  repeat: boolean
}

/**
 * 경고 음원 매핑 한 줄. `GET /alert-sounds`. API명세서 §4.5 · 기능명세서 §6
 */
export interface AlertSound {
  violation_type: string
  file_path: string
  level: 1 | 2 | 3
  label: string | null
  active: boolean
}

/**
 * `PUT /alert-sounds/{violation_type}` 요청. API명세서 §4.5
 */
export interface AlertSoundPatch {
  file_path: string | null
  level: 1 | 2 | 3 | null
  label: string | null
  active: boolean | null
}

/**
 * 이상 탐지 플래그 하나. `GET /anomalies`
 */
export interface AnomalyItem {
  anomaly_id: number
  cam_id: number
  score: number
  detected_at: string
  note: string | null
  keyframe_url: string | null
}

/**
 * `GET /anomalies` 응답.
 */
export interface AnomalyListResponse {
  items: AnomalyItem[]
}

/**
 * `anomaly` — 이상 탐지 플래그. API명세서 §5.3
 */
export interface AnomalyMsg {
  type: 'anomaly'
  anomaly_id: number
  cam_id: number
  score: number
  detected_at: string
  note: string | null
  keyframe_url: string | null
}

/**
 * `POST /assistant/briefing` 요청. API명세서 §4.4
 */
export interface BriefingRequest {
  cam_ids: number[]
}

/**
 * `POST /assistant/briefing` 응답. API명세서 §4.4
 */
export interface BriefingResponse {
  summary: string
  captured_at: string
}

/**
 * 지면 캘리브레이션 대응점 1쌍. API명세서 §4.5
 */
export interface CalibrationPoint {
  px: [number, number]
  m: [number, number]
}

/**
 * `POST /cameras/{cam_id}/calibration` 요청. API명세서 §4.5
 */
export interface CalibrationRequest {
  points: CalibrationPoint[]
  reference_person: ReferencePerson | null
}

/**
 * `POST /cameras/{cam_id}/calibration` 응답. API명세서 §4.5
 */
export interface CalibrationResponse {
  homography: number[][]
  reprojection_error_m: number
  ref_height_calibrated: boolean
}

/**
 * 카메라 한 대의 설정과 저장된 캘리브레이션. `GET /cameras`. API명세서 §4.5
 */
export interface CameraCalibration {
  cam_id: number
  name: string
  rtsp_main: string
  rtsp_sub: string
  homography: number[][] | null
  calib_points: CalibrationPoint[] | null
  reproj_error_m: number | null
  ref_height: RefHeight | null
  calibrated_at: string | null
}

/**
 * `heartbeat.cameras[]` 원소 — 카메라별 상태. API명세서 §2.4
 */
export interface CameraHealth {
  cam_id: number
  sub_state: 'ok' | 'reconnecting' | 'down'
  fps: number
}

/**
 * `PATCH /cameras/{cam_id}` 요청. API명세서 §4.5
 */
export interface CameraPatch {
  name: string | null
  rtsp_main: string | null
  rtsp_sub: string | null
}

/**
 * 카메라 스트림 상태. API명세서 §4.6
 */
export interface CameraStatus {
  cam_id: number
  main_state: 'ok' | 'reconnecting' | 'down'
  sub_state: 'ok' | 'reconnecting' | 'down'
  fps: number | null
  recording: boolean | null
}

/**
 * `system` — 카메라 **스트림** 상태 변화. API명세서 §5.3
 */
export interface CameraSystemMsg {
  type: 'system'
  component: 'camera'
  cam_id: number
  stream: 'main' | 'sub'
  state: 'ok' | 'reconnecting' | 'down'
  detail: string
  at: string
}

/**
 * `candidate` — 이벤트 후보. API명세서 §2.2
 */
export interface CandidateMsg {
  type: 'candidate'
  cam_id: number
  ts: string
  track_id: number
  violation_type: ViolationType
  bbox: [number, number, number, number]
  conf: number
  foot_point_m: [number, number]
  observed_ms: number
  zone_id: string | null
  foot_conf: number | null
  helmet: 'on' | 'off' | null
  helmet_conf: number | null
  posture: 'standing' | 'fallen' | 'unknown' | null
  nearby: NearbyVehicle[]
}

/**
 * `POST /assistant/chat` 요청. API명세서 §4.4
 */
export interface ChatRequest {
  session_id: string
  message: string
}

/**
 * `POST /assistant/chat` 응답. API명세서 §4.4
 */
export interface ChatResponse {
  route: 'sql' | 'vector' | 'vision'
  answer: string
  attachments: (ClipAttachment | ImageAttachment | TableAttachment | EventRefAttachment)[]
  sources: ChatSource[]
}

/**
 * 챗봇 응답 근거. API명세서 §4.4
 */
export interface ChatSource {
  type: string
  detail: string
}

/**
 * `attachments[]` 의 클립 첨부. API명세서 §4.4
 */
export interface ClipAttachment {
  kind: 'clip'
  event_id: string
  clip_url: string
  thumbnail_url: string
  label: string
}

/**
 * `POST /clips` 요청. API명세서 §4.7
 */
export interface ClipRequest {
  cam_id: number
  from: string
  to: string
  event_id: string
}

/**
 * `POST /clips` 응답. API명세서 §4.7
 */
export interface ClipResponse {
  status: 'ready' | 'partial' | 'not_found'
  size_bytes: number | null
  download_url: string | null
  actual_from: string | null
  actual_to: string | null
  reason: string | null
}

/**
 * 클라우드 상태. API명세서 §4.6
 */
export interface CloudStatus {
  available: boolean
  quota_used: number | null
}

/**
 * `system` — 카메라 외 구성요소 상태 변화. API명세서 §5.3
 */
export interface ComponentSystemMsg {
  type: 'system'
  component: 'edge' | 'mcu' | 'cloud_api' | 'storage' | 'db'
  state: 'ok' | 'degraded' | 'down'
  detail: string
  at: string
}

/**
 * `frame` 메시지의 person 객체. API명세서 §2.1
 */
export interface DetectedPerson {
  class: 'person'
  track_id: number
  conf: number
  bbox: [number, number, number, number]
  helmet: 'on' | 'off' | null
  helmet_conf: number | null
  helmet_checked_at: string | null
  foot_point: [number, number]
  foot_point_m: [number, number]
  foot_conf: number
  posture: 'standing' | 'fallen' | 'unknown'
  height_ratio: number
  axis_angle_deg: number
  stillness_s: number
  in_zone: string | null
  nearby: FrameNearby[]
}

/**
 * `frame` 메시지의 vehicle(지게차) 객체. API명세서 §2.1
 */
export interface DetectedVehicle {
  class: 'vehicle'
  track_id: number
  conf: number
  bbox: [number, number, number, number]
  anchor: [number, number]
  anchor_m: [number, number]
  moving: boolean
  danger_radius_m: number
}

/**
 * `aegis/device/status` 페이로드. API명세서 §3
 */
export interface DeviceStatus {
  device: string
  online: boolean
  uptime_s: number
  last_alert: string | null
}

/**
 * `GET /metrics/distribution` 의 한 구간. API명세서 §4.2
 */
export interface DistributionBucket {
  key: string
  label: string
  count: number
  ratio: number
}

/**
 * `heartbeat.clock` — 엣지가 **자체 NTP 로 잰** 자기 시계 오차. API명세서 §2.4
 */
export interface EdgeClock {
  offset_ms: number
  synced: boolean
  source: string | null
  last_sync_at: string | null
}

/**
 * 엣지 상태. API명세서 §4.6
 */
export interface EdgeStatus {
  online: boolean
  gpu_util: number | null
  cls_cache_hit_rate: number | null
  depth_calls_per_min: number | null
  msg_rejected_total: number
}

/**
 * 오류 본문. API명세서 §1.4
 */
export interface ErrorBody {
  code: 'VALIDATION_ERROR' | 'NOT_FOUND' | 'EDGE_OFFLINE' | 'CLOUD_UNAVAILABLE' | 'QUOTA_EXCEEDED'
  message: string
  detail: Record<string, unknown> | null
}

/**
 * 오류 응답 봉투. API명세서 §1.4
 */
export interface ErrorResponse {
  error: ErrorBody
}

/**
 * `event_created` — 신규 확정 이벤트. API명세서 §5.2
 */
export interface EventCreatedMsg {
  type: 'event_created'
  event_id: string
  cam_id: number
  violation_type: ViolationType
  track_id: number
  zone_id: string | null
  status: EventStatus
  confirmed_at: string
  alerted_at: string | null
  severity: 1 | 2 | 3
  keyframe_url: string | null
}

/**
 * `GET /events/{event_id}`. 목록 필드에 아래가 추가된다. API명세서 §4.1
 */
export interface EventDetail {
  event_id: string
  cam_id: number
  track_id: number
  violation_type: ViolationType
  zone_id: string | null
  status: EventStatus
  detected_at: string
  confirmed_at: string | null
  alerted_at: string | null
  last_alerted_at: string | null
  note: string | null
  resolved_at: string | null
  resolution_sec: number | null
  alert_count: number
  min_distance_m: number | null
  posture: 'standing' | 'fallen' | 'unknown' | null
  repeat_count_7d: number
  thumbnail_url: string | null
  clip_url: string | null
  keyframe_urls: string[]
  helmet_conf: number | null
  stillness_s: number | null
  height_ratio: number | null
  depth_verified: boolean | null
  nearby_snapshot: NearbySnapshot[]
  llm_analysis: string | null
  regulation_refs: RegulationRef[]
  similar_incidents: SimilarIncident[]
  timeline: TimelineEntry[]
  clip_status: 'pending' | 'ready' | 'failed' | null
  clip_error: string | null
  alert_suppressed: boolean
}

/**
 * `GET /events` 쿼리 파라미터. API명세서 §4.1
 */
export interface EventListQuery {
  from: string | null
  to: string | null
  cam_id: number | null
  type: ViolationType | null
  status: EventStatus | null
  zone_id: string | null
  limit: number | null
  cursor: string | null
}

/**
 * `GET /events` 응답. API명세서 §4.1
 */
export interface EventListResponse {
  items: EventSummary[]
  next_cursor: string | null
}

/**
 * `PATCH /events/{event_id}`. API명세서 §4.1
 */
export interface EventPatchRequest {
  is_false_positive: boolean | null
  note: string | null
  force_resolve: boolean | null
}

/**
 * `attachments[]` 의 이벤트 링크 — 상세 화면으로 이동. API명세서 §4.4
 */
export interface EventRefAttachment {
  kind: 'event_ref'
  event_id: string
  label: string
}

/**
 * 이벤트 상태머신 값. 기능명세서 §4.2 상태 전이표.
 */
export type EventStatus = 'candidate' | 'active' | 'alerted' | 're_alerted' | 'lost' | 'resolved' | 'expired' | 'dropped'

/**
 * `GET /events` 목록 항목. API명세서 §4.1
 */
export interface EventSummary {
  event_id: string
  cam_id: number
  track_id: number
  violation_type: ViolationType
  zone_id: string | null
  status: EventStatus
  detected_at: string
  confirmed_at: string | null
  alerted_at: string | null
  last_alerted_at: string | null
  note: string | null
  resolved_at: string | null
  resolution_sec: number | null
  alert_count: number
  min_distance_m: number | null
  posture: 'standing' | 'fallen' | 'unknown' | null
  repeat_count_7d: number
  thumbnail_url: string | null
}

/**
 * `event_updated` — 상태 변경(경고·해소·재경고·소실·종결). API명세서 §5.2
 */
export interface EventUpdatedMsg {
  type: 'event_updated'
  event_id: string
  status: EventStatus
  alerted_at: string | null
  last_alerted_at: string | null
  alert_count: number | null
  severity: 1 | 2 | 3 | null
  lost_at: string | null
  track_id: number | null
  reassoc_count: number | null
  resolved_at: string | null
  resolution_sec: number | null
  expired_at: string | null
  clip_status: 'pending' | 'ready' | 'failed' | null
  clip_url: string | null
  is_false_positive: boolean | null
  note: string | null
}

/**
 * `frame` — 프레임 메타데이터 (매 프레임). API명세서 §2.1
 */
export interface FrameMsg {
  type: 'frame'
  cam_id: number
  ts: string
  objects: (DetectedPerson | DetectedVehicle)[]
}

/**
 * `frame.objects[].nearby[]` — 이 사람과 차량 사이의 거리. API명세서 §2.1
 */
export interface FrameNearby {
  track_id: number
  class: 'vehicle'
  dist_m: number
  basis: 'mask_nearest' | 'anchor'
  in_danger_zone: boolean
}

/**
 * `heartbeat` — 상태 보고 (5초 주기). API명세서 §2.4
 */
export interface HeartbeatMsg {
  type: 'heartbeat'
  ts: string
  cameras: CameraHealth[]
  gpu_util: number
  mem_used_mb: number
  cls_calls_per_min: number
  cls_cache_hit_rate: number
  depth_calls_per_min: number
  clock: EdgeClock | null
}

/**
 * `attachments[]` 의 이미지 첨부. API명세서 §4.4
 */
export interface ImageAttachment {
  kind: 'image'
  image_url: string
  label: string
}

/**
 * `POST /alerts/manual` 요청. API명세서 §4.5
 */
export interface ManualAlertRequest {
  cam_id: number
  sound: string | null
  level: 1 | 2 | 3
  notify_device: boolean
}

/**
 * `POST /alerts/manual` 응답(`202`). API명세서 §4.5
 */
export interface ManualAlertResponse {
  dispatched_at: string
}

/**
 * ESP32 상태. API명세서 §4.6
 */
export interface McuStatus {
  online: boolean
  last_seen: string | null
}

/**
 * `metric` — 지표 갱신. API명세서 §5.3
 */
export interface MetricMsg {
  type: 'metric'
  period: string
  correction_rate: number | null
  undetermined_rate: number | null
  total_violations: number
  resolved: number
  resolved_late: number
  unresolved: number
  undetermined: number
  suppressed: number
  avg_resolution_sec: number
  fall_events: number
  anomaly_flags: number
}

/**
 * `GET /metrics/distribution` 쿼리 파라미터. API명세서 §4.2
 */
export interface MetricsDistributionQuery {
  by: 'violation_type' | 'zone' | 'camera' | 'hour_of_day'
  from: string | null
  to: string | null
}

/**
 * `GET /metrics/distribution` 응답. API명세서 §4.2
 */
export interface MetricsDistributionResponse {
  by: 'violation_type' | 'zone' | 'camera' | 'hour_of_day'
  buckets: DistributionBucket[]
}

/**
 * `GET /metrics/repeat` 쿼리 파라미터. API명세서 §4.2
 */
export interface MetricsRepeatQuery {
  days: number
  limit: number
}

/**
 * `GET /metrics/repeat` 응답. API명세서 §4.2
 */
export interface MetricsRepeatResponse {
  days: number
  items: RepeatItem[]
}

/**
 * `GET /metrics/summary`. API명세서 §4.2 · §6.7
 */
export interface MetricsSummary {
  period: string
  correction_rate: number | null
  undetermined_rate: number | null
  total_violations: number
  resolved: number
  resolved_late: number
  unresolved: number
  undetermined: number
  suppressed: number
  avg_resolution_sec: number
  fall_events: number
  anomaly_flags: number
}

/**
 * `GET /metrics/timeseries` 쿼리 파라미터. API명세서 §4.2
 */
export interface MetricsTimeseriesQuery {
  metric: 'violations' | 'correction_rate' | 'avg_resolution_sec' | 'undetermined_rate'
  bucket: 'hour' | 'day' | 'week'
  from: string | null
  to: string | null
}

/**
 * `GET /metrics/timeseries` 응답. API명세서 §4.2
 */
export interface MetricsTimeseriesResponse {
  metric: 'violations' | 'correction_rate' | 'avg_resolution_sec' | 'undetermined_rate'
  bucket: 'hour' | 'day' | 'week'
  points: TimeseriesPoint[]
}

/**
 * `POST /alerts/mute` 요청. API명세서 §4.5
 */
export interface MuteAlertRequest {
  cam_id: number | null
  minutes: number | null
  reason: string
}

/**
 * `POST /alerts/mute` · `GET /alerts/mute` 응답. API명세서 §4.5
 */
export interface MuteAlertResponse {
  cam_id: number | null
  muted: boolean
  muted_until: string | null
  reason: string | null
}

/**
 * 확정 시점의 주변 지게차 상태 스냅샷. API명세서 §4.1
 */
export interface NearbySnapshot {
  class: 'vehicle'
  track_id: number
  dist_m: number
  depth_verified: boolean
  moving: boolean
  within_danger_radius: boolean
}

/**
 * `candidate.nearby[]` 원소 — 주변 위험 지게차. API명세서 §2.2
 */
export interface NearbyVehicle {
  class: 'vehicle'
  track_id: number
  dist_m: number
  method: 'bbox_center' | 'mask_nearest'
  depth_verified: boolean
  moving: boolean
  within_danger_radius: boolean
}

/**
 * `overlay` — 이벤트 상태로 보강된 오버레이 데이터. API명세서 §5.1
 */
export interface OverlayMsg {
  type: 'overlay'
  cam_id: number
  ts: string
  objects: (OverlayPerson | OverlayVehicle)[]
}

/**
 * `overlay.objects[].nearby[]` — 거리선을 그리기 위한 상대 차량. API명세서 §5.1
 */
export interface OverlayNearby {
  class: 'vehicle'
  track_id: number
  dist_m: number
  anchor: [number, number]
  in_danger_zone: boolean
}

/**
 * `overlay.objects[]` 의 person. API명세서 §5.1
 */
export interface OverlayPerson {
  class: 'person'
  track_id: number
  bbox: [number, number, number, number]
  foot_point: [number, number]
  posture: 'standing' | 'fallen' | 'unknown'
  in_zone: string | null
  helmet: 'on' | 'off' | null
  violations: ViolationType[]
  event_ids: string[]
  alert_state: 'candidate' | 'active' | 'alerted' | 're_alerted' | 'lost' | null
  nearby: OverlayNearby[]
}

/**
 * `overlay.objects[]` 의 vehicle(지게차). API명세서 §5.1
 */
export interface OverlayVehicle {
  class: 'vehicle'
  track_id: number
  bbox: [number, number, number, number]
  anchor: [number, number]
  moving: boolean
  danger_radius_m: number
  violations: ViolationType[]
  event_ids: string[]
  alert_state: 'candidate' | 'active' | 'alerted' | 're_alerted' | 'lost' | null
  nearby: OverlayNearby[]
}

/**
 * 정책값 전량. API명세서 §4.5
 */
export interface Policies {
  confirm_duration_s: number
  resolve_duration_s: number
  cooldown_s: number
  resolve_window_s: number
  track_miss_timeout_ms: number
  track_lost_grace_s: number
  reassoc_window_s: number
  reassoc_max_speed_ms: number
  reassoc_radius_cap_m: number
  proximity_threshold_m: number
  vehicle_danger_radius_m: number
  depth_band_m: [number, number]
  depth_cache_ms: number
  screening_radius_m: number
  min_confidence: number
  cls_cache_ms: number
  cls_min_crop_px: number
  cls_min_conf: number
  clip_pre_roll_s: number
  clip_post_roll_s: number
  clip_extract_margin_s: number
  alert_duration_s: number
  mute_default_duration_s: number
  overlay_buffer_webrtc_ms: number
  overlay_buffer_hls_ms: number
  overlay_stale_ms: number
  fall_height_ratio_max: number
  fall_axis_angle_min_deg: number
  fall_stillness_s: number
  stillness_move_px: number
  stillness_window_s: number
  stillness_shape_change_max: number
  anomaly_sample_interval_min: number
  anomaly_threshold: number
  anomaly_knn_k: number
  anomaly_min_pool: number
  anomaly_time_bucket_h: number
  clock_offset_warn_ms: number
  assistant_history_turns: number
}

/**
 * `PATCH /policies` 요청. 지정한 키만 갱신한다. API명세서 §4.5
 */
export interface PolicyPatch {
  confirm_duration_s: number | null
  resolve_duration_s: number | null
  cooldown_s: number | null
  resolve_window_s: number | null
  track_miss_timeout_ms: number | null
  track_lost_grace_s: number | null
  reassoc_window_s: number | null
  reassoc_max_speed_ms: number | null
  reassoc_radius_cap_m: number | null
  proximity_threshold_m: number | null
  vehicle_danger_radius_m: number | null
  depth_band_m: [number, number] | null
  depth_cache_ms: number | null
  screening_radius_m: number | null
  min_confidence: number | null
  cls_cache_ms: number | null
  cls_min_crop_px: number | null
  cls_min_conf: number | null
  clip_pre_roll_s: number | null
  clip_post_roll_s: number | null
  clip_extract_margin_s: number | null
  alert_duration_s: number | null
  mute_default_duration_s: number | null
  overlay_buffer_webrtc_ms: number | null
  overlay_buffer_hls_ms: number | null
  overlay_stale_ms: number | null
  fall_height_ratio_max: number | null
  fall_axis_angle_min_deg: number | null
  fall_stillness_s: number | null
  stillness_move_px: number | null
  stillness_window_s: number | null
  stillness_shape_change_max: number | null
  anomaly_sample_interval_min: number | null
  anomaly_threshold: number | null
  anomaly_knn_k: number | null
  anomaly_min_pool: number | null
  anomaly_time_bucket_h: number | null
  clock_offset_warn_ms: number | null
  assistant_history_turns: number | null
}

/**
 * `GET /status` 의 카메라 항목. API명세서 §4.7
 */
export interface RecCameraStatus {
  cam_id: number
  recording: boolean
  last_segment_at: string | null
}

/**
 * `GET /status` 의 녹화 절. API명세서 §4.7 · 기능명세서 §4.4
 */
export interface RecRecordingStatus {
  segment_seconds: number
  snapshot_window_s: number
  snapshot_bytes: number
}

/**
 * `GET /status`. API명세서 §4.7
 */
export interface RecStatusResponse {
  cameras: RecCameraStatus[]
  storage: RecStorageStatus
  recording: RecRecordingStatus
}

/**
 * `GET /status` 의 저장소 절. API명세서 §4.7
 */
export interface RecStorageStatus {
  total_gb: number
  used_gb: number
  free_gb: number
  retention_days: number
  oldest_segment_at: string | null
}

/**
 * 저장된 높이 비율 기준. 기능명세서 §6 `cameras.ref_height`(jsonb)
 */
export interface RefHeight {
  height_px: number
  at_m: [number, number]
}

/**
 * 높이 비율 기준 보정용(선택). `POST /cameras/{id}/calibration` 요청. API명세서 §4.5
 */
export interface ReferencePerson {
  height_px: number
  at_m: [number, number]
}

/**
 * 사전 매핑 테이블로 연결된 규정 조항(LLM 생성 아님). API명세서 §4.1 · FN-AI-06
 */
export interface RegulationRef {
  code: string
  title: string
}

/**
 * `GET /metrics/repeat` 의 한 항목. API명세서 §4.2
 */
export interface RepeatItem {
  subject: 'zone' | 'camera' | 'track'
  key: string
  label: string
  violation_type: ViolationType
  count: number
  last_at: string
}

/**
 * `GET /reports/{report_id}` 응답. API명세서 §4.4
 */
export interface ReportDetail {
  report_id: string
  status: 'pending' | 'ready' | 'failed'
  period: ReportPeriod
  body: string | null
  stats: MetricsSummary | null
  created_at: string
  error: string | null
}

/**
 * `GET /reports/{report_id}` 의 `period`. API명세서 §4.4
 */
export interface ReportPeriod {
  from: string
  to: string
}

/**
 * `POST /search/scenes` 필터. API명세서 §4.3
 */
export interface SceneSearchFilters {
  from: string | null
  to: string | null
  cam_id: number | null
}

/**
 * `POST /search/scenes` 결과 항목. API명세서 §4.3
 */
export interface SceneSearchItem {
  event_id: string
  similarity: number | null
  title: string
  cam_id: number
  occurred_at: string
  thumbnail_url: string | null
  clip_url: string | null
}

/**
 * `POST /search/scenes` 요청. API명세서 §4.3
 */
export interface SceneSearchRequest {
  query: string
  top_k: number
  filters: SceneSearchFilters
}

/**
 * `POST /search/scenes` 응답. API명세서 §4.3
 */
export interface SceneSearchResponse {
  mode: 'sql' | 'vector' | 'hybrid'
  items: SceneSearchItem[]
}

/**
 * 임베딩 유사도로 매칭된 과거 사고사례. API명세서 §4.1 · FN-AI-07
 */
export interface SimilarIncident {
  title: string
  source: string
  similarity: number
}

/**
 * 저장소 상태. API명세서 §4.6
 */
export interface StorageStatus {
  total_gb: number | null
  used_gb: number | null
  free_gb: number | null
  retention_days: number | null
  oldest_segment_at: string | null
}

/**
 * `GET /system/status`. API명세서 §4.6
 */
export interface SystemStatus {
  edge: EdgeStatus
  cameras: CameraStatus[]
  mcu: McuStatus
  cloud: CloudStatus
  storage: StorageStatus
  time_sync: TimeSyncStatus
}

/**
 * `attachments[]` 의 표 첨부 — SQL 집계 결과 표시용. API명세서 §4.4
 */
export interface TableAttachment {
  kind: 'table'
  columns: string[]
  rows: ((string | number | null)[])[]
  label: string
}

/**
 * 엣지–서버 시각 차이. 크면 클립 추출 구간이 어긋난다. API명세서 §4.6
 */
export interface TimeSyncStatus {
  edge_offset_ms: number | null
  edge_synced: boolean | null
  server_offset_ms: number | null
}

/**
 * 이벤트 상태 전이 타임라인 항목. API명세서 §4.1
 */
export interface TimelineEntry {
  at: string
  state: EventStatus
}

/**
 * `GET /metrics/timeseries` 의 한 점. API명세서 §4.2
 */
export interface TimeseriesPoint {
  t: string
  value: number
  n: number
}

/**
 * `track_lost` — 트랙 소실 통지. API명세서 §2.3
 */
export interface TrackLostMsg {
  type: 'track_lost'
  cam_id: number
  track_id: number
  class: 'person' | 'vehicle'
  last_ts: string
  last_foot_point_m: [number, number]
  last_helmet: 'on' | 'off' | null
  reason: 'occluded' | 'out_of_view' | 'low_conf'
}

/**
 * 클래스별 위험 반경. `GET /vehicle-classes`. API명세서 §4.5
 */
export interface VehicleClass {
  class_name: string
  danger_radius_m: number
  active: boolean
}

/**
 * `PATCH /vehicle-classes/{name}` 요청. API명세서 §4.5
 */
export interface VehicleClassPatch {
  danger_radius_m: number | null
  active: boolean | null
}

/**
 * 위반 유형. API명세서 §2.2 · §4.1 · §5.2 의 `violation_type`.
 */
export type ViolationType = 'no_helmet' | 'zone_intrusion' | 'proximity' | 'fall'

/**
 * `POST /reports/weekly` 요청. API명세서 §4.4
 */
export interface WeeklyReportRequest {
  from: string
  to: string
}

/**
 * `POST /reports/weekly` 응답. API명세서 §4.4
 */
export interface WeeklyReportResponse {
  report_id: string
  status: 'pending' | 'ready' | 'failed'
  estimated_sec: number
}

/**
 * 금지구역. `GET /zones` / `POST /zones`. API명세서 §4.5
 */
export interface Zone {
  zone_id: string
  cam_id: number
  name: string
  polygon_m: ([number, number])[]
  polygon: ([number, number])[]
  buffer_m: number
  active: boolean
}

/**
 * `zone_updated` — 금지구역 변경 통지. API명세서 §5.4
 */
export interface ZoneUpdatedMsg {
  type: 'zone_updated'
  cam_id: number
  action: 'upsert' | 'delete'
  zone: ZoneUpdatedPayload
}

/**
 * `zone_updated.zone` — 구역 리소스. API명세서 §5.4
 */
export interface ZoneUpdatedPayload {
  zone_id: string
  name: string | null
  polygon_m: ([number, number])[] | null
  buffer_m: number | null
  active: boolean | null
}

/**
 * `POST /zones` 요청. API명세서 §4.5
 */
export interface ZoneUpsertRequest {
  zone_id: string
  cam_id: number
  name: string
  polygon: ([number, number])[]
  buffer_m: number
  active: boolean
}
