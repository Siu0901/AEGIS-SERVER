/**
 * 영상 위 오버레이 렌더링 (FN-UI-02 표시 규칙 · API명세서 §5.1).
 *
 * 표시 규칙은 기능명세서 §4.6 표 그대로다.
 *
 * | 대상 | 색상 | 라벨 예시 |
 * |---|---|---|
 * | 정상 사람 | 청록 | `작업자 #7 · 정상` |
 * | 위반 사람 | 적색 | `작업자 #3 · 안전모 미착용` |
 * | 쓰러진 사람 | 적색(점멸) | `작업자 #5 · 쓰러짐 감지` |
 * | 지게차 | 앰버 | `지게차 #1 · 이동 중` |
 * | 근접 거리선 | 적색 점선 + 거리 라벨 | `3.2 m` |
 *
 * **박스는 `person` 과 `vehicle` 에만 그린다.** 안전모에는 별도 bbox 가 없다 —
 * 1단계 감지는 2클래스뿐이고 안전모는 2단계 분류 결과라 사람 박스의 색과 라벨로 표현한다.
 *
 * **위반 여부를 여기서 추론하지 않는다.** `violations` 를 그대로 읽는다. `helmet` 으로
 * 색을 정하면 `proximity` 와 `fall` 을 놓친다.
 *
 * 그리는 시점은 `requestVideoFrameCallback` 이다. 임의의 `requestAnimationFrame` 으로
 * 돌리면 "지금 화면에 나가는 프레임이 언제 찍힌 것인지"를 알 수 없어 ±100ms 를 맞출 수 없다.
 */

import { useEffect, useRef } from 'react'
import { subscribeDashboard } from '../api/system'
import type { OverlayObject, OverlayPerson, OverlayPolicies, Zone } from '../types/system'
import { isOverlayMsg } from '../types/system'
import { OverlayBuffer, targetTimestamp, type Sample } from './overlayBuffer'
import { OVERLAY_BUFFER_POLICY_KEY, type PlaybackKind } from './player'

/** 기능명세서 §4.6 표시 규칙의 색. 시안의 팔레트를 따르되 용어는 명세서다. */
const COLOR = {
  normal: '#22d3ee', // 청록 — 정상 사람
  violation: '#ef4444', // 적색 — 위반 사람 · 근접 거리선
  vehicle: '#f59e0b', // 앰버 — 지게차
} as const

/** 위반 유형 라벨. 시안의 건설현장 용어가 아니라 명세서 용어다(부록 B). */
const VIOLATION_LABEL: Record<string, string> = {
  no_helmet: '안전모 미착용',
  zone_intrusion: '금지구역 침입',
  proximity: '지게차 근접',
  fall: '쓰러짐 감지',
}

/** 쓰러짐 박스 점멸 주기(ms). 표시 효과일 뿐 판정과 무관하다. */
const BLINK_PERIOD_MS = 700

type Props = {
  camId: number
  videoRef: React.RefObject<HTMLVideoElement | null>
  /** 현재 재생 경로. 지연 버퍼가 경로마다 다르다(§4.5). */
  kind: PlaybackKind
  /** `GET /policies` 값. 없으면 **그리지 않는다** — 틀린 위치의 박스가 없는 박스보다 나쁘다. */
  policies: OverlayPolicies | null
  /** 캐시된 금지구역. 라벨에 구역 표시 이름을 쓰기 위해서다(§5.1 · §5.4). */
  zones: Zone[]
}

