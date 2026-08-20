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
 * | 트럭 | 앰버 | `트럭 #1 · 이동 중` |
 * | 탑승자 | 청록 | `작업자 #3 · 운전 중 (트럭 #1)` — 거리선 없음 |
 * | 근접 거리선 | 적색 점선 + 거리 라벨 | `3.2 m` |
 * | 금지구역 | 보라 점선 + 옅은 채움 | `금지구역 · 지게차 통행로` |
 *
 * **금지구역만 좌표와 무관하게 그린다**(§5.1 · §5.4). 폴리곤은 `overlay` 에 실려
 * 오지 않고 `GET /zones` 캐시에서 오므로, 엣지가 끊겨도 화면에 남아 있어야 한다 —
 * 「사람이 안 보인다」와 「구역이 설정되지 않았다」는 다른 사실이다.
 *
 * **확정 전(`alert_state === 'candidate'`)은 적색으로 그리지 않는다** (§5.1).
 * 위반 조건이 관측됐을 뿐 확정된 것이 아니므로 위반으로 단정할 수 없다. 청록을
 * 유지하되 **점선 테두리 + `확정 중` 라벨**로 진행 중임을 드러낸다 — 색을 바꾸지
 * 않는 이유는 적색이 "경고가 나갔다"는 뜻으로 굳어져야 하기 때문이다.
 *
 * **박스는 `person` 과 `vehicle` 에만 그린다.** 안전모에는 별도 bbox 가 없다 —
 * 1단계 감지는 2클래스뿐이고 안전모는 2단계 분류 결과라 사람 박스의 색과 라벨로 표현한다.
 *
 * **위반 여부를 여기서 추론하지 않는다.** `violations` 와 `alert_state` 를 그대로 읽는다.
 * `helmet` 으로 색을 정하면 `proximity` 와 `fall` 을 놓친다.
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
  normal: '#22d3ee', // 청록 — 정상 사람 · 확정 전 후보
  violation: '#ef4444', // 적색 — 확정된 위반 사람 · 근접 거리선
  vehicle: '#f59e0b', // 앰버 — 지게차
  //: 금지구역 경계. **사람·지게차 어느 색과도 겹치지 않아야 한다** — 구역은 관측된
  //: 대상이 아니라 사람이 설정한 경계선이고, 그 둘이 같은 색이면 화면에서 "지금 무엇이
  //: 감지된 것"과 "여기가 어디"가 섞인다.
  zone: '#a855f7', // 보라 — 금지구역 폴리곤
} as const

/**
 * 거리 라벨 단위.
 *
 * ★ **`_m` 은 스키마 필드명이며 그 숫자의 단위는 캘리브레이션이 정한다.** 미니어처
 * 시연에서는 모형을 자로 잰 cm 를 그대로 넣으므로 화면에 나오는 숫자도 cm 다
 * (기능명세서 §4.7 FN-CFG-01). 실물 현장으로 옮길 때는 캘리브레이션을 미터로 다시
 * 하고 정책값도 되돌리므로, 그때 이 값을 `m` 으로 바꾼다 — 고칠 곳은 여기 하나다.
 */
const DISTANCE_UNIT = 'cm'

/** 선 굵기(`view.unit` 배수). 한 곳에 모아 화면 전체의 인상을 함께 조정한다. */
const LINE = {
  person: 3.0,
  personConfirmed: 4.5,
  vehicle: 3.0,
  zone: 3.0,
  nearby: 2.4,
  nearbyDanger: 3.4,
  dot: 2.6,
} as const

/**
 * 어두운 테두리를 깔고 색을 얹는다.
 *
 * ★ **색만 진하게 해서는 안 보인다.** 레고 보드처럼 밝고 무늬가 촘촘한 배경에서는
 * 얇은 선이 그대로 묻힌다. 검은 테두리를 한 겹 깔면 배경이 무엇이든 윤곽이 살아난다.
 * 지도·방송 그래픽이 쓰는 방식과 같다.
 *
 * 호출 전에 경로(`beginPath` ~)가 만들어져 있어야 한다.
 */
function haloStroke(context: CanvasRenderingContext2D, color: string, width: number): void {
  const dash = context.getLineDash()
  context.strokeStyle = 'rgba(0, 0, 0, 0.62)'
  context.lineWidth = width + Math.max(2, width * 0.7)
  context.stroke()
  context.setLineDash(dash)
  context.strokeStyle = color
  context.lineWidth = width
  context.stroke()
}

