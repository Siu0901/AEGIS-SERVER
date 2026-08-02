/**
 * 이벤트 (FN-UI-03 · 기능명세서 §4.6 · API명세서 §4.1).
 *
 * 시안 3페이지 — 좌측 목록·필터, 우측 상세(클립 · 태그 · LLM 분석 · 유사 사례 ·
 * 규정 매핑 · 시정 타임라인). 용어는 부록 B 를 따른다(「중장비 근접」 아님).
 *
 * 이 화면의 판단들:
 *
 * · **선택 상태는 URL 에 둔다**(`/events?event=EV-...`). 개요 화면의 「최근 이벤트」가
 *   그 링크로 들어오고, 새로고침해도 같은 이벤트가 열려 있어야 한다
 * · **`clip_status` 로 재생 가능 여부를 판단한다.** `pending` 이면 클립 대신 키프레임을
 *   보여준다 — 아직 없는 파일에 `<video>` 를 붙이면 조용히 재생에 실패한다(§4.1 은
 *   그 상황에 404 를 준다)
 * · **LLM 분석 · 유사 사례 · 규정 매핑은 비어 있을 수 있다**(FN-AI-05·06·07). 값이 없는
 *   이유가 "아직 그 기능이 없다"임을 화면에 적는다 — 빈 칸은 "생성 실패"와 구분되지
 *   않는다(§4.6 null 규약)
 * · **`alert_suppressed` 를 상세에 표시한다.** 그 이벤트가 시정률에서 빠진 이유이며,
 *   표시하지 않으면 "미시정인데 왜 지표에 없나"를 설명할 수 없다(§4.8)
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { clipSrc, fetchEvent, fetchEvents, patchEvent, type EventQuery } from '../api/events'
import { subscribeDashboard } from '../api/system'
import { useMergedRefresh } from '../api/useRefresh'
import {
  CLIP_STATUS_LABEL,
  STATUS_TONE,
  VIOLATION_LABEL,
  clockTime,
  durationLabel,
  relativeTime,
  stamp,
  statusLabel,
  violationLabel,
} from '../types/labels'
import {
  isEventCreatedMsg,
  isEventUpdatedMsg,
  type EventDetail,
  type EventStatus,
  type EventSummary,
  type ViolationType,
} from '../types/system'
import './events.css'
import { useCameraName } from '../api/cameraNames'

/** 한 번에 불러오는 건수. 커서 페이징이므로 「더 보기」로 이어 받는다(§4.1). */
const PAGE_SIZE = 40

/** 시안 3페이지 상단의 필터 칩. 축이 서로 다르므로 한 번에 하나만 걸린다. */
type Chip =
  | { key: string; label: string; kind: 'all' }
  | { key: string; label: string; kind: 'type'; value: ViolationType }
  | { key: string; label: string; kind: 'status'; value: EventStatus }
  | { key: string; label: string; kind: 'cam'; value: number }
  | { key: string; label: string; kind: 'today' }

const CHIPS: Chip[] = [
  { key: 'all', label: '전체', kind: 'all' },
  { key: 'no_helmet', label: '안전모', kind: 'type', value: 'no_helmet' },
  { key: 'zone_intrusion', label: '금지구역', kind: 'type', value: 'zone_intrusion' },
  // ★ 시안은 「중장비 근접」이지만 명세서 용어는 「지게차 근접」이다(부록 B).
  { key: 'proximity', label: '지게차 근접', kind: 'type', value: 'proximity' },
  { key: 'fall', label: '쓰러짐', kind: 'type', value: 'fall' },
  { key: 'cam1', label: '카메라 1', kind: 'cam', value: 1 },
  { key: 'cam2', label: '카메라 2', kind: 'cam', value: 2 },
  { key: 'alerted', label: '미해소', kind: 'status', value: 'alerted' },
  { key: 'today', label: '오늘', kind: 'today' },
]

