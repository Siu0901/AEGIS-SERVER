/**
 * 분석 · 보고서 (FN-UI-05 · API명세서 §4.2 · §4.4).
 *
 * 시정률 추이 · 반복 위반 순위 · 시간대 히트맵 · 유형 분포 · 이상 탐지 · 보고서 생성.
 *
 * 이 화면의 판단들:
 *
 * · ★ **시정률과 판정 불가율을 병기한다**(§6.7 표기 규칙). 추이 그래프도 두 계열을
 *   함께 그린다 — 시정률만 보면 그 숫자가 무엇을 세지 않았는지 알 수 없다
 * · ★ **`null` 은 `–` 다.** 분모가 빈 구간에는 점을 찍지 않고 선도 잇지 않는다.
 *   0% 로 접으면 이벤트가 없던 날이 「아무도 시정하지 않은 날」로 보인다
 * · **표본 크기(`n`)를 함께 보여준다.** 3건짜리 100% 와 40건짜리 87% 를 같은 굵기로
 *   그리면 안 된다(§4.2 가 `n` 을 함께 내려주는 이유다)
 * · **반복 순위의 `track` 축을 「작업자」라고 부르지 않는다**(§4.2). 추적 번호는
 *   신원이 아니고 카메라를 벗어나면 유효하지 않다
 * · **이상 탐지는 '주의'다**(FN-AI-04). 위반과 같은 색으로 그리지 않는다 — 조명·날씨로도
 *   점수가 오르고, 경고 방송은 애초에 나가지 않는다
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  fetchDistribution,
  fetchRepeat,
  fetchReport,
  fetchTimeseries,
  requestWeeklyReport,
  type WeeklyReport,
} from '../api/analysis'
import { fetchMetricsSummary } from '../api/metrics'
import type {
  DistributionBucket,
  MetricBucket,
  RepeatItem,
  TimeseriesPoint,
} from '../types/contracts'
import { stamp, violationLabel } from '../types/labels'
import { formatRate, formatRatePair, type MetricsSummary } from '../types/system'
import './analysis.css'

/** 추이 기간 선택. 시연에서 하루치와 한 주치를 모두 보여줄 수 있어야 한다. */
const RANGES: { label: string; days: number; bucket: MetricBucket }[] = [
  { label: '24시간', days: 1, bucket: 'hour' },
  { label: '7일', days: 7, bucket: 'day' },
  { label: '30일', days: 30, bucket: 'day' },
]

/** 보고서 생성 상태를 다시 묻는 간격(ms). §4.4 예상 20초의 1/10 이다. */
const REPORT_POLL_MS = 2000

