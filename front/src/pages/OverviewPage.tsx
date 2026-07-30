/**
 * 개요 (FN-UI-01 · 기능명세서 §4.6).
 *
 * 레이아웃은 `docs/AEGIS_front_design.pdf` 1페이지를 따르고, 용어는 명세서를 따른다
 * (부록 B — 「중장비 근접」이 아니라 「지게차 근접」).
 *
 * 이 화면에서 절대 틀리면 안 되는 것 셋:
 *
 * 1. **시정률의 `null` 은 `–` 다**(§6.7). `0%` 로 접으면 "판정 가능한 이벤트가 없다"가
 *    "아무도 시정하지 않았다"로 읽힌다. 대응이 정반대인 두 상황이다
 * 2. **판정 불가율을 나란히 표시한다**(§4.8 표기 규칙). 지표를 단독으로 제시하지 않는다
 * 3. **`suppressed`(방송 없이 확정된 건수)를 드러낸다**(§4.8). 그 값이 분모가 왜 줄었는지를
 *    설명한다 — 숨기면 시정률이 좋아 보이는 이유를 아무도 설명할 수 없다
 *
 * 추세·분포는 `GET /metrics/timeseries` · `/distribution`(M8)이 데이터원이다. 지금은
 * **최근 이벤트에서 계산할 수 있는 것만** 그린다 — 없는 API 를 흉내 내 가짜 곡선을
 * 그리지 않는다(그 곡선은 시연에서 사실처럼 보인다).
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchEvents } from '../api/events'
import { fetchMetricsSummary } from '../api/metrics'
import { subscribeDashboard } from '../api/system'
import { useSystemStatus } from '../api/useSystemStatus'
import {
  cameraName,
  clockTime,
  durationLabel,
  relativeTime,
  retentionLabel,
  statusLabel,
  violationLabel,
} from '../types/labels'
import {
  UNMEASURED,
  formatRate,
  isEventCreatedMsg,
  isEventUpdatedMsg,
  isMetricMsg,
  metricsAddUp,
  type EventSummary,
  type MetricsSummary,
  type ViolationType,
} from '../types/system'
import { STATUS_TONE, VIOLATION_LABEL } from '../types/labels'
import './overview.css'

/** 「최근 이벤트」에 띄우는 건수. 시안 1페이지가 세 건을 보여준다. */
const RECENT_LIMIT = 8

/** 유형 분포·추세를 계산할 표본. 하루치를 다 끌어오지 않고 최근 것만 본다. */
const SAMPLE_LIMIT = 200

