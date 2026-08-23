/**
 * 실시간 관제 (FN-UI-02).
 *
 * 시안 2페이지 그대로 — 좌측 2채널 라이브(+오버레이 · 단독 확대), 우측 「진행 중
 * 이벤트」와 「빠른 제어」. M5 에서 우측 패널이 붙어 화면이 완성됐다.
 *
 * 오버레이가 필요로 하는 두 가지를 이 화면이 한 번만 읽어 타일에 나눠준다.
 *
 * * `GET /policies` — 재생 경로별 지연 버퍼(§4.5). 타일마다 따로 읽으면 두 타일이
 *   다른 값으로 그릴 수 있고, 그러면 어긋났을 때 무엇이 맞는지 알 수 없다
 * * `GET /zones` — 금지구역 폴리곤(§5.1). 매 프레임 변하지 않으므로 캐시하고
 *   `zone_updated`(§5.4)로 갱신한다
 *
 * 레이아웃은 `docs/AEGIS_front_design.pdf` 2페이지를 따르되, 용어는 기능명세서
 * 부록 B 대조표대로 제조현장 기준으로 쓴다.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { subscribePolicies } from '../api/policies'
import {
  ANOMALY_KEEP,
  anomalyTone,
  fetchAnomalies,
  mergeAnomalies,
  toItem,
  type AnomalyItem,
} from '../api/anomalies'
import { subscribeDashboard } from '../api/system'
import { useSystemStatus } from '../api/useSystemStatus'
import { applyZoneUpdate, fetchZones } from '../api/zones'
import ActiveEvents from '../live/ActiveEvents'
import CameraTile from '../live/CameraTile'
import DemoTile from '../live/DemoTile'
import AssistantChat from '../chat/AssistantChat'
import { useCameraName } from '../api/cameraNames'
import { violationLabel } from '../types/labels'
import {
  isAnomalyMsg,
  isEventCreatedMsg,
  type EventCreatedMsg,
  type OverlayPolicies,
  type Zone,
} from '../types/system'
import '../live/live.css'
import '../pages/overview.css'
import '../pages/events.css'
import '../pages/analysis.css'

/** 가장자리 알림 한 건. 확대 중이 아닌 채널에서 확정된 이벤트다. */
type EdgeAlert = {
  event_id: string
  cam_id: number
  label: string
}

/**
 * 우측 패널 폭 — 시연 중에 끌어서 조절한다(FN-UI-02).
 *
 * **최소값이 기본값이다.** 300px 이 이 패널이 제 역할을 하는 최소 폭이라(이벤트 한 줄에
 * 유형·트랙·상태가 다 들어가야 한다), 그보다 좁히면 줄바꿈이 생겨 훑어보는 용도를
 * 잃는다. 그래서 끌기는 **넓히는 방향으로만** 열어 둔다.
 *
 * 상한은 컨테이너에서 영상 몫을 뺀 값으로 매번 계산한다 — 고정 상수로 두면 좁은
 * 화면에서 영상이 사라진다.
 */
const SIDE_MIN_PX = 300
/** 영상이 최소한 확보해야 하는 폭. 타일 최소(360px)에 여백을 더한 값이다. */
const MAIN_MIN_PX = 420
/** 끌어 놓은 폭을 기억한다. 시연 중 새로고침으로 되돌아가면 다시 맞춰야 한다. */
const SIDE_WIDTH_KEY = 'aegis.live.sideWidth'

/**
 * 「전체 분할 보기」에 함께 띄우는 **녹화 영상**.
 *
 * 카메라를 여러 대 붙였을 때 관제 화면이 어떻게 보이는지를 시연에서 보여주기 위한
 * 자리다. **감지 파이프라인과 무관하다** — 박스는 영상에 이미 구워져 있고 엣지·서버·
 * 오버레이 어느 것도 거치지 않는다.
 *
 * 파일은 `media/` 에 둔다(git 에 올라가지 않는 런타임 저장소). 없으면 그 타일만
 * 검게 남고 나머지는 그대로 돈다.
 */
