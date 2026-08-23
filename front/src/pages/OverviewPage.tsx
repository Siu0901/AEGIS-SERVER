/**
 * 개요 (FN-UI-01 · 기능명세서 §4.6).
 *
 * 레이아웃은 `docs/AEGIS_front_design.pdf` 1페이지를 따르고, 용어는 명세서를 따른다
 * (부록 B — 「중장비 근접」이 아니라 「지게차 근접」. 단 화면 표기는 시연용으로
 * 「트럭 근접」이다 — `types/labels.ts` 참조).
 *
 * 이 화면에서 절대 틀리면 안 되는 것 셋:
 *
 * 1. **시정률의 `null` 은 `–` 다**(§6.7). `0%` 로 접으면 "판정 가능한 이벤트가 없다"가
 *    "아무도 시정하지 않았다"로 읽힌다. 대응이 정반대인 두 상황이다
 * 2. **판정 불가율을 나란히 표시한다**(§4.8 표기 규칙). 지표를 단독으로 제시하지 않는다
 * 3. **`suppressed`(방송 없이 확정된 건수)를 드러낸다**(§4.8). 그 값이 분모가 왜 줄었는지를
 *    설명한다 — 숨기면 시정률이 좋아 보이는 이유를 아무도 설명할 수 없다
 *
 * 추세·분포의 데이터원은 `GET /metrics/timeseries` · `/distribution` 이다(M8 에서 붙었다).
 * **최근 이벤트 목록으로 세지 않는다** — 그 목록은 페이지 크기만큼만 담기므로 표본이
 * 잘린 줄 모르고 "7일 추세"라고 부르게 된다. 실제로 M5~M7 동안 그렇게 그렸고, 화면에는
 * 그 사실이 각주로만 있었다.
 *
 * **분석 화면(FN-UI-05)과 같은 API 를 본다.** 두 화면이 다른 숫자를 말하면 어느 쪽이
 * 맞는지 가릴 방법이 없다.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchDistribution, fetchTimeseries } from '../api/analysis'
import { fetchEvents } from '../api/events'
import { fetchMetricsSummary } from '../api/metrics'
import { subscribeDashboard } from '../api/system'
import { useMergedRefresh } from '../api/useRefresh'
import { useSystemStatus } from '../api/useSystemStatus'
import {
  clockTime,
  durationLabel,
  relativeTime,
  retentionLabel,
  statusLabel,
  violationLabel,
} from '../types/labels'
import type { DistributionBucket, TimeSyncStatus, TimeseriesPoint } from '../types/contracts'
import {
  UNMEASURED,
  formatRate,
  isEventCreatedMsg,
  isEventUpdatedMsg,
  isMetricMsg,
  metricsAddUp,
  type EventSummary,
  type MetricsSummary,
} from '../types/system'
import { STATUS_TONE } from '../types/labels'
import './overview.css'
import { useCameraName } from '../api/cameraNames'

/** 「최근 이벤트」에 띄우는 건수. 시안 1페이지가 세 건을 보여준다. */
const RECENT_LIMIT = 8

/** 「최근 이벤트」 목록만 이만큼 받는다. **집계에는 쓰지 않는다** — 집계는 §4.2 다. */
const RECENT_FETCH = 20

/** 추세 창(일). 시안 1페이지의 스파크라인이 한 주치다. */
const TREND_DAYS = 7

/** 이 값을 넘으면 시각 경고(§4.5 `clock_offset_warn_ms` 기본). 서버가 판정하고
 *  화면은 같은 기준으로 색만 맞춘다 — 두 값이 갈리면 배너와 등급이 어긋난다. */
const CLOCK_WARN_MS = 100