export default function AnalysisPage() {
  const [rangeIndex, setRangeIndex] = useState(1)
  const range = RANGES[rangeIndex]

  const [summary, setSummary] = useState<MetricsSummary | null>(null)
  const [correction, setCorrection] = useState<TimeseriesPoint[]>([])
  const [undetermined, setUndetermined] = useState<TimeseriesPoint[]>([])
  const [byType, setByType] = useState<DistributionBucket[]>([])
  const [byHour, setByHour] = useState<DistributionBucket[]>([])
  const [byZone, setByZone] = useState<DistributionBucket[]>([])
  const [repeat, setRepeat] = useState<RepeatItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<WeeklyReport | null>(null)
  const [reportBusy, setReportBusy] = useState(false)
  const pollRef = useRef<number | null>(null)

  const period = useMemo(() => {
    const to = new Date()
    const from = new Date(to.getTime() - range.days * 24 * 3600 * 1000)
    return { from: from.toISOString(), to: to.toISOString() }
  }, [range.days])

  useEffect(() => {
    const controller = new AbortController()
    const signal = controller.signal
    setError(null)
    void (async () => {
      try {
        const [rate, undet, types, hours, zones, repeats, totals] = await Promise.all([
          fetchTimeseries({ metric: 'correction_rate', bucket: range.bucket, ...period }, signal),
          fetchTimeseries(
            { metric: 'undetermined_rate', bucket: range.bucket, ...period },
            signal,
          ),
          fetchDistribution({ by: 'violation_type', ...period }, signal),
          fetchDistribution({ by: 'hour_of_day', ...period }, signal),
          fetchDistribution({ by: 'zone', ...period }, signal),
          fetchRepeat({ days: range.days, limit: 10 }, signal),
          fetchMetricsSummary(signal),
        ])
        setCorrection(rate.points)
        setUndetermined(undet.points)
        setByType(types.buckets)
        setByHour(hours.buckets)
        setByZone(zones.buckets)
        setRepeat(repeats.items)
        setSummary(totals)
      } catch (cause) {
        if (signal.aborted) return
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    })()
    return () => controller.abort()
  }, [range.bucket, range.days, period])

  // 보고서는 배경에서 만들어진다(§4.4). 완성될 때까지 상태만 다시 묻는다.
  const poll = useCallback((reportId: string) => {
    if (pollRef.current !== null) window.clearInterval(pollRef.current)
    pollRef.current = window.setInterval(() => {
      void (async () => {
        try {
          const found = await fetchReport(reportId)
          setReport(found)
          if (found.status !== 'generating' && pollRef.current !== null) {
            window.clearInterval(pollRef.current)
            pollRef.current = null
            setReportBusy(false)
          }
        } catch {
          // 조회 실패는 다음 주기에 다시 시도한다. 생성 자체는 서버에서 돌고 있다.
        }
      })()
    }, REPORT_POLL_MS)
  }, [])

  useEffect(
    () => () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current)
    },
    [],
  )

  const makeReport = async () => {
    setReportBusy(true)
    try {
      const id = await requestWeeklyReport(
        period.from.slice(0, 10),
        period.to.slice(0, 10),
      )
      setReport({ report_id: id, status: 'generating', from: '', to: '', body: null })
      poll(id)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
      setReportBusy(false)
    }
  }

  return (
    <div className="analysis">
      <section className="card">
        <div className="analysis__head">
          <h2 className="card__title">분석 · 보고서</h2>
          <div className="settings__tabs">
            {RANGES.map((item, index) => (
              <button
                key={item.label}
                type="button"
                className={index === rangeIndex ? 'chip chip--on' : 'chip'}
                onClick={() => setRangeIndex(index)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
        {error && <p className="analysis__error">{error}</p>}
        {/* ★ 시정률을 단독으로 제시하지 않는다(§6.7 표기 규칙). */}
        <dl className="analysis__facts">
          <div>
            <dt>방송 후 시정률</dt>
            <dd className="analysis__headline">
              {summary
                ? formatRatePair(summary.correction_rate, summary.undetermined_rate)
                : '–'}
            </dd>
          </div>
          <div>
            <dt>모집단</dt>
            <dd>{summary ? `${summary.total_violations}건` : '–'}</dd>
          </div>
          <div>
            <dt>평균 시정</dt>
            <dd>{summary ? `${summary.avg_resolution_sec}초` : '–'}</dd>
          </div>
          <div>
            <dt>이상 탐지</dt>
            <dd>{summary ? `${summary.anomaly_flags}건 주의` : '–'}</dd>
          </div>
        </dl>
      </section>

      <section className="card">
        <h2 className="card__title">시정률 추이</h2>
        <RateChart correction={correction} undetermined={undetermined} />
        <p className="card__note">
          ★ 판정 불가율을 함께 그린다(§6.7). 모집단이 빈 구간은 <strong>점이 없다</strong> —
          0% 로 찍으면 이벤트가 없던 구간이 「아무도 시정하지 않았다」로 보인다.
        </p>
      </section>

      <div className="analysis__row">
        <section className="card">
          <h2 className="card__title">위반 유형 분포</h2>
          <BarList buckets={byType} translate />
        </section>
        <section className="card">
          <h2 className="card__title">구역 분포</h2>
          <BarList buckets={byZone} />
        </section>
      </div>

      <section className="card">
        <h2 className="card__title">시간대 히트맵</h2>
        <Heatmap buckets={byHour} />
        <p className="card__note">
          `by=hour_of_day` 는 <code>&quot;00&quot;</code>~<code>&quot;23&quot;</code> 을 키로 쓴다.
          UTC 기준으로 자르므로 서버를 어디에 두든 같은 칸에 떨어진다.
        </p>
      </section>

      <section className="card">
        <h2 className="card__title">반복 위반 순위 (최근 {range.days}일)</h2>
        {repeat.length === 0 ? (
          <p className="card__note">기간 안에 반복된 위반이 없다.</p>
        ) : (
          <table className="analysis__table">
            <thead>
              <tr>
                <th>대상</th>
                <th>위반</th>
                <th>횟수</th>
                <th>마지막</th>
              </tr>
            </thead>
            <tbody>
              {repeat.map((item) => (
                <tr key={`${item.subject}:${item.key}:${item.violation_type}`}>
                  <td>
                    <span className="chip">{SUBJECT_LABEL[item.subject]}</span> {item.label}
                  </td>
                  <td>{violationLabel(item.violation_type)}</td>
                  <td className="analysis__num">{item.count}</td>
                  <td>{stamp(item.last_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="card__note">
          ★ <strong>작업자 개인 단위 누적이 아니다</strong>(§4.2). 「추적」은 세션 안의
          추적 번호일 뿐 신원이 아니며 카메라를 벗어나면 유효하지 않다.
        </p>
      </section>

      <section className="card">
        <h2 className="card__title">주간 보고서</h2>
        <div className="settings__actions">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void makeReport()}
            disabled={reportBusy}
          >
            {reportBusy ? '생성 중…' : '이 기간으로 생성'}
          </button>
          {report && (
            <span className="settings__state">
              {report.report_id} · {report.status === 'ready' ? '완료' : report.status}
            </span>
          )}
        </div>
        {report?.body && <pre className="analysis__report">{report.body}</pre>}
        <p className="card__note">
          숫자는 SQL 집계가 만들고 LLM 은 그것을 문장으로 옮긴다. 클라우드가 꺼져 있으면
          집계 문장만 나온다 — 비어 있는 것보다 낫다.
        </p>
      </section>
    </div>
  )
}

const SUBJECT_LABEL: Record<string, string> = {
  zone: '구역',
  camera: '카메라',
  // ★ 「작업자」가 아니다(§4.2).
  track: '추적',
}

/**
 * 시정률·판정 불가율 두 계열. **선을 잇지 않고 막대로 그린다.**
 *
 * 버킷이 빠질 수 있으므로(모집단 0) 선으로 이으면 없는 구간을 지나가는 직선이 생기고,
 * 그 직선은 관측되지 않은 값을 관측된 것처럼 보이게 한다.
 */
function RateChart({
  correction,
  undetermined,
}: {
  correction: TimeseriesPoint[]
  undetermined: TimeseriesPoint[]
}) {
  const byBucket = new Map<string, { correction: number | null; undetermined: number | null; n: number }>()
  for (const point of correction) {
    byBucket.set(point.t, { correction: point.value, undetermined: null, n: point.n })
  }
  for (const point of undetermined) {
    const found = byBucket.get(point.t)
    if (found) found.undetermined = point.value
    else byBucket.set(point.t, { correction: null, undetermined: point.value, n: point.n })
  }
  const rows = [...byBucket.entries()].sort(([a], [b]) => a.localeCompare(b))

  if (rows.length === 0) {
    return <p className="card__note">이 구간에는 판정 가능한 이벤트가 없다.</p>
  }
  return (
    <div className="chart">
      {rows.map(([bucket, values]) => (
        <div key={bucket} className="chart__col" title={`${bucket} · 모집단 ${values.n}건`}>
          <div className="chart__stack">
            <span
              className="chart__bar chart__bar--ok"
              style={{ height: `${(values.correction ?? 0) * 100}%` }}
            />
            <span
              className="chart__bar chart__bar--muted"
              style={{ height: `${(values.undetermined ?? 0) * 100}%` }}
            />
          </div>
          <span className="chart__label">{bucket.slice(-5)}</span>
          <span className="chart__value">
            {formatRate(values.correction)}
            <em>({formatRate(values.undetermined)})</em>
          </span>
        </div>
      ))}
    </div>
  )
}

function BarList({ buckets, translate }: { buckets: DistributionBucket[]; translate?: boolean }) {
  if (buckets.length === 0) return <p className="card__note">집계할 이벤트가 없다.</p>
  return (
    <ul className="bars">
      {buckets.map((bucket) => (
        <li key={bucket.key} className="bars__row">
          <span className="bars__label">
            {translate ? violationLabel(bucket.key) : bucket.label}
          </span>
          <span className="bars__track">
            <span className="bars__fill" style={{ width: `${bucket.ratio * 100}%` }} />
          </span>
          <span className="bars__count">
            {bucket.count} · {Math.round(bucket.ratio * 100)}%
          </span>
        </li>
      ))}
    </ul>
  )
}

/** 24칸 히트맵. 서버가 0을 채운 키를 주므로 사전순 = 시각순이다(§4.2). */
function Heatmap({ buckets }: { buckets: DistributionBucket[] }) {
  const counts = new Map(buckets.map((bucket) => [bucket.key, bucket.count]))
  const peak = Math.max(1, ...buckets.map((bucket) => bucket.count))
  return (
    <div className="heatmap">
      {Array.from({ length: 24 }, (_, hour) => {
        const key = String(hour).padStart(2, '0')
        const count = counts.get(key) ?? 0
        return (
          <div key={key} className="heatmap__cell" title={`${key}시 · ${count}건`}>
            <span
              className="heatmap__fill"
              style={{ opacity: count === 0 ? 0.06 : 0.2 + (count / peak) * 0.8 }}
            />
            <span className="heatmap__hour">{key}</span>
          </div>
        )
      })}
    </div>
  )
}
