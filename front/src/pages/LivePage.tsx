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

import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { subscribePolicies } from '../api/policies'
import { subscribeDashboard } from '../api/system'
import { useSystemStatus } from '../api/useSystemStatus'
import { applyZoneUpdate, fetchZones } from '../api/zones'
import ActiveEvents from '../live/ActiveEvents'
import CameraTile from '../live/CameraTile'
import QuickControls from '../live/QuickControls'
import { cameraName, retentionLabel, violationLabel } from '../types/labels'
import {
  UNMEASURED,
  isEventCreatedMsg,
  type EventCreatedMsg,
  type OverlayPolicies,
  type Zone,
} from '../types/system'
import '../live/live.css'
import '../pages/overview.css'
import '../pages/events.css'

/** 가장자리 알림 한 건. 확대 중이 아닌 채널에서 확정된 이벤트다. */
type EdgeAlert = {
  event_id: string
  cam_id: number
  label: string
}

export default function LivePage() {
  const { status, connected, error } = useSystemStatus()
  const [searchParams, setSearchParams] = useSearchParams()
  const [alerts, setAlerts] = useState<EdgeAlert[]>([])
  const [policies, setPolicies] = useState<OverlayPolicies | null>(null)
  const [zones, setZones] = useState<Zone[]>([])

  const cameras = status?.cameras ?? []

  // 개발용 정합 진단 표시. 확대 상태와 같이 URL 에 둔다 — 새로고침해도 유지되고,
  // 어긋난 화면을 캡처해 공유할 때 링크만으로 같은 상태를 재현할 수 있다.
  const debug = searchParams.get('debug') === '1'

  // 확대 상태도 URL 이 원본이다(`/live?cam=1`). 컴포넌트 state 에 두면 새로고침에
  // 날아간다 — 시연 중 실수로 새로고침해도 화면이 돌아가면 안 된다.
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

  return (
    <div className={solo === null ? 'live' : 'live live--solo'}>
      <div className="live__main">
        <div className="live__toolbar" role="group" aria-label="보기 전환">
          <button
            type="button"
            className={`live__view ${solo === null ? 'live__view--on' : ''}`}
            onClick={() => show(null)}
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

        <div className={solo === null ? 'live__grid' : 'live__grid live__grid--solo'}>
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

      <aside className="live__side">
        {/* 시안 2페이지 우측 — 진행 중 이벤트가 먼저, 그다음 빠른 제어다.
            스트림·저장소 상태는 그 아래로 내린다(관제 중 먼저 볼 것이 이벤트다). */}
        <ActiveEvents camIds={cameras.map((camera) => camera.cam_id)} />
        <QuickControls camIds={cameras.map((camera) => camera.cam_id)} />

        <section className="card">
          <h2 className="card__title">스트림 상태</h2>
          <table className="live__table">
            <thead>
              <tr>
                <th>카메라</th>
                <th>메인</th>
                <th>서브</th>
                <th>fps</th>
              </tr>
            </thead>
            <tbody>
              {status.cameras.map((camera) => (
                <tr key={camera.cam_id}>
                  <td>카메라 {camera.cam_id}</td>
                  <td className={`live__state live__state--${camera.main_state}`}>
                    {camera.main_state}
                  </td>
                  <td className={`live__state live__state--${camera.sub_state}`}>
                    {camera.sub_state}
                  </td>
                  {/* 엣지가 붙기 전에는 null 이다. 0 으로 그리면 장애처럼 보인다. */}
                  <td>{camera.fps === null ? UNMEASURED : camera.fps.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="card__note">
            메인은 서버가, 서브는 엣지가 관측한다. 메인이 끊겨도 추론은 계속되고 서브가
            끊겨도 녹화는 계속되므로 따로 표시한다.
          </p>
        </section>

        <section className="card">
          <h2 className="card__title">녹화 · 저장소</h2>
          <dl className="live__facts">
            <dt>용량</dt>
            <dd>{gb(status.storage.used_gb)} / {gb(status.storage.total_gb)}</dd>
            <dt>여유</dt>
            <dd>{gb(status.storage.free_gb)}</dd>
            <dt>보존</dt>
            <dd>{retentionLabel(status.storage.retention_days)}</dd>
            <dt>최고(最古)</dt>
            <dd>{recStamp(status.storage.oldest_segment_at)}</dd>
          </dl>
          <p className="card__note">
            REC(§4.7)이 보고한 값을 그대로 표시한다 — 서버 노트북의 디스크가 아니다.
            <br />
            <span className="live__unmeasured">{UNMEASURED}</span> 는 <b>측정 불가</b>다.
            REC 에 닿지 못했다는 뜻이며 0 과 다르다. 최고 세그먼트 시각은 영상 검색이
            가능한 범위의 하한이다.
          </p>
        </section>

        <section className="card">
          <h2 className="card__title">실시간 갱신</h2>
          <p className="card__note">
            <span className={`dot dot--${connected ? 'ok' : 'danger'}`} />{' '}
            {connected
              ? '/ws/dashboard 연결됨 — 상태 변화가 즉시 반영된다'
              : '/ws/dashboard 끊김 — 아래 값이 낡았을 수 있다'}
          </p>
        </section>
      </aside>
    </div>
  )
}

function gb(value: number | null): string {
  return value === null ? UNMEASURED : `${value} GB`
}

/**
 * REC 이 준 시각. **`null` 을 `—` 가 아니라 「측정 불가」로 그린다** — 여기서 `null` 은
 * "값이 없다"가 아니라 "REC 에 닿지 못했다"는 뜻이다(§4.6). 이벤트 시각의 `—`
 * (`types/labels.ts` 의 `stamp`)와 의미가 다르므로 함수를 나눠 둔다.
 */
function recStamp(value: string | null): string {
  if (value === null) return UNMEASURED
  const at = new Date(value)
  return Number.isNaN(at.getTime()) ? value : at.toLocaleString()
}