export default function OverviewPage() {
  const cameraName = useCameraName()
  const { status, connected, error: statusError } = useSystemStatus()
  const [summary, setSummary] = useState<MetricsSummary | null>(null)
  const [recent, setRecent] = useState<EventSummary[]>([])
  const [trend, setTrend] = useState<TimeseriesPoint[]>([])
  const [distribution, setDistribution] = useState<DistributionBucket[]>([])
  const [error, setError] = useState<string | null>(null)

  /** 추세·분포가 보는 구간. 지금부터 `TREND_DAYS` 일 전까지다. */
  const period = useMemo(() => {
    const to = new Date()
    const from = new Date(to.getTime() - TREND_DAYS * 24 * 3600 * 1000)
    return { from: from.toISOString(), to: to.toISOString() }
  }, [])

  const load = useCallback(
    (signal?: AbortSignal) => {
      // 넷을 함께 읽는다. 한쪽만 갱신하면 "시정률 87%" 옆에 그 87%를 만든 이벤트가
      // 없는 화면이 된다.
      void Promise.all([
        fetchMetricsSummary(signal),
        fetchEvents({ limit: RECENT_FETCH }, signal),
        fetchTimeseries({ metric: 'violations', bucket: 'day', ...period }, signal),
        fetchDistribution({ by: 'violation_type', ...period }, signal),
      ])
        .then(([nextSummary, list, points, buckets]) => {
          setSummary(nextSummary)
          setRecent(list.items)
          setTrend(points.points)
          setDistribution(buckets.buckets)
          setError(null)
        })
        .catch((cause: unknown) => {
          if (signal?.aborted) return
          setError(cause instanceof Error ? cause.message : String(cause))
        })
    },
    [period],
  )

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  // §5.3 `metric` 은 **그 자체로 완결이다.** `suppressed` 가 실리면서 §4.2 응답과
  // 같은 칸을 전부 갖게 됐으므로, 받은 값을 그대로 쓰고 지표를 다시 읽지 않는다 —
  // 종결 전이마다 나가던 요청 하나가 사라졌다.
  //
  // 목록(`GET /events`)은 여전히 다시 읽어야 한다. `event_*` 는 이벤트 하나의 변화만
  // 알려주고 최근 목록의 정렬까지는 담고 있지 않다. 한 전이가 여러 메시지를 만들므로
  // 그 요청은 병합한다.
  const merged = useMergedRefresh(() => {
    // 목록과 함께 추세·분포도 다시 읽는다. 지표 타일만 §5.3 `metric` 으로 즉시
    // 갱신되고 그래프가 옛 값에 머물면, 같은 화면 안에서 두 숫자가 어긋난다.
    void Promise.all([
      fetchEvents({ limit: RECENT_FETCH }),
      fetchTimeseries({ metric: 'violations', bucket: 'day', ...period }),
      fetchDistribution({ by: 'violation_type', ...period }),
    ])
      .then(([list, points, buckets]) => {
        setRecent(list.items)
        setTrend(points.points)
        setDistribution(buckets.buckets)
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause))
      })
  })
  useEffect(() => {
    return subscribeDashboard({
      onMessage: (message) => {
        if (isMetricMsg(message)) {
          const { type: _type, ...metrics } = message
          setSummary(metrics)
          return
        }
        if (isEventCreatedMsg(message) || isEventUpdatedMsg(message)) {
          merged()
        }
      },
    })
  }, [merged])

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
          hint="경고 방송이 나간 뒤 실제로 시정된 비율"
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
          hint="오늘 확정된 위반 건수"
        />
        <Tile
          label="평균 시정 시간"
          value={summary ? String(summary.avg_resolution_sec) : UNMEASURED}
          unit="초"
          foot="경고 방송 → 시정 확인"
          hint="경고 방송부터 시정 확인까지 걸린 평균 시간"
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
          hint="경고 방송이 나가지 않은 건이라 시정률 계산에서 빠진다"
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
            <h2 className="card__title">위반 추세</h2>
            <span className="overview__hint">최근 {TREND_DAYS}일 · 일별 발생</span>
          </header>
          {trend.length === 0 ? (
            <p className="card__note">이 기간에 이벤트가 없다.</p>
          ) : (
            <Sparkline points={trend} />
          )}
          <p className="card__note">
            최근 {TREND_DAYS}일이다. 자세한 추이는{' '}
            <Link to="/analysis">분석 화면</Link>에 있다.
          </p>
        </section>

        <section className="card overview__panel overview__panel--narrow">
          <header className="overview__head">
            <h2 className="card__title">유형 분포</h2>
            <span className="overview__hint">최근 {TREND_DAYS}일</span>
          </header>
          {distribution.length === 0 ? (
            <p className="card__note">이 기간에 이벤트가 없다.</p>
          ) : (
            <ul className="dist">
              {distribution.map((bucket) => (
                <li key={bucket.key} className="dist__row">
                  {/* 서버가 라벨을 함께 내려주지만(§4.2) 용어 표는 화면 쪽에 있다
                      (`types/labels.ts`). 시안의 「중장비 근접」이 아니고, 명세서의
                      「지게차 근접」을 시연용으로 「트럭 근접」으로 띄운다. */}
                  <span className="dist__label">{violationLabel(bucket.key)}</span>
                  <span className="dist__bar">
                    <span
                      className={`dist__fill dist__fill--${bucket.key}`}
                      /* `ratio` 는 전체 대비다. 막대는 **최댓값 기준**으로 그려야 작은
                         항목이 보이므로 여기서만 다시 정규화한다. 서버가 건수 내림차순으로
                         주므로 첫 항목이 최댓값이다. */
                      style={{
                        width: `${Math.round((bucket.count / distribution[0].count) * 100)}%`,
                      }}
                    />
                  </span>
                  <span className="dist__count">{bucket.count}</span>
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
              <HealthRow
                name="시각 동기화"
                /* ★ FN-SYS-02 — 이 실패는 조용하다. 시각이 어긋난 상태에서 잘라낸
                   클립은 정상적으로 생성되고 재생되지만 **다른 구간을 담는다.**
                   사람이 열어보기 전까지 드러나지 않으므로 상시 노출한다(§4.6). */
                tone={clockTone(status.time_sync)}
                value={clockValue(status.time_sync)}
              />
            </ul>
          )}
          <p className="card__note">
            <span className="overview__dim">{UNMEASURED}</span> 는 값을 읽지 못했다는 뜻이며
            0 과 다르다.
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
function Sparkline({ points }: { points: TimeseriesPoint[] }) {
  const max = Math.max(...points.map((point) => point.value), 1)
  const width = 100
  const height = 40
  const step = points.length > 1 ? width / (points.length - 1) : 0
  const coords = points.map((point, index) => {
    const x = points.length > 1 ? index * step : width / 2
    const y = height - (point.value / max) * (height - 4) - 2
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
          // `t` 는 버킷 시작이고 형식은 `bucket` 에 따라 다르다(§4.2). 여기는 `day` 라
          // `YYYY-MM-DD` 이므로 월-일만 잘라 쓴다. 표본 크기는 툴팁에 남긴다.
          <span key={point.t} title={`${point.t} · ${point.n}건`}>
            {point.t.slice(5)}
          </span>
        ))}
      </div>
    </div>
  )
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

/**
 * 시각 동기화 등급 (FN-SYS-02 · §4.6).
 *
 * 세 가지를 구분한다 — 「엣지가 없다」(`null`) · 「엣지는 있는데 시계를 못 맞췄다」
 * (`edge_synced === false`) · 「맞췄고 오차가 이만큼이다」. 셋을 하나로 합치면 클립
 * 구간을 믿어도 되는지 알 수 없다.
 */
function clockTone(sync: TimeSyncStatus): Tone {
  if (sync.edge_synced === false) return 'danger'
  if (sync.edge_offset_ms === null) return 'muted'
  return Math.abs(sync.edge_offset_ms) > CLOCK_WARN_MS ? 'warn' : 'ok'
}

function clockValue(sync: TimeSyncStatus): string {
  const server =
    sync.server_offset_ms === null ? '' : ` · 서버 ${sync.server_offset_ms.toFixed(1)}ms`
  if (sync.edge_synced === false) return `엣지 동기화 실패 — 클립 구간 신뢰 불가${server}`
  if (sync.edge_offset_ms === null) return `엣지 ${UNMEASURED}${server}`
  return `엣지 ${sync.edge_offset_ms > 0 ? '+' : ''}${sync.edge_offset_ms}ms${server}`
}

function cameraTone(states: string[]): Tone {
  if (states.length === 0) return 'muted'
  if (states.every((state) => state === 'ok')) return 'ok'
  return states.some((state) => state === 'down') ? 'danger' : 'warn'
}