/** 위반 유형 라벨. 시안의 건설현장 용어가 아니라 명세서 용어다(부록 B). */
const VIOLATION_LABEL: Record<string, string> = {
  no_helmet: '안전모 미착용',
  zone_intrusion: '금지구역 침입',
  // 명세서 용어는 「지게차 근접」이고 화면 표기만 「트럭 근접」이다(`types/labels.ts`).
  proximity: '트럭 근접',
  fall: '쓰러짐 감지',
}

/** 쓰러짐 박스 점멸 주기(ms). 표시 효과일 뿐 판정과 무관하다. */
const BLINK_PERIOD_MS = 700

/** 디버그 표시 갱신 주기(ms). 매 프레임 setState 하면 렌더가 폭주한다. */
const DEBUG_THROTTLE_MS = 200

/** 실시간 관제 디버그 표시가 읽는 값 (FN-UI-02 정합 진단). */
export type OverlayDebug = {
  /** 지금 화면에 나가는 프레임의 표시 시각 (epoch ms). */
  displayAt: number
  /** 그 프레임에 맞춰 그린 오버레이의 `ts` (epoch ms). 그릴 것이 없으면 `null`. */
  overlayTs: number | null
  /** `displayAt − overlayTs`. **적용 버퍼와 같아야 한다** — 다르면 버퍼가 잘못 걸린 것이다. */
  deltaMs: number | null
  /** 실제로 적용한 버퍼 값(ms)과 그 정책 키. 하드코딩이 아니라 `GET /policies` 값이다. */
  bufferMs: number
  bufferKey: string
  kind: PlaybackKind
  /** 좌표 파이프라인 지연: 지금 − 가장 최근에 받은 `ts`. 커지면 엣지·서버 쪽 문제다. */
  arrivalLagMs: number | null
  /** 지연 버퍼에 쌓여 있는 프레임 수. */
  buffered: number
  /** 마지막 좌표가 낡은 정도(ms). `overlay_stale_ms` 초과면 흐리게 그린다. */
  ageMs: number | null
  /**
   * `requestVideoFrameCallback` 메타데이터에 **프레임 촬영 시각이 실려 오는가**.
   *
   * `captureTime` 이 있으면 고정 버퍼 없이 그 시각으로 직접 정합할 수 있다 — 지금 남아
   * 있는 지터의 원인이 고정 버퍼이므로 그것이 되면 문제 자체가 사라진다. 다만 이 필드는
   * WebRTC 경로에서 **송신 측이 `abs-capture-time` RTP 확장을 실어 보낼 때만** 채워지고,
   * 그 값이 가리키는 순간이 카메라 센서인지 mediamtx 수신 지점인지에 따라 의미가 달라진다
   * (후자면 영상 지연의 대부분인 카메라→mediamtx 0.27초가 빠져 고정 버퍼보다 나빠진다).
   *
   * 그래서 **읽어서 보여주기만 한다.** 정합 방식을 바꾸는 것은 이 값과
   * `impliedOffsetMs` 를 실제 브라우저에서 확인한 뒤의 일이다.
   */
  captureTimeMs: number | null
  /** `receiveTime`(수신 시각). 있으면 네트워크 몫을 분리해 볼 수 있다. */
  receiveTimeMs: number | null
  /** `rtpTimestamp`. 벽시계가 아니라 클럭레이트 카운터이므로 단독으로는 쓸 수 없다. */
  rtpTimestamp: number | null
  /**
   * `captureTime` 이 있을 때 **표시 시각과 촬영 시각의 차이**(ms) = 실제 영상 경로 지연.
   *
   * 이 값이 적용 버퍼(`bufferMs`)와 같으면 고정 버퍼가 맞게 걸려 있다는 뜻이고,
   * 다르면 그 차이가 곧 정합 오차다. **고정 버퍼를 대체할 값이 여기서 나온다.**
   */
  captureLagMs: number | null
}