export default function EventsPage() {
  const cameraName = useCameraName()
  const [searchParams, setSearchParams] = useSearchParams()
  const [items, setItems] = useState<EventSummary[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const chipKey = searchParams.get('filter') ?? 'all'
  const selectedId = searchParams.get('event')
  const chip = useMemo(() => CHIPS.find((item) => item.key === chipKey) ?? CHIPS[0], [chipKey])
  const query = useMemo(() => toQuery(chip), [chip])

  const load = useCallback(
    (signal?: AbortSignal) => {
      setLoading(true)
      void fetchEvents({ ...query, limit: PAGE_SIZE }, signal)
        .then((page) => {
          setItems(page.items)
          setCursor(page.next_cursor)
          setListError(null)
        })
        .catch((cause: unknown) => {
          if (signal?.aborted) return
          setListError(cause instanceof Error ? cause.message : String(cause))
        })
        .finally(() => {
          if (!signal?.aborted) setLoading(false)
        })
    },
    [query],
  )

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  // 확정·전이가 일어나면 목록을 다시 읽는다(§5.2). 선택은 유지한다 — 보고 있던
  // 이벤트가 갱신 때문에 닫히면 시연 중에 다시 찾아야 한다.
  const mergedList = useMergedRefresh(() => load())
  useEffect(() => {
    return subscribeDashboard({
      onMessage: (message) => {
        if (isEventCreatedMsg(message) || isEventUpdatedMsg(message)) mergedList()
      },
    })
  }, [mergedList])

  const select = (eventId: string | null) => {
    const next = new URLSearchParams(searchParams)
    if (eventId === null) next.delete('event')
    else next.set('event', eventId)
    setSearchParams(next, { replace: true })
  }

  const pickChip = (key: string) => {
    const next = new URLSearchParams(searchParams)
    if (key === 'all') next.delete('filter')
    else next.set('filter', key)
    setSearchParams(next, { replace: true })
  }

  const more = () => {
    if (!cursor) return
    void fetchEvents({ ...query, limit: PAGE_SIZE, cursor })
      .then((page) => {
        setItems((current) => [...current, ...page.items])
        setCursor(page.next_cursor)
      })
      .catch((cause: unknown) => {
        setListError(cause instanceof Error ? cause.message : String(cause))
      })
  }

  return (
    <div className="events">
      <div className="events__filters" role="group" aria-label="필터">
        {CHIPS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`chip ${item.key === chip.key ? 'chip--on' : ''}`}
            onClick={() => pickChip(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="events__body">
        <section className="card events__list">
          {listError && (
            <p className="card__note events__error">목록을 읽지 못했다 — {listError}</p>
          )}
          {!listError && items.length === 0 && (
            <p className="card__note">{loading ? '불러오는 중…' : '해당하는 이벤트가 없다.'}</p>
          )}
          <ul className="rows">
            {items.map((event) => (
              <li key={event.event_id}>
                <button
                  type="button"
                  className={`rows__item ${event.event_id === selectedId ? 'rows__item--on' : ''}`}
                  onClick={() => select(event.event_id)}
                >
                  <span className={`rows__mark rows__mark--${event.violation_type}`} />
                  <span className="rows__body">
                    <span className="rows__title">{violationLabel(event.violation_type)}</span>
                    <span className="rows__meta">
                      {cameraName(event.cam_id)} · #{event.track_id}
                    </span>
                    <span className={`badge badge--${STATUS_TONE[event.status]}`}>
                      {event.status === 'resolved' && event.resolution_sec !== null
                        ? `${durationLabel(event.resolution_sec)} 만에 시정`
                        : statusLabel(event.status)}
                    </span>
                  </span>
                  <span className="rows__when">
                    {relativeTime(event.confirmed_at ?? event.detected_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {cursor && (
            <button type="button" className="events__more" onClick={more}>
              더 보기
            </button>
          )}
        </section>

        <EventDetailPanel eventId={selectedId} onRefreshList={load} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 상세
// ---------------------------------------------------------------------------

function EventDetailPanel({
  eventId,
  onRefreshList,
}: {
  eventId: string | null
  onRefreshList: () => void
}) {
  const cameraName = useCameraName()
  const [detail, setDetail] = useState<EventDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const reload = useCallback(
    (signal?: AbortSignal) => {
      if (!eventId) {
        setDetail(null)
        return
      }
      void fetchEvent(eventId, signal)
        .then((next) => {
          setDetail(next)
          setNote(next.note ?? '')
          setError(null)
        })
        .catch((cause: unknown) => {
          if (signal?.aborted) return
          setError(cause instanceof Error ? cause.message : String(cause))
        })
    },
    [eventId],
  )

  useEffect(() => {
    const controller = new AbortController()
    reload(controller.signal)
    return () => controller.abort()
  }, [reload])

  // 이 이벤트에 대한 §5.2 갱신만 반영한다(클립 준비 완료 · 상태 전이).
  const mergedDetail = useMergedRefresh(() => reload())
  useEffect(() => {
    if (!eventId) return
    return subscribeDashboard({
      onMessage: (message) => {
        if (isEventUpdatedMsg(message) && message.event_id === eventId) mergedDetail()
      },
    })
  }, [eventId, mergedDetail])

  const apply = (patch: Parameters<typeof patchEvent>[1], label: string) => {
    if (!eventId) return
    setBusy(true)
    void patchEvent(eventId, patch)
      .then(() => {
        reload()
        onRefreshList()
      })
      .catch((cause: unknown) => {
        setError(`${label} 실패 — ${cause instanceof Error ? cause.message : String(cause)}`)
      })
      .finally(() => setBusy(false))
  }

  if (!eventId) {
    return (
      <section className="card events__detail events__detail--empty">
        <p className="card__note">왼쪽 목록에서 이벤트를 고르면 상세가 열린다.</p>
      </section>
    )
  }

  if (error && !detail) {
    return (
      <section className="card events__detail">
        <p className="card__note events__error">상세를 읽지 못했다 — {error}</p>
      </section>
    )
  }

  if (!detail) {
    return (
      <section className="card events__detail">
        <p className="card__note">불러오는 중…</p>
      </section>
    )
  }

  const keyframe = detail.keyframe_urls[0] ?? detail.thumbnail_url
  const clipReady = detail.clip_status === 'ready'

  return (
    <section className="card events__detail">
      <header className="events__detail-head">
        <h2 className="card__title">이벤트 상세 · {detail.event_id}</h2>
        <span className="overview__hint">
          {violationLabel(detail.violation_type)} · {clockTime(detail.confirmed_at)}
        </span>
      </header>

      {error && <p className="card__note events__error">{error}</p>}

      {/* --- 클립 (FN-REC-03) --- */}
      <div className="clip">
        {clipReady ? (
          <video
            className="clip__video"
            src={clipSrc(detail.event_id)}
            poster={keyframe ?? undefined}
            controls
            preload="metadata"
          />
        ) : keyframe ? (
          <img className="clip__still" src={keyframe} alt="이벤트 키프레임" />
        ) : (
          <div className="clip__blank">그림이 아직 없다</div>
        )}
        <div className="clip__foot">
          <span>
            {clipReady
              ? `이벤트 클립 · 전후 각 10초 · ${cameraName(detail.cam_id)}`
              : /* pending 이면 키프레임으로 대체하고 그 이유를 적는다(기능명세서 §4.4). */
                '사후 구간이 녹화된 뒤 추출된다 — 그동안 키프레임을 보여준다'}
          </span>
          <span className={`badge badge--${clipReady ? 'ok' : 'muted'}`}>
            {detail.clip_status === null ? '예약 없음' : CLIP_STATUS_LABEL[detail.clip_status]}
          </span>
        </div>
        {detail.clip_error && (
          /* §6 `events.clip_error` — REC 이 준 사유를 그대로 보여준다. `note` 와 섞지 않는다. */
          <p className="clip__error">클립 실패 사유: {detail.clip_error}</p>
        )}
      </div>

      {/* --- 태그 --- */}
      <div className="tags">
        <span className={`tag tag--${detail.violation_type}`}>
          {VIOLATION_LABEL[detail.violation_type]}
        </span>
        {detail.zone_id && <span className="tag">{detail.zone_id}</span>}
        {detail.min_distance_m !== null && (
          <span className="tag">지게차 {detail.min_distance_m}m</span>
        )}
        {detail.posture !== null && detail.posture !== 'standing' && (
          <span className="tag tag--fall">자세 {detail.posture}</span>
        )}
        {detail.repeat_count_7d > 1 && (
          /* FN-EVT-06. ★ **작업자 개인 단위 누적이 아니다**(API명세서 §4.2) —
             `track_id` 는 세션 내 추적 번호일 뿐 신원이 아니다. 라벨과 툴팁이
             「이 사람이 4번」이 아니라 「이 자리에서 같은 위반이 4번」으로 읽히게 적는다. */
          <span
            className="tag tag--repeat"
            title="같은 구역·추적에서 관측된 동일 유형 위반 횟수다. 작업자 개인 단위 누적이 아니다."
          >
            같은 자리 7일 내 {detail.repeat_count_7d}회
          </span>
        )}
        {detail.helmet_conf !== null && (
          <span className="tag tag--dim">분류 신뢰도 {detail.helmet_conf}</span>
        )}
        {detail.depth_verified === true && <span className="tag tag--dim">뎁스 검증</span>}
        {detail.alert_suppressed && (
          /* ★ 이 이벤트가 시정률 모집단에서 빠진 이유다(§4.8). */
          <span className="tag tag--suppressed">방송 없음 · 시정률 제외</span>
        )}
      </div>

      {/* --- 시정 타임라인 (§4.1 timeline) --- */}
      <div className="timeline">
        <h3 className="events__sub">시정 타임라인</h3>
        {detail.timeline.length === 0 ? (
          <p className="card__note">전이 기록이 없다.</p>
        ) : (
          <ol className="timeline__list">
            {detail.timeline.map((entry) => (
              <li key={`${entry.state}-${entry.at}`} className="timeline__item">
                <span className={`timeline__dot timeline__dot--${STATUS_TONE[entry.state]}`} />
                <span className="timeline__when">{clockTime(entry.at)}</span>
                <span className="timeline__state">{statusLabel(entry.state)}</span>
              </li>
            ))}
          </ol>
        )}
        <dl className="facts">
          <dt>최초 경고</dt>
          <dd>{stamp(detail.alerted_at)}</dd>
          <dt>최근 경고</dt>
          {/* `alerted_at`(최초)과 분리되어 있다 — 덮으면 시정률이 부풀려진다(§5.2). */}
          <dd>
            {stamp(detail.last_alerted_at)}
            {detail.alert_count > 1 && ` (${detail.alert_count}회)`}
          </dd>
          <dt>시정 소요</dt>
          <dd>{durationLabel(detail.resolution_sec)}</dd>
        </dl>
      </div>

      {/* --- 지능 기능 (FN-AI-05 · 06 · 07) --- */}
      <div className="pending-panels">
        <section className="pending">
          <h4 className="pending__title">LLM 심층 분석</h4>
          {detail.llm_analysis ? (
            <p className="pending__body">{detail.llm_analysis}</p>
          ) : (
            /* ★ 비어 있는 것과 기능이 없는 것은 다르다. 클라우드가 죽어도 안전
               기능은 무영향이므로(FN-SYS-03) 이 칸만 비는 것이 정상 경로다. */
            <p className="pending__why">
              아직 없다 — 확정 직후 배경에서 생성된다. 클라우드가 꺼져 있으면 비어 있고,
              그래도 감지 → 경고 → 시정 판정은 정상 동작한다(FN-SYS-03).
            </p>
          )}
        </section>

        <section className="pending">
          <h4 className="pending__title">유사 사고사례</h4>
          {detail.similar_incidents.length > 0 ? (
            <ul className="pending__list">
              {detail.similar_incidents.map((item) => (
                <li key={item.title}>
                  <span>{item.title}</span>
                  {/* 유사도는 **잰 값**이다. 없는 항목은 애초에 실리지 않는다(§4.3). */}
                  <em>
                    {item.source} · 유사도 {Math.round(item.similarity * 100)}%
                  </em>
                </li>
              ))}
            </ul>
          ) : (
            <p className="pending__why">
              아직 없다 — 키프레임 임베딩으로 확정 시 1회 매칭한다(FN-AI-07). 임베딩이
              없으면 <strong>유사도를 지어내지 않고 비워 둔다</strong>.
            </p>
          )}
        </section>

        <section className="pending">
          <h4 className="pending__title">규정 매핑</h4>
          {detail.regulation_refs.length > 0 ? (
            <ul className="pending__list">
              {detail.regulation_refs.map((item) => (
                <li key={item.code}>
                  <span>{item.code}</span>
                  <em>{item.title}</em>
                </li>
              ))}
            </ul>
          ) : (
            <p className="pending__why">
              아직 없다 — 위반 유형 → 조항은 <strong>사전 매핑 테이블</strong>로 연결되며
              LLM 이 조항을 생성하지 않는다(FN-AI-06). 이 칸은 클라우드와 무관하다.
            </p>
          )}
        </section>
      </div>

      {/* --- 수동 정정 (FN-EVT-05) --- */}
      <div className="correct">
        <h3 className="events__sub">수동 정정</h3>
        <label className="correct__field">
          <span>관리자 메모</span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={2}
            placeholder="오탐 사유 등"
          />
        </label>
        <div className="correct__buttons">
          <button
            type="button"
            className="btn"
            disabled={busy || note === (detail.note ?? '')}
            onClick={() => apply({ note }, '메모 저장')}
          >
            메모 저장
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy || detail.status === 'resolved'}
            /* `fall` 은 관리자 확인으로 종결하는 것이 기본 절차다(§4.1). */
            onClick={() => apply({ force_resolve: true }, '강제 종결')}
          >
            강제 종결
          </button>
          <button
            type="button"
            className="btn btn--danger"
            disabled={busy}
            onClick={() => apply({ is_false_positive: true, note }, '오탐 표시')}
          >
            오탐으로 표시
          </button>
        </div>
        <p className="card__note">
          오탐으로 표시한 이벤트는 시정률에서 <b>전량 제외</b>된다(§4.8). 강제 종결은 시스템이
          놓친 시정을 사람이 닫는 것이고, 쓰러짐은 이 절차로 종결하는 것이 기본이다.
        </p>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------

function toQuery(chip: Chip): EventQuery {
  switch (chip.kind) {
    case 'type':
      return { type: chip.value }
    case 'status':
      return { status: chip.value }
    case 'cam':
      return { cam_id: chip.value }
    case 'today':
      // 저장은 UTC 다(§1.2). 「오늘」의 경계를 로컬 자정으로 잡으면 지표 화면(UTC 기준)과
      // 목록이 서로 다른 하루를 보게 되므로 여기서도 UTC 자정으로 끊는다.
      return { from: utcMidnight() }
    default:
      return {}
  }
}

function utcMidnight(): string {
  const now = new Date()
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())).toISOString()
}