export default function OverlayCanvas({ camId, videoRef, kind, policies, zones }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const bufferRef = useRef(new OverlayBuffer())

  // 렌더 루프가 매 프레임 최신 값을 봐야 하는데, effect 를 다시 걸면 rVFC 등록이
  // 끊겼다 붙으며 한두 프레임이 빈다. ref 로 넘겨 루프는 한 번만 건다.
  const policiesRef = useRef(policies)
  policiesRef.current = policies
  const kindRef = useRef(kind)
  kindRef.current = kind
  const zonesRef = useRef(zones)
  zonesRef.current = zones

  // 수신 — 화면 갱신과 분리한다. 소켓은 `subscribeDashboard` 가 하나로 유지하므로
  // 단독 확대 보기에서 타일을 내려도 다른 채널의 수신은 끊기지 않는다(FN-UI-02).
  useEffect(() => {
    const buffer = bufferRef.current
    return subscribeDashboard({
      onMessage: (message) => {
        if (!isOverlayMsg(message) || message.cam_id !== camId) return
        buffer.push(message)
      },
    })
  }, [camId])

  useEffect(() => {
    const canvas = canvasRef.current
    const video = videoRef.current
    if (!canvas || !video) return
    const context = canvas.getContext('2d')
    if (!context) return

    let handle = 0
    let cancelled = false

    const draw: VideoFrameRequestCallback = (_now, metadata) => {
      if (cancelled) return
      const settings = policiesRef.current
      const bufferKey = OVERLAY_BUFFER_POLICY_KEY[kindRef.current]

      resize(canvas, video)
      context.clearRect(0, 0, canvas.width, canvas.height)

      if (settings && bufferKey) {
        // `expectedDisplayTime` 은 `performance.now()` 기준이다. `timeOrigin` 을 더하면
        // 그 프레임이 화면에 나가는 벽시계 시각이 되고, 거기서 경로별 버퍼를 빼면
        // 그 프레임이 카메라에서 찍힌 시각이 된다.
        const displayAt = performance.timeOrigin + metadata.expectedDisplayTime
        const targetAt = targetTimestamp(displayAt, settings[bufferKey])
        const sample = bufferRef.current.sample(targetAt)
        if (sample) render(context, canvas, video, sample, settings, zonesRef.current)
      }

      handle = video.requestVideoFrameCallback(draw)
    }

    if (typeof video.requestVideoFrameCallback !== 'function') {
      // 이 브라우저에서는 "지금 나가는 프레임의 시각"을 알 수 없다. 정합을 맞출 수단이
      // 없으므로 그리지 않는다 — 어긋난 박스는 없는 박스보다 나쁘다.
      console.warn('[overlay] requestVideoFrameCallback 이 없어 오버레이를 그리지 않는다')
      return
    }

    handle = video.requestVideoFrameCallback(draw)
    return () => {
      cancelled = true
      video.cancelVideoFrameCallback(handle)
    }
  }, [videoRef])

  return <canvas ref={canvasRef} className="tile__overlay" aria-hidden="true" />
}

/** 캔버스를 표시 크기 × devicePixelRatio 로 맞춘다. 안 하면 선이 뭉갠다. */
function resize(canvas: HTMLCanvasElement, video: HTMLVideoElement): void {
  const ratio = window.devicePixelRatio || 1
  const width = Math.round(video.clientWidth * ratio)
  const height = Math.round(video.clientHeight * ratio)
  if (canvas.width !== width) canvas.width = width
  if (canvas.height !== height) canvas.height = height
}

/**
 * 정규화 좌표 → 캔버스 픽셀.
 *
 * `video` 는 `object-fit: contain` 이라 요소 전체가 영상이 아니다. 화면비가 다르면
 * 위아래(또는 좌우)에 레터박스가 생기고, 그 여백을 빼지 않으면 박스가 통째로 밀린다.
 */
function viewport(canvas: HTMLCanvasElement, video: HTMLVideoElement) {
  const vw = video.videoWidth || 16
  const vh = video.videoHeight || 9
  const scale = Math.min(canvas.width / vw, canvas.height / vh)
  const width = vw * scale
  const height = vh * scale
  return {
    x: (canvas.width - width) / 2,
    y: (canvas.height - height) / 2,
    width,
    height,
    /** 화면 크기에 비례하는 선 굵기·글자 크기. 단독 확대에서도 같은 인상이 나오게 한다. */
    unit: Math.max(1, canvas.height / 360),
  }
}

function render(
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  video: HTMLVideoElement,
  sample: Sample,
  policies: OverlayPolicies,
  zones: Zone[],
): void {
  const view = viewport(canvas, video)
  const stale = sample.ageMs > policies.overlay_stale_ms

  context.save()
  // 낡은 좌표는 흐리게 — 신뢰할 수 없다는 표시다(§5 5번).
  context.globalAlpha = stale ? 0.35 : 1
  context.lineJoin = 'round'
  context.textBaseline = 'bottom'

  for (const object of sample.objects) {
    if (object.class === 'person') drawPerson(context, view, object, zones)
    else drawVehicle(context, view, object)
  }
  // 거리선은 박스 위에 그린다. 박스 테두리에 가려지면 라벨이 읽히지 않는다.
  for (const object of sample.objects) {
    if (object.class === 'person') drawNearby(context, view, object)
  }

  if (stale) drawStaleBadge(context, canvas, view, sample.ageMs)
  context.restore()
}

type View = ReturnType<typeof viewport>

function box(view: View, bbox: [number, number, number, number]) {
  const [x1, y1, x2, y2] = bbox
  return {
    x: view.x + x1 * view.width,
    y: view.y + y1 * view.height,
    w: (x2 - x1) * view.width,
    h: (y2 - y1) * view.height,
  }
}

function point(view: View, [x, y]: [number, number]) {
  return { x: view.x + x * view.width, y: view.y + y * view.height }
}