export default function OverviewPage() {
  const { status, connected, error: statusError } = useSystemStatus()
  const [summary, setSummary] = useState<MetricsSummary | null>(null)
  const [recent, setRecent] = useState<EventSummary[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback((signal?: AbortSignal) => {
    // 지표와 목록을 함께 다시 읽는다. 한쪽만 갱신하면 "시정률 87%" 옆에 그 87%를
    // 만든 이벤트가 없는 화면이 된다.
    void Promise.all([fetchMetricsSummary(signal), fetchEvents({ limit: SAMPLE_LIMIT }, signal)])
      .then(([nextSummary, list]) => {
        setSummary(nextSummary)
        setRecent(list.items)
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

  // §5.3 `metric` 과 §5.2 `event_*` 가 오면 다시 읽는다. `metric` 에는 `suppressed` 가
  // 없으므로(§5.3 은 §4.2 의 부분집합) 메시지 값만으로 갱신하면 그 칸이 낡는다.
  useEffect(() => {
    return subscribeDashboard({
      onMessage: (message) => {
        if (isMetricMsg(message) || isEventCreatedMsg(message) || isEventUpdatedMsg(message)) {
          load()
        }
      },
    })
  }, [load])

  const distribution = useMemo(() => violationCounts(recent), [recent])
  const trend = useMemo(() => dailyCounts(recent), [recent])

  if (error && !summary) {
    return (
      <section className="card">
        <h2 className="card__title">개요</h2>
        <p className="card__note">
          지표를 읽지 못했다 — {error}
          <br />
          <code>uv run uvicorn server.app.main:app --reload</code> 와 DB 가 떠 있는지 확인해라.
        </p>
      </section>
    )
  }

  return (
    <div className="overview">
      <div className="overview__tiles">
        <Tile
          label="방송 후 시정률"
          value={formatRate(summary?.correction_rate ?? null)}
          /* ★ §4.8 표기 규칙 — 시정률과 판정 불가율은 항상 병기한다. */
          foot={`판정 불가 ${formatRate(summary?.undetermined_rate ?? null)}`}
          tone={rateTone(summary?.correction_rate ?? null)}
          hint="resolved / (resolved + resolved_late + unresolved) · 분모가 0이면 – 다"
        />
        <Tile
          label="오늘 위반"
          value={summary ? String(summary.total_violations) : UNMEASURED}
          unit="건"
          foot={
            summary
              ? `미해소 ${summary.unresolved}건 · 늦은 시정 ${summary.resolved_late}건`
              : '집계 없음'
          }
          hint="네 버킷(해소·늦은 시정·미시정·판정 불가)의 합이다"
        />
        <Tile
          label="평균 시정 시간"
          value={summary ? String(summary.avg_resolution_sec) : UNMEASURED}
          unit="초"
          foot="경고 방송 → 시정 확인"
          hint="alerted_at → resolved_at 평균. 해소된 건만 센다"
        />
        <Tile
          label="방송 없이 확정"
          value={summary ? String(summary.suppressed) : UNMEASURED}
          unit="건"
          /* ★ 이 값이 0이 아니면 시정률 분모가 그만큼 줄어 있다는 뜻이다. */
          foot={
            summary && summary.suppressed > 0
              ? '경고 일시중지 중 확정 · 시정률에서 제외'
              : '일시중지 중 확정된 건 없음'
          }
          tone={summary && summary.suppressed > 0 ? 'warn' : 'muted'}
          hint="alert_suppressed = true. 알린 적이 없으니 「방송 후」 시정률의 모집단이 아니다"
        />
      </div>

      {summary && !metricsAddUp(summary) && (
        <p className="overview__mismatch">
          ⚠ 지표 검산이 맞지 않는다 — 해소 {summary.resolved} + 늦은 시정{' '}
          {summary.resolved_late} + 미시정 {summary.unresolved} + 판정 불가{' '}
          {summary.undetermined} ≠ 전체 {summary.total_violations}. 서버 집계를 확인해라.
        </p>
      )}

      <div className="overview__row">
        <section className="card overview__panel">
          <header className="overview__head">
            <h2 className="card__title">위반 추세 · 최근 표본</h2>
            <span className="overview__hint">일별 발생</span>
          </header>
          {trend.length === 0 ? (
            <p className="card__note">표본이 없다. 이벤트가 쌓이면 그려진다.</p>
          ) : (
            <Sparkline points={trend} />
          )}
          <p className="card__note">
            최근 이벤트 {recent.length}건으로 그린 것이다. 기간 지표(<code>
              GET /metrics/timeseries
            </code>)는 분석 화면(FN-UI-05 · M8)과 함께 붙는다 — 없는 API 로 곡선을 지어내지
            않는다.
          </p>
        </section>

        <section className="card overview__panel overview__panel--narrow">
          <header className="overview__head">
            <h2 className="card__title">유형 분포</h2>
            <span className="overview__hint">최근 표본</span>
          </header>
          {distribution.total === 0 ? (
            <p className="card__note">표본이 없다.</p>
          ) : (
            <ul className="dist">
              {distribution.rows.map((row) => (
                <li key={row.type} className="dist__row">
                  <span className="dist__label">{VIOLATION_LABEL[row.type]}</span>
                  <span className="dist__bar">
                    <span
                      className={`dist__fill dist__fill--${row.type}`}
                      style={{ width: `${Math.round((row.count / distribution.max) * 100)}%` }}
                    />
                  </span>
                  <span className="dist__count">{row.count}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="overview__row">
        <section className="card overview__panel">
          <header className="overview__head">
            <h2 className="card__title">최근 이벤트</h2>
            <span className={`overview__hint ${connected ? '' : 'overview__hint--off'}`}>
              <span className={`dot dot--${connected ? 'ok' : 'danger'}`} />{' '}
              {connected ? '실시간' : '갱신 끊김'}
            </span>
          </header>
          {recent.length === 0 ? (
            <p className="card__note">확정된 이벤트가 없다.</p>
          ) : (
            <ul className="recent">
              {recent.slice(0, RECENT_LIMIT).map((event) => (
                <li key={event.event_id} className="recent__item">
                  <Link className="recent__link" to={`/events?event=${event.event_id}`}>
                    <span className={`recent__mark recent__mark--${event.violation_type}`} />
                    <span className="recent__body">
                      <span className="recent__title">
                        {violationLabel(event.violation_type)} · {cameraName(event.cam_id)}
                      </span>
                      <span className="recent__meta">
                        작업자 #{event.track_id}
                        {event.zone_id ? ` · ${event.zone_id}` : ''}
                        {event.min_distance_m !== null ? ` · ${event.min_distance_m}m` : ''}
                      </span>
                      <span className={`badge badge--${STATUS_TONE[event.status]}`}>
                        {event.status === 'resolved' && event.resolution_sec !== null
                          ? `${durationLabel(event.resolution_sec)} 만에 시정`
                          : statusLabel(event.status)}
                      </span>
                    </span>
                    <span className="recent__when" title={clockTime(event.detected_at)}>
                      {relativeTime(event.confirmed_at ?? event.detected_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card overview__panel overview__panel--narrow">
          <header className="overview__head">
            <h2 className="card__title">시스템 상태</h2>
            <Link className="overview__hint" to="/live">
              관제 화면
            </Link>
          </header>
          {statusError && !status ? (
            <p className="card__note">상태를 읽지 못했다 — {statusError}</p>
          ) : !status ? (
            <p className="card__note">불러오는 중…</p>
          ) : (
            <ul className="health">
              <HealthRow
                name="Jetson 엣지 추론"
                tone={status.edge.online ? 'ok' : 'danger'}
                value={
                  status.edge.online
                    ? `정상 · GPU ${percent(status.edge.gpu_util)}`
                    : '연결 끊김'
                }
              />
              <HealthRow
                name="카메라"
                tone={cameraTone(status.cameras.map((camera) => camera.main_state))}
                value={`메인 ${status.cameras.filter((c) => c.main_state === 'ok').length}/${
                  status.cameras.length
                } · 서브 ${status.cameras.filter((c) => c.sub_state === 'ok').length}/${
                  status.cameras.length
                }`}
              />
              <HealthRow
                name="ESP32 경고 장치"
                tone={status.mcu.online ? 'ok' : 'danger'}
                value={status.mcu.online ? '연결됨' : '보고 없음'}
              />
              <HealthRow
                name="클라우드 API"
                tone={status.cloud.available ? 'ok' : 'warn'}
                /* 클라우드가 죽어도 안전 기능은 무영향이다(FN-SYS-03). */
                value={
                  status.cloud.available
                    ? `정상 · 쿼터 ${percent(status.cloud.quota_used)}`
                    : '중단 — 분석만 멈춘다'
                }
              />
              <HealthRow
                name="영상 저장"
                tone={status.storage.free_gb === null ? 'muted' : 'ok'}
                value={
                  status.storage.free_gb === null
                    ? UNMEASURED
                    : `${status.storage.free_gb} GB 여유 · 보존 ${retentionLabel(
                        status.storage.retention_days,
                      )}`
                }
              />
              <HealthRow
                name="엣지 메시지 거부"
                /* FN-SYS-06 — 0이 아니면 감지된 위반이 검증에서 사라지고 있다. */
                tone={status.edge.msg_rejected_total > 0 ? 'danger' : 'ok'}
                value={`${status.edge.msg_rejected_total}건`}
              />
            </ul>
          )}
          <p className="card__note">
            <span className="overview__dim">{UNMEASURED}</span> 는 관측 주체가 없다는 뜻이며
            0 과 다르다(§4.6).
          </p>
        </section>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 조각들
// ---------------------------------------------------------------------------

type Tone = 'ok' | 'warn' | 'danger' | 'muted'

function Tile(props: {
  label: string
  value: string
  unit?: string
  foot: string
  tone?: Tone
  hint: string
}) {
  return (
    <section className={`tile tile--${props.tone ?? 'muted'}`} title={props.hint}>
      <span className="tile__label">{props.label}</span>
      <span className="tile__value">
        {props.value}
        {props.unit && <span className="tile__unit">{props.unit}</span>}
      </span>
      <span className="tile__foot">{props.foot}</span>
    </section>
  )
}

function HealthRow(props: { name: string; tone: Tone; value: string }) {
  return (
    <li className="health__row">
      <span className="health__name">{props.name}</span>
      <span className={`badge badge--${props.tone}`}>{props.value}</span>
    </li>
  )
}

/** 시안 1페이지의 면적 그래프. 표본이 적어도 모양이 무너지지 않게 정규화한다. */
function Sparkline({ points }: { points: { day: string; count: number }[] }) {
  const max = Math.max(...points.map((point) => point.count), 1)
  const width = 100
  const height = 40
  const step = points.length > 1 ? width / (points.length - 1) : 0
  const coords = points.map((point, index) => {
    const x = points.length > 1 ? index * step : width / 2
    const y = height - (point.count / max) * (height - 4) - 2
    return `${x.toFixed(2)},${y.toFixed(2)}`
  })
  const line = coords.join(' ')
  const area = `0,${height} ${line} ${width},${height}`
  return (
    <div className="spark">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img">
        <title>일별 위반 건수</title>
        <polygon className="spark__area" points={area} />
        <polyline className="spark__line" points={line} />
      </svg>
      <div className="spark__axis">
        {points.map((point) => (
          <span key={point.day}>{point.day.slice(5)}</span>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 표본 계산 — 없는 API 를 대신하는 것이 아니라, 가진 목록으로 셀 수 있는 것만 센다
// ---------------------------------------------------------------------------

function violationCounts(events: EventSummary[]): {
  rows: { type: ViolationType; count: number }[]
  total: number
  max: number
} {
  const counts = new Map<ViolationType, number>()
  for (const event of events) {
    counts.set(event.violation_type, (counts.get(event.violation_type) ?? 0) + 1)
  }
  const rows = [...counts.entries()]
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => b.count - a.count)
  return {
    rows,
    total: events.length,
    max: Math.max(...rows.map((row) => row.count), 1),
  }
}

function dailyCounts(events: EventSummary[]): { day: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const event of events) {
    const day = event.detected_at.slice(0, 10)
    counts.set(day, (counts.get(day) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([day, count]) => ({ day, count }))
    .sort((a, b) => a.day.localeCompare(b.day))
    .slice(-7)
}

function rateTone(rate: number | null): Tone {
  // `null` 은 좋지도 나쁘지도 않다 — 판정할 수 없었다는 뜻이므로 색으로 주장하지 않는다.
  if (rate === null) return 'muted'
  if (rate >= 0.8) return 'ok'
  return rate >= 0.5 ? 'warn' : 'danger'
}

function percent(value: number | null): string {
  return value === null ? UNMEASURED : `${Math.round(value * 100)}%`
}

function cameraTone(states: string[]): Tone {
  if (states.length === 0) return 'muted'
  if (states.every((state) => state === 'ok')) return 'ok'
  return states.some((state) => state === 'down') ? 'danger' : 'warn'
}
