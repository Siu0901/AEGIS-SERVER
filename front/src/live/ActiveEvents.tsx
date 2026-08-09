/**
 * 진행 중 이벤트 패널 (FN-UI-02 · FN-ALM-03).
 *
 * 시안 2페이지 우측 상단의 「진행 중 이벤트 · 자동 갱신」이다.
 *
 * **쓰러짐은 따로 띄운다**(FN-ALM-03). 대상자가 스스로 시정할 수 없으므로 목적이
 * 시정 유도가 아니라 **구조 대응**이고, 명세서는 「최상위 등급 알림 + 관리자 확인」을
 * 요구한다. 확인은 `PATCH /events/{id}` 의 `force_resolve` 다 — 쓰러짐을 관리자 확인으로
 * 종결하는 것이 기본 절차다(§4.1).
 *
 * **목록을 상태 질의로 받지 않는다.** `GET /events?status=` 는 값 하나만 받는데(§4.1)
 * 진행 중은 다섯 상태의 합집합이다. 상태별로 다섯 번 묻는 대신 최근 목록을 받아
 * 걸러낸다 — 종결되지 않은 이벤트가 최근 것 밖에 있을 수는 없다.
 */

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchEvents, patchEvent } from '../api/events'
import { subscribeDashboard } from '../api/system'
import { useMergedRefresh } from '../api/useRefresh'
import {
  STATUS_TONE,
  relativeTime,
  statusLabel,
  violationLabel,
} from '../types/labels'
import {
  isEventCreatedMsg,
  isEventUpdatedMsg,
  type EventStatus,
  type EventSummary,
} from '../types/system'
import { useCameraName } from '../api/cameraNames'

/** 종결되지 않은 상태(기능명세서 §4.2). 저장소의 `OPEN_STATUSES` 와 같은 집합이다. */
const OPEN: EventStatus[] = ['candidate', 'active', 'alerted', 're_alerted', 'lost']

/** 걸러낼 표본 크기. 진행 중 이벤트가 이보다 뒤에 있을 수는 없다. */
const SAMPLE = 60

export default function ActiveEvents({ camIds }: { camIds: number[] }) {
  const cameraName = useCameraName()
  const [open, setOpen] = useState<EventSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback((signal?: AbortSignal) => {
    void fetchEvents({ limit: SAMPLE }, signal)
      .then((page) => {
        setOpen(page.items.filter((event) => OPEN.includes(event.status)))
        setError(null)
      })
      .catch((cause: unknown) => {
        if (signal?.aborted) return
        setError(cause instanceof Error ? cause.message : String(cause))
      })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  // 한 전이가 §5.2 메시지를 여럿 만든다(확정 · 경고 · 해소 · 클립 준비). 그때마다
  // 목록을 다시 읽으면 전이 하나에 요청이 서너 개씩 붙어 서버 로그를 덮는다.
  const merged = useMergedRefresh(() => load())
  useEffect(() => {
    return subscribeDashboard({
      onMessage: (message) => {
        if (isEventCreatedMsg(message) || isEventUpdatedMsg(message)) merged()
      },
    })
  }, [merged])

  const acknowledge = (eventId: string) => {
    setBusy(eventId)
    // FN-ALM-03 — 관리자가 상황을 확인했다는 기록이다. 쓰러짐은 자력 시정이 불가능해
    // 시스템이 해소를 관측할 수 없으므로, 사람이 닫지 않으면 유예 만료로 `expired` 가
    // 되어 판정 불가율만 올라간다.
    void patchEvent(eventId, { force_resolve: true, note: '관리자 확인 — 구조 대응' })
      .then(() => load())
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause))
      })
      .finally(() => setBusy(null))
  }

  const falls = open.filter((event) => event.violation_type === 'fall')
  const others = open.filter((event) => event.violation_type !== 'fall')
  const quiet = camIds.filter((camId) => !open.some((event) => event.cam_id === camId))

  return (
    <section className="card active">
      <header className="active__head">
        <h2 className="card__title">진행 중 이벤트</h2>
        {/* 몇 건인지 적는다 — 목록이 5건에서 잘리므로 그 아래에 더 있다는 사실이
            숫자로 보여야 한다. */}
        {others.length > 0 && <span className="active__count">{others.length}건</span>}
      </header>

      {error && <p className="card__note events__error">{error}</p>}

      {/* ★ 최상위 등급 — 쓰러짐 (FN-ALM-03) */}
      {falls.map((event) => (
        <div key={event.event_id} className="urgent">
          <div className="urgent__title">긴급 · 쓰러짐 감지</div>
          <div className="urgent__meta">
            {cameraName(event.cam_id)} · 작업자 #{event.track_id} ·{' '}
            {relativeTime(event.confirmed_at ?? event.detected_at)}
          </div>
          <div className="urgent__actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy === event.event_id}
              onClick={() => acknowledge(event.event_id)}
            >
              관리자 확인
            </button>
            <Link className="btn" to={`/events?event=${event.event_id}`}>
              상세
            </Link>
          </div>
        </div>
      ))}

      {/* ★ **다섯 줄 자리를 처음부터 잡아 둔다.** 높이를 내용에 맡기면 이벤트가 하나씩
          들어올 때마다 이 카드가 자라면서 아래(챗봇)를 밀어낸다 — 관제 중에 화면이
          계속 움직이는 것이 이 패널에서 가장 거슬리는 부분이다. 그래서 비어 있을 때도
          같은 높이를 차지하고, 넘치면 **이 안에서만** 스크롤한다. */}
      <div className="active__scroll">
        {others.length === 0 && falls.length === 0 ? (
          <p className="card__note">진행 중인 이벤트가 없다.</p>
        ) : (
          <ul className="active__list">
            {others.map((event) => (
              <li key={event.event_id}>
                <Link className="active__item" to={`/events?event=${event.event_id}`}>
                  <span className={`rows__mark rows__mark--${event.violation_type}`} />
                  <span className="rows__body">
                    <span className="rows__title">{violationLabel(event.violation_type)}</span>
                    <span className="rows__meta">
                      #{event.track_id}
                      {event.zone_id ? ` · ${event.zone_id}` : ''} ·{' '}
                      {relativeTime(event.confirmed_at ?? event.detected_at)}
                    </span>
                    <span className={`badge badge--${STATUS_TONE[event.status]}`}>
                      {statusLabel(event.status)}
                      {event.alert_count > 1 ? ` · ${event.alert_count}회` : ''}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 이상 없는 채널도 적어 둔다 — 시안 2페이지가 「카메라 2 · 이상 없음」을 보여준다.
          진행 중 이벤트가 0건인 것과 그 카메라를 보고 있지 않은 것은 다르다. */}
      {quiet.length > 0 && (
        <ul className="active__quiet">
          {quiet.map((camId) => (
            <li key={camId}>
              <span className="rows__title">{cameraName(camId)}</span>
              <span className="badge badge--ok">이상 없음</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