function drawPerson(
  context: CanvasRenderingContext2D,
  view: View,
  person: OverlayPerson,
  zones: Zone[],
): void {
  const fallen = person.violations.includes('fall')
  const violating = person.violations.length > 0
  const color = violating ? COLOR.violation : COLOR.normal

  context.save()
  if (fallen) {
    // 쓰러짐만 점멸한다. 유일하게 자력 시정이 불가능한 위반이라 눈을 끌어야 한다.
    const phase = (Date.now() % BLINK_PERIOD_MS) / BLINK_PERIOD_MS
    context.globalAlpha *= 0.55 + 0.45 * Math.abs(Math.cos(phase * Math.PI))
  }
  const rect = box(view, person.bbox)
  context.strokeStyle = color
  context.lineWidth = view.unit * (violating ? 2.2 : 1.6)
  context.strokeRect(rect.x, rect.y, rect.w, rect.h)

  // 접지점 — 거리·구역 판정의 기준점이다(§6.1). 어디를 기준으로 판정했는지 보여준다.
  const foot = point(view, person.foot_point)
  context.fillStyle = color
  context.beginPath()
  context.arc(foot.x, foot.y, view.unit * 1.6, 0, Math.PI * 2)
  context.fill()

  label(context, view, rect.x, rect.y, color, personLabel(person, zones))
  context.restore()
}

function personLabel(person: OverlayPerson, zones: Zone[]): string {
  const who = `작업자 #${person.track_id}`
  if (person.violations.length === 0) {
    // 구역 안에 있는 것 자체는 위반이 아니다(통행이 허용된 구역도 있다). 위치만 덧붙인다.
    const zone = zones.find((item) => item.zone_id === person.in_zone)
    return zone ? `${who} · 정상 (${zone.name})` : `${who} · 정상`
  }
  return `${who} · ${person.violations.map((v) => VIOLATION_LABEL[v] ?? v).join(' · ')}`
}

function drawVehicle(
  context: CanvasRenderingContext2D,
  view: View,
  vehicle: Extract<OverlayObject, { class: 'vehicle' }>,
): void {
  const rect = box(view, vehicle.bbox)
  context.strokeStyle = COLOR.vehicle
  context.lineWidth = view.unit * 1.6
  context.strokeRect(rect.x, rect.y, rect.w, rect.h)
  label(
    context,
    view,
    rect.x,
    rect.y,
    COLOR.vehicle,
    `지게차 #${vehicle.track_id} · ${vehicle.moving ? '이동 중' : '정지'}`,
  )
}

/** 근접 거리선 — 적색 점선 + 거리 라벨 (기능명세서 §4.6 표시 규칙). */
function drawNearby(context: CanvasRenderingContext2D, view: View, person: OverlayPerson): void {
  if (person.nearby.length === 0) return
  const from = point(view, person.foot_point)

  for (const other of person.nearby) {
    const to = point(view, other.anchor)
    context.save()
    context.strokeStyle = COLOR.violation
    context.lineWidth = view.unit * (other.in_danger_zone ? 1.6 : 1.1)
    context.setLineDash([view.unit * 4, view.unit * 3])
    context.beginPath()
    context.moveTo(from.x, from.y)
    context.lineTo(to.x, to.y)
    context.stroke()
    context.restore()

    label(
      context,
      view,
      (from.x + to.x) / 2,
      (from.y + to.y) / 2,
      COLOR.violation,
      `${other.dist_m.toFixed(1)} m`,
    )
  }
}

function label(
  context: CanvasRenderingContext2D,
  view: View,
  x: number,
  y: number,
  color: string,
  text: string,
): void {
  const size = view.unit * 11
  context.font = `600 ${size}px system-ui, sans-serif`
  const width = context.measureText(text).width
  const padding = size * 0.35
  const height = size * 1.5
  const top = Math.max(0, y - height)

  context.fillStyle = 'rgba(0, 0, 0, 0.68)'
  context.fillRect(x, top, width + padding * 2, height)
  context.fillStyle = color
  context.fillText(text, x + padding, top + height - padding * 0.8)
}

/** 좌표가 끊겼다는 표시. 흐린 박스만으로는 "사람이 안 보인다"와 구분되지 않는다. */
function drawStaleBadge(
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  view: View,
  ageMs: number,
): void {
  context.save()
  context.globalAlpha = 1
  label(
    context,
    view,
    view.unit * 4,
    view.unit * 4 + view.unit * 16,
    '#f59e0b',
    `좌표 지연 ${(ageMs / 1000).toFixed(1)}초 — 위치를 신뢰할 수 없다`,
  )
  context.restore()
  void canvas
}