type Props = {
  camId: number
  videoRef: React.RefObject<HTMLVideoElement | null>
  /** 현재 재생 경로. 지연 버퍼가 경로마다 다르다(§4.5). */
  kind: PlaybackKind
  /** `GET /policies` 값. 없으면 **그리지 않는다** — 틀린 위치의 박스가 없는 박스보다 나쁘다. */
  policies: OverlayPolicies | null
  /** 캐시된 금지구역. 폴리곤을 그리고 사람 라벨의 구역 이름에도 쓴다(§5.1 · §5.4). */
  zones: Zone[]
  /** 디버그 표시가 켜져 있을 때만 넘어온다. 꺼져 있으면 계산도 하지 않는다. */
  onDebug?: (info: OverlayDebug) => void
}

export default function OverlayCanvas({ camId, videoRef, kind, policies, zones, onDebug }: Props) {
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
  const debugRef = useRef(onDebug)
  debugRef.current = onDebug

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
    let lastDebugAt = 0

    const draw: VideoFrameRequestCallback = (_now, metadata) => {
      if (cancelled) return
      const settings = policiesRef.current
      const bufferKey = OVERLAY_BUFFER_POLICY_KEY[kindRef.current]

      resize(canvas, video)
      context.clearRect(0, 0, canvas.width, canvas.height)

      // ★ **좌표와 무관하게 먼저 그린다.** 구역은 관측 결과가 아니라 설정이므로,
      //   엣지가 끊겨 `overlay` 가 한 건도 없어도 화면에 있어야 한다. 아래 `render`
      //   안에 넣으면 「사람이 안 보이면 구역도 사라지는」 화면이 된다.
      drawZones(context, canvas, video, zonesRef.current)

      if (settings && bufferKey) {
        // `expectedDisplayTime` 은 `performance.now()` 기준이다. `timeOrigin` 을 더하면
        // 그 프레임이 화면에 나가는 벽시계 시각이 되고, 거기서 경로별 버퍼를 빼면
        // 그 프레임이 카메라에서 찍힌 시각이 된다.
        const bufferMs = settings[bufferKey]
        const displayAt = performance.timeOrigin + metadata.expectedDisplayTime
        const targetAt = targetTimestamp(displayAt, bufferMs)
        const sample = bufferRef.current.sample(targetAt)
        if (sample) render(context, canvas, video, sample, settings, zonesRef.current)

        const report = debugRef.current
        if (report && _now - lastDebugAt >= DEBUG_THROTTLE_MS) {
          lastDebugAt = _now
          const newest = bufferRef.current.newestAt
          // §5 「구현 전제」 조사 — 브라우저가 **프레임 촬영 시각**을 주는가.
          // 주면 고정 버퍼 없이 직접 정합할 수 있다. 지금은 읽어서 표시만 한다
          // (정합 방식을 바꾸기 전에 실측이 있어야 한다 · `docs/INDEX.md` M5 절).
          const extra = metadata as VideoFrameCallbackMetadata & {
            captureTime?: number
            receiveTime?: number
            rtpTimestamp?: number
          }
          const captureAt =
            extra.captureTime === undefined
              ? null
              : performance.timeOrigin + extra.captureTime
          report({
            displayAt,
            overlayTs: sample ? targetAt : null,
            deltaMs: sample ? displayAt - targetAt : null,
            // **실제로 적용한 값**을 그대로 올린다. 화면에 다른 값을 적으면
            // 버퍼가 잘못 걸렸을 때 그 사실이 표시에 가려진다.
            bufferMs,
            bufferKey,
            kind: kindRef.current,
            arrivalLagMs: newest === null ? null : Date.now() - newest,
            buffered: bufferRef.current.size,
            ageMs: sample ? sample.ageMs : null,
            captureTimeMs: captureAt,
            receiveTimeMs:
              extra.receiveTime === undefined
                ? null
                : performance.timeOrigin + extra.receiveTime,
            rtpTimestamp: extra.rtpTimestamp ?? null,
            captureLagMs: captureAt === null ? null : displayAt - captureAt,
          })
        }
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

/**
 * 금지구역 폴리곤 (§5.1 · §5.4 · FN-UI-02).
 *
 * **`overlay` 에 실려 오지 않는다.** 매 프레임 변하지 않으므로 `GET /zones` 로 한 번
 * 조회해 캐시하고 `zone_updated` 로 갱신한 것을 여기서 그린다.
 *
 * 쓰는 좌표는 `polygon`(정규화 픽셀)이지 `polygon_m`(지면 미터)이 아니다. 판정은
 * 지면 좌표로 하지만 화면에 얹는 것은 픽셀이고, 매번 역변환하면 캘리브레이션이
 * 미세하게 바뀔 때마다 도형이 흔들린다 — 사용자가 화면에서 그린 위치가 원본이다.
 *
 * `active: false` 는 그리지 않는다. 꺼 둔 구역이 화면에 남아 있으면 「감시 중」으로
 * 읽히고, 그건 침입이 감지되지 않는 이유를 화면이 숨기는 것이다.
 */
function drawZones(
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  video: HTMLVideoElement,
  zones: Zone[],
): void {
  const drawable = zones.filter((zone) => zone.active && zone.polygon.length >= 3)
  if (drawable.length === 0) return

  const view = viewport(canvas, video)
  context.save()
  context.lineJoin = 'round'
  context.textBaseline = 'bottom'

  for (const zone of drawable) {
    const points = zone.polygon.map((vertex) => point(view, vertex))
    context.beginPath()
    context.moveTo(points[0].x, points[0].y)
    for (const vertex of points.slice(1)) context.lineTo(vertex.x, vertex.y)
    context.closePath()

    // 옅게 채운다 — 진하면 영상이 가려져 정작 그 안에서 무슨 일이 벌어지는지 안 보인다.
    context.fillStyle = 'rgba(168, 85, 247, 0.12)'
    context.fill()
    // 점선으로 그린다. 실선은 감지 박스와 같은 인상이라 「지금 잡힌 것」으로 읽힌다.
    context.setLineDash([view.unit * 6, view.unit * 4])
    haloStroke(context, COLOR.zone, view.unit * LINE.zone)
    context.setLineDash([])

    // 라벨은 가장 위쪽 꼭짓점에 붙인다 — 폴리곤이 화면 아래에 있으면 무게중심에
    // 찍은 글자가 영상 밖으로 밀린다.
    const anchor = points.reduce((top, vertex) => (vertex.y < top.y ? vertex : top), points[0])
    label(context, view, anchor.x, anchor.y, COLOR.zone, `금지구역 · ${zone.name}`)
  }
  context.restore()
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
    if (object.class !== 'person') continue
    // 확정된 근접 위반일 때만 적색이다. `alert_state === 'candidate'` 는 아직 위반이
    // 아니므로(§5.1) 박스와 같은 기준으로 가른다.
    const violating =
      object.alert_state !== 'candidate' && object.violations.includes('proximity')
    drawNearby(context, view, object, violating)
  }

  if (stale) drawStaleBadge(context, view, sample.ageMs)
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
  // **확정 전은 위반이 아니다** (§5.1). 색은 서버가 준 `alert_state` 로 가르고,
  // `violations` 는 라벨에만 쓴다.
  const pending = person.alert_state === 'candidate'
  const confirmed = person.violations.length > 0 && !pending
  const fallen = confirmed && person.violations.includes('fall')
  const color = confirmed ? COLOR.violation : COLOR.normal

  context.save()
  if (fallen) {
    // 쓰러짐만 점멸한다. 유일하게 자력 시정이 불가능한 위반이라 눈을 끌어야 한다.
    const phase = (Date.now() % BLINK_PERIOD_MS) / BLINK_PERIOD_MS
    context.globalAlpha *= 0.55 + 0.45 * Math.abs(Math.cos(phase * Math.PI))
  }
  const rect = box(view, person.bbox)
  // 확정 전은 점선 — 색을 바꾸지 않고도 "아직 단정하지 않았다"가 읽힌다.
  if (pending) context.setLineDash([view.unit * 5, view.unit * 4])
  context.beginPath()
  context.rect(rect.x, rect.y, rect.w, rect.h)
  haloStroke(context, color, view.unit * (confirmed ? LINE.personConfirmed : LINE.person))
  context.setLineDash([])

  drawContour(context, view, person.contour, color)

  // 접지점 — 거리·구역 판정의 기준점이다(§6.1). 어디를 기준으로 판정했는지 보여준다.
  const foot = point(view, person.foot_point)
  context.beginPath()
  context.arc(foot.x, foot.y, view.unit * LINE.dot, 0, Math.PI * 2)
  context.fillStyle = color
  context.fill()
  context.strokeStyle = 'rgba(0, 0, 0, 0.62)'
  context.lineWidth = view.unit * 0.9
  context.stroke()

  label(context, view, rect.x, rect.y, color, personLabel(person, zones, pending))
  context.restore()
}

/**
 * 진단용 마스크 윤곽 (API명세서 §2.1 · 정책 `overlay_mask`).
 *
 * **박스를 대신하지 않는다.** 박스 위에 겹쳐 그린다 — 윤곽은 정책이 켜졌을 때만 오고,
 * 그것이 없다고 화면 구성이 달라지면 「지금 무엇을 보고 있는가」가 흔들린다.
 *
 * 채움을 옅게 두는 이유: 마스크가 사람을 덮으면 안전모 착용 여부를 눈으로 확인할 수
 * 없다. 이 표시의 목적은 **감지가 형태를 제대로 잡았는지** 보는 것이지 사람을 가리는
 * 것이 아니다.
 */
function drawContour(
  context: CanvasRenderingContext2D,
  view: View,
  contour: [number, number][] | null,
  color: string,
): void {
  if (!contour || contour.length < 3) return
  context.save()
  context.beginPath()
  contour.forEach(([x, y], index) => {
    const p = point(view, [x, y])
    if (index === 0) context.moveTo(p.x, p.y)
    else context.lineTo(p.x, p.y)
  })
  context.closePath()
  context.fillStyle = `${color}22`
  context.fill()
  context.strokeStyle = color
  context.lineWidth = view.unit * 1.2
  context.setLineDash([])
  context.stroke()
  context.restore()
}

function personLabel(person: OverlayPerson, zones: Zone[], pending: boolean): string {
  const who = `작업자 #${person.track_id}`
  // 탑승 중이면 그 사실을 먼저 말한다(FN-DET-13). 구역 안에 있어도 침입이 아니고
  // 자기 차량과의 근접도 위반이 아니라서, 이유를 모르면 「왜 안 잡히지」가 된다.
  if (person.riding_track_id !== null) {
    const kinds = person.violations.map((v) => VIOLATION_LABEL[v] ?? v).join(' · ')
    const driving = `${who} · 운전 중 (트럭 #${person.riding_track_id})`
    return kinds ? `${driving} · ${kinds}` : driving
  }
  if (person.violations.length === 0) {
    // 구역 안에 있는 것 자체는 위반이 아니다(통행이 허용된 구역도 있다). 위치만 덧붙인다.
    const zone = zones.find((item) => item.zone_id === person.in_zone)
    return zone ? `${who} · 정상 (${zone.name})` : `${who} · 정상`
  }
  const kinds = person.violations.map((v) => VIOLATION_LABEL[v] ?? v).join(' · ')
  // 확정 전이라는 사실을 라벨에도 적는다. 점선만으로는 캡처 화면에서 구분이 안 된다.
  if (pending) return `${who} · ${kinds} 확정 중`
  // 재경고(FN-EVT-04)는 쿨다운이 지나도록 시정되지 않았다는 뜻이다. 상습 상황을
  // 화면에서 구분할 수 있어야 관리자가 현장에 나갈지 판단한다.
  if (person.alert_state === 're_alerted') return `${who} · ${kinds} 재경고`
  return `${who} · ${kinds}`
}

function drawVehicle(
  context: CanvasRenderingContext2D,
  view: View,
  vehicle: Extract<OverlayObject, { class: 'vehicle' }>,
): void {
  const rect = box(view, vehicle.bbox)
  context.beginPath()
  context.rect(rect.x, rect.y, rect.w, rect.h)
  haloStroke(context, COLOR.vehicle, view.unit * LINE.vehicle)

  drawContour(context, view, vehicle.contour, COLOR.vehicle)

  // 접지점은 **서버가 준 `anchor`** 다(§2.1). 마스크 하단에서 산출한 값이라
  // 박스 아래변 중앙과 다르다 — 포크가 뻗었거나 적재물이 있으면 어긋난다.
  const anchor = point(view, vehicle.anchor)
  context.beginPath()
  context.arc(anchor.x, anchor.y, view.unit * LINE.dot, 0, Math.PI * 2)
  context.fillStyle = COLOR.vehicle
  context.fill()
  context.strokeStyle = 'rgba(0, 0, 0, 0.62)'
  context.lineWidth = view.unit * 0.9
  context.stroke()

  label(
    context,
    view,
    rect.x,
    rect.y,
    COLOR.vehicle,
    `트럭 #${vehicle.track_id} · ${vehicle.moving ? '이동 중' : '정지'}`,
  )
}

/**
 * 근접 거리선 — 적색 점선 + 거리 라벨 (기능명세서 §4.6 표시 규칙).
 *
 * ★ **선이 그려지는 것과 위반은 다르다.** `nearby[]` 에는 스크리닝 반경
 * (`screening_radius_m`) 안의 지게차가 **전부** 실려 오고(§2.2), 이 함수는 그것을
 * 모두 그린다. 위반 후보가 되는 기준은 그보다 좁은 `proximity_threshold_m` 이고,
 * 그마저도 3초 연속 관측을 채워야 서버가 확정한다.
 *
 * 위험 반경(`in_danger_zone`) 안이면 선을 굵게 해서 구분한다.
 *
 * ★ **적색은 확정된 근접 위반에만 쓴다.** 전부 적색으로 그리면 스크리닝 반경 안에
 * 있을 뿐인 차량까지 위반처럼 읽혀서, 「선은 빨간데 확정이 안 된다」가 된다. 위반이
 * 아닌 선은 차량 박스와 같은 앰버로 둬서 "이 차량과의 거리"라는 뜻만 남긴다.
 *
 * 판정은 서버가 준 `violations` · `alert_state` 로만 한다 — 거리와 임계값을 여기서
 * 비교해 위반을 추론하지 않는다(`.claude/rules/front.md`).
 */
function drawNearby(
  context: CanvasRenderingContext2D,
  view: View,
  person: OverlayPerson,
  violating: boolean,
): void {
  if (person.nearby.length === 0) return
  const from = point(view, person.foot_point)
  const color = violating ? COLOR.violation : COLOR.vehicle

  for (const other of person.nearby) {
    // 자기가 탄 차량과는 거리선을 그리지 않는다(FN-DET-13). 거리가 사실상 0이라
    // 선이 박스 안에서 뭉치고, 위반이 아닌 것을 위반처럼 보이게 한다.
    if (other.track_id === person.riding_track_id) continue
    const to = point(view, other.anchor)
    context.save()
    context.setLineDash([view.unit * 4, view.unit * 3])
    context.beginPath()
    context.moveTo(from.x, from.y)
    context.lineTo(to.x, to.y)
    haloStroke(
      context,
      color,
      view.unit * (other.in_danger_zone ? LINE.nearbyDanger : LINE.nearby),
    )
    context.restore()

    label(
      context,
      view,
      (from.x + to.x) / 2,
      (from.y + to.y) / 2,
      color,
      `${other.dist_m.toFixed(1)} ${DISTANCE_UNIT}`,
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
  // 라벨도 함께 키운다 — 박스만 굵게 하면 글자가 상대적으로 더 안 읽힌다.
  const size = view.unit * 13
  context.font = `700 ${size}px system-ui, sans-serif`
  const width = context.measureText(text).width
  const padding = size * 0.35
  const height = size * 1.5
  const top = Math.max(0, y - height)

  // 배경을 더 불투명하게. 밝은 영상 위에서 반투명 검정은 글자를 못 살린다.
  context.fillStyle = 'rgba(0, 0, 0, 0.82)'
  context.fillRect(x, top, width + padding * 2, height)
  context.strokeStyle = color
  context.lineWidth = Math.max(1, view.unit * 0.8)
  context.strokeRect(x, top, width + padding * 2, height)
  context.fillStyle = color
  context.fillText(text, x + padding, top + height - padding * 0.8)
}

/** 좌표가 끊겼다는 표시. 흐린 박스만으로는 "사람이 안 보인다"와 구분되지 않는다. */
function drawStaleBadge(context: CanvasRenderingContext2D, view: View, ageMs: number): void {
  context.save()
  context.globalAlpha = 1
  label(
    context,
    view,
    view.unit * 4,
    view.unit * 20,
    '#f59e0b',
    `좌표 지연 ${(ageMs / 1000).toFixed(1)}초 — 위치를 신뢰할 수 없다`,
  )
  context.restore()
}