const DEMO_CLIPS: { file: string; name: string }[] = [
  { file: 'demo_result.mp4', name: '3번 카메라 · 포장 라인' },
  { file: 'demo_v2.mp4', name: '4번 카메라 · 입고장' },
  { file: 'result_combined.mp4', name: '5번 카메라 · 적재장' },
  { file: '4000_381_50epoch.mp4', name: '6번 카메라 · 출하장' },
]

export default function LivePage() {
  const cameraName = useCameraName()
  const { status, error } = useSystemStatus()
  const [searchParams, setSearchParams] = useSearchParams()
  const [alerts, setAlerts] = useState<EdgeAlert[]>([])
  // FN-AI-04 — **위반 알림과 다른 목록이다.** 같은 배열에 담으면 화면이 둘을 같은
  // 모양으로 그리게 되고, 그 순간 '주의'가 경고처럼 읽힌다.
  const [anomalies, setAnomalies] = useState<AnomalyItem[]>([])
  const [dismissed, setDismissed] = useState<number[]>([])
  const [policies, setPolicies] = useState<OverlayPolicies | null>(null)
  const [zones, setZones] = useState<Zone[]>([])
  const shellRef = useRef<HTMLDivElement>(null)
  const [sideWidth, setSideWidth] = useState(() => {
    const saved = Number(window.localStorage.getItem(SIDE_WIDTH_KEY))
    return Number.isFinite(saved) && saved >= SIDE_MIN_PX ? saved : SIDE_MIN_PX
  })

  const cameras = status?.cameras ?? []

  /**
   * 끌기로 우측 패널 폭을 정한다. 영상 쪽은 `1fr` 이라 자동으로 나머지를 먹는다.
   *
   * 포인터 이벤트를 캡처해 창 밖으로 끌어도 놓칠 때까지 이어진다 — `mousemove` 만
   * 쓰면 커서가 iframe·영상 위로 가는 순간 끌기가 끊긴다.
   */
  const startResize = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const shell = shellRef.current
    if (!shell) return
    event.preventDefault()
    const handle = event.currentTarget
    handle.setPointerCapture(event.pointerId)

    // 두 열이 아닌 것(간격 두 칸 + 손잡이 트랙)이 먹는 폭. **실측으로 뺀다** —
    // 상수로 적으면 CSS 의 `gap` 을 바꿀 때 조용히 어긋나고, 영상이 최소 폭 아래로
    // 내려간다(실측: 간격 32px + 손잡이 4px 를 빼지 않아 420 대신 384 까지 줄었다).
    const columns = shell.getBoundingClientRect().width
    const mainNow = shell.querySelector<HTMLElement>('.live__main')?.offsetWidth ?? 0
    const sideNow = shell.querySelector<HTMLElement>('.live__side')?.offsetWidth ?? 0
    const overhead = Math.max(0, columns - mainNow - sideNow)

    const move = (moved: PointerEvent) => {
      const box = shell.getBoundingClientRect()
      // 오른쪽 끝에서 커서까지가 곧 패널 폭이다.
      const raw = box.right - moved.clientX
      const max = Math.max(SIDE_MIN_PX, box.width - overhead - MAIN_MIN_PX)
      setSideWidth(Math.round(Math.min(max, Math.max(SIDE_MIN_PX, raw))))
    }
    const stop = () => {
      handle.removeEventListener('pointermove', move)
      handle.removeEventListener('pointerup', stop)
      handle.removeEventListener('pointercancel', stop)
      setSideWidth((current) => {
        window.localStorage.setItem(SIDE_WIDTH_KEY, String(current))
        return current
      })
    }
    handle.addEventListener('pointermove', move)
    handle.addEventListener('pointerup', stop)
    handle.addEventListener('pointercancel', stop)
  }, [])

  // 개발용 정합 진단 표시. 확대 상태와 같이 URL 에 둔다 — 새로고침해도 유지되고,
  // 어긋난 화면을 캡처해 공유할 때 링크만으로 같은 상태를 재현할 수 있다.
  const debug = searchParams.get('debug') === '1'

  // 확대 상태도 URL 이 원본이다(`/live?cam=1`). 컴포넌트 state 에 두면 새로고침에
  // 날아간다 — 시연 중 실수로 새로고침해도 화면이 돌아가면 안 된다.
  // 전체 분할 보기(시연용). 확대 상태와 같이 URL 에 둔다 — 새로고침해도 유지된다.
  const wall = searchParams.get('view') === 'wall'

  const requested = Number(searchParams.get('cam'))
  const solo =
    Number.isInteger(requested) && cameras.some((camera) => camera.cam_id === requested)
      ? requested
      : null

  const show = useCallback(
    (camId: number | null) => {
      const next = new URLSearchParams(searchParams)
      if (camId === null) next.delete('cam')
      else next.set('cam', String(camId))
      // 확대·복귀는 히스토리에 쌓지 않는다. 뒤로 가기가 시연 도중 페이지를 떠나게 된다.
      setSearchParams(next, { replace: true })
      if (camId !== null) setAlerts((current) => current.filter((item) => item.cam_id !== camId))
    },
    [searchParams, setSearchParams],
  )

  // Esc 로 분할 보기 복귀. 확대 중일 때만 듣는다.
  useEffect(() => {
    if (solo === null) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') show(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [solo, show])

  // 오버레이 지연 버퍼(§4.5). 값을 프론트에 적지 않는다(절대규칙 6).
  useEffect(() => subscribePolicies(setPolicies), [])

  // FN-AI-04 — 화면을 열 때 **한 번 조회한다.** WebSocket 만 보면 새로고침한 화면이
  // 텅 비고, 서버가 죽어 있던 동안의 이상은 영영 보이지 않는다.
  useEffect(() => {
    const controller = new AbortController()
    fetchAnomalies({ days: 1, limit: ANOMALY_KEEP }, controller.signal)
      .then((items) => setAnomalies((current) => mergeAnomalies(current, items)))
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        // 조용히 넘기지 않는다 — '주의'가 안 뜨는 이유가 여기일 수 있다(절대규칙 9).
        console.warn('[anomaly] 이상 목록을 읽지 못했다:', reason)
      })
    return () => controller.abort()
  }, [])

  // 금지구역은 한 번 조회해 캐시하고 `zone_updated` 로 갱신한다(§5.1 · §5.4).
  useEffect(() => {
    const controller = new AbortController()
    fetchZones(controller.signal)
      .then(setZones)
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        // 빈 배열로 두되 조용히 넘기지 않는다 — 구역 이름이 안 보이는 이유가 여기다.
        console.warn('[zones] 금지구역을 읽지 못했다:', reason)
      })
    return () => controller.abort()
  }, [])

  // **구독은 확대 여부와 무관하다.** 화면에서 내린 채널의 이벤트도 계속 받는다 —
  // 보이지 않는 것과 감시가 멈추는 것은 다르다. 소켓 자체도 `subscribeDashboard` 가
  // 화면 밖에서 하나로 유지하므로 타일을 내려도 끊기지 않는다.
  useEffect(() => {
    return subscribeDashboard({
      onMessage: (message) => {
        setZones((current) => applyZoneUpdate(current, message))
        if (isAnomalyMsg(message)) {
          // ★ 경고가 아니다(FN-AI-04). 소리도 내지 않고 배너만 띄운다.
          setAnomalies((current) => mergeAnomalies(current, [toItem(message)]))
          return
        }
        if (!isEventCreatedMsg(message)) return
        const event = message as EventCreatedMsg
        setAlerts((current) => {
          if (current.some((item) => item.event_id === event.event_id)) return current
          const label = violationLabel(event.violation_type)
          // 최신 3건까지만 띄운다. 그 이상은 가장자리를 덮어 영상을 가린다.
          return [...current, { event_id: event.event_id, cam_id: event.cam_id, label }].slice(-3)
        })
      },
    })
  }, [])

  if (error && !status) {
    return (
      <section className="card">
        <h2 className="card__title">실시간 관제</h2>
        <p className="card__note">
          서버 상태를 읽지 못했다 — {error}
          <br />
          <code>uv run uvicorn server.app.main:app --reload</code> 가 떠 있는지 확인해라.
        </p>
      </section>
    )
  }

  if (!status) {
    return (
      <section className="card">
        <h2 className="card__title">실시간 관제</h2>
        <p className="card__note">시스템 상태를 불러오는 중…</p>
      </section>
    )
  }

  const shown = solo === null ? cameras : cameras.filter((camera) => camera.cam_id === solo)
  // 확대 중이 아닌 채널의 알림만 띄운다. 보고 있는 채널은 영상에 그대로 나온다.
  const pending = solo === null ? [] : alerts.filter((alert) => alert.cam_id !== solo)
  // FN-AI-04 — 최근 '주의' 두 건. 확대 여부와 무관하게 띄운다(어느 채널이든 봐야 할
  // 것이 있다는 뜻이다). 사람이 닫으면 그 건은 다시 뜨지 않는다.
  const notices = anomalies
    .filter((item) => !dismissed.includes(item.anomaly_id))
    .slice(0, 2)

  return (
    <div
      ref={shellRef}
      className={solo === null ? 'live' : 'live live--solo'}
      style={{ ['--live-side-w' as string]: `${sideWidth}px` }}
    >
      <div className="live__main">
        <div className="live__toolbar" role="group" aria-label="보기 전환">
          <button
            type="button"
            className={`live__view ${solo === null && !wall ? 'live__view--on' : ''}`}
            onClick={() => {
              const next = new URLSearchParams(searchParams)
              next.delete('cam')
              next.delete('view')
              setSearchParams(next, { replace: true })
            }}
          >
            분할 보기
          </button>
          {cameras.map((camera) => (
            <button
              key={camera.cam_id}
              type="button"
              className={`live__view ${solo === camera.cam_id ? 'live__view--on' : ''}`}
              onClick={() => show(camera.cam_id)}
            >
              {cameraName(camera.cam_id)}
            </button>
          ))}
          {/* 시연용 — 녹화 영상을 함께 띄워 카메라를 여러 대 붙였을 때의 화면을 보인다. */}
          <button
            type="button"
            className={`live__view ${wall ? 'live__view--on' : ''}`}
            onClick={() => {
              const next = new URLSearchParams(searchParams)
              if (wall) next.delete('view')
              else {
                next.set('view', 'wall')
                next.delete('cam')
              }
              setSearchParams(next, { replace: true })
            }}
            title="녹화 영상을 함께 띄운다. 감지는 실시간 카메라에서만 돈다"
          >
            전체 분할 보기
          </button>
          <span className="live__spacer" />
          <button
            type="button"
            className={`live__view ${debug ? 'live__view--on' : ''}`}
            onClick={() => {
              const next = new URLSearchParams(searchParams)
              if (debug) next.delete('debug')
              else next.set('debug', '1')
              setSearchParams(next, { replace: true })
            }}
            title="재생 프레임 시각 · 그린 좌표 ts · 차이 · 적용 버퍼를 타일에 표시한다"
          >
            정합 진단
          </button>
          {solo !== null && <span className="live__hint">Esc 로 분할 보기</span>}
        </div>

        {/* ★ 이상 탐지 '주의'(FN-AI-04) — **위반 경고가 아니다.**
            경고 방송·경광등을 발동하지 않으며 조명·날씨로도 점수가 오른다. 그래서
            적색이 아니라 앰버이고, 문구도 단정하지 않는다(「평소와 다르다」). 아래
            `live__edge`(위반)와 **다른 색·다른 자리**여야 사람이 둘을 구분한다. */}
        {notices.length > 0 && (
          <div className="live__notices" aria-live="polite">
            {notices.map((notice) => (
              <div key={notice.anomaly_id} className={`notice notice--${anomalyTone(notice.score)}`}>
                <button
                  type="button"
                  className="notice__body"
                  onClick={() => show(notice.cam_id)}
                  title="이 카메라로 전환"
                >
                  <span className="notice__tag">주의</span>
                  <span className="notice__what">
                    {cameraName(notice.cam_id)} — 평소와 다른 상황
                    <em> (이상 점수 {notice.score.toFixed(2)})</em>
                  </span>
                  {/* 설명은 클라우드가 살아 있을 때만 붙는다(§5.3 `note` 는 nullable).
                      없다고 「이상 없음」이라고 쓰지 않는다 — 점수는 이미 넘었다. */}
                  {notice.note && <span className="notice__note">{notice.note}</span>}
                </button>
                <button
                  type="button"
                  className="notice__close"
                  aria-label="닫기"
                  onClick={() => setDismissed((current) => [...current, notice.anomaly_id])}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}

        <div
          className={
            solo !== null
              ? 'live__grid live__grid--solo'
              : wall
                ? 'live__grid live__grid--wall'
                : 'live__grid'
          }
        >
          {shown.map((camera) => (
            <CameraTile
              key={camera.cam_id}
              camera={camera}
              name={cameraName(camera.cam_id)}
              solo={solo === camera.cam_id}
              onToggleSolo={() => show(solo === camera.cam_id ? null : camera.cam_id)}
              policies={policies}
              zones={zones.filter((zone) => zone.cam_id === camera.cam_id)}
              debug={debug}
            />
          ))}
          {/* 실시간 타일 뒤에 붙인다 — 앞에 두면 시연 영상이 관제 화면의 주역처럼 보인다. */}
          {wall &&
            solo === null &&
            DEMO_CLIPS.map((clip) => (
              <DemoTile key={clip.file} file={clip.file} name={clip.name} />
            ))}
        </div>

        {pending.length > 0 && (
          <div className="live__edge" aria-live="polite">
            {pending.map((alert) => (
              <button
                key={alert.event_id}
                type="button"
                className="live__edge-item"
                onClick={() => show(alert.cam_id)}
              >
                <span className="live__edge-cam">{cameraName(alert.cam_id)}</span>
                <span className="live__edge-label">{alert.label}</span>
                <span className="live__edge-go">전환</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 끌어서 우측 패널 폭을 조절한다. **확대 보기에서도 남는다** — 확대한 채로
          챗봇에 묻는 것이 이 배치의 목적이므로, 그때도 폭을 조절할 수 있어야 한다. */}
      <div
        className="live__resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="우측 패널 폭 조절"
        onPointerDown={startResize}
        onDoubleClick={() => {
          setSideWidth(SIDE_MIN_PX)
          window.localStorage.setItem(SIDE_WIDTH_KEY, String(SIDE_MIN_PX))
        }}
        title="끌어서 폭 조절 · 두 번 눌러 기본값"
      >
        <span className="live__resizer-grip" />
      </div>

      <aside className="live__side">
        <ActiveEvents camIds={cameras.map((camera) => camera.cam_id)} />
        {/* 챗봇을 관제 화면에 둔다(FN-UI-06). 「지금 상황은?」을 물으면 현재 프레임을
            읽어 답하므로, 영상을 보면서 바로 물을 수 있어야 의미가 있다.
            **확대 보기에서도 남는다** — 화면을 키운 채로 묻는 것이 자연스럽다. */}
        <AssistantChat compact />
      </aside>
    </div>
  )
}
