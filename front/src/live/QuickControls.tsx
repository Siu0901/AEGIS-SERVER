/**
 * 빠른 제어 — 수동 방송과 경고 일시중지 (FN-ALM-04 · FN-ALM-05 · API명세서 §4.5).
 *
 * 시안 2페이지 우측 하단의 「빠른 제어」 패널이다.
 *
 * **일시중지 상태를 계속 조회한다.** 꺼둔 것을 잊는 순간 감시가 조용히 멎으므로 그
 * 상태는 오탐보다 위험하다(CLAUDE.md 절대규칙 9). 화면은 남은 시간을 표시하고,
 * 새로고침해도 `GET /alerts/mute` 로 같은 사실을 다시 읽어온다.
 *
 * **음원 이름을 코드에 적지 않는다**(절대규칙 6). 고를 수 있는 것은 위반 유형 넷
 * (그 값 자체는 절대규칙 11 로 고정이다)과 「기본 안내」(`sound` 생략)뿐이며, 유형 →
 * 파일 매핑은 DB `alert_sounds` 에만 있다. 유형별 음원을 화면에서 바꾸는 것은
 * 설정 화면(FN-CFG-03 · M6)의 일이다.
 */

import { useCallback, useEffect, useState } from 'react'
import { fetchMuteState, postManualAlert, postMute } from '../api/alerts'
import { cameraName, VIOLATION_LABEL } from '../types/labels'
import type { AlertLevel, MuteAlertResponse, ViolationType } from '../types/system'

/** 일시중지 남은 시간을 다시 그리는 주기(ms). 초 단위로 줄어드는 것이 보여야 한다. */
const TICK_MS = 1_000

/** 상태를 서버에 다시 묻는 주기(ms). 다른 창에서 걸었을 수도 있다. */
const POLL_MS = 15_000

/** 일시중지 길이 선택지(분). `null` 은 정책 기본값(`mute_default_duration_s`)이다. */
const MUTE_CHOICES: { label: string; minutes: number | null }[] = [
  { label: '기본', minutes: null },
  { label: '5분', minutes: 5 },
  { label: '15분', minutes: 15 },
  { label: '30분', minutes: 30 },
]

/** 수동 방송으로 고를 수 있는 음원. 값은 `alert_sounds` 의 키다(파일명이 아니다). */
const SOUND_CHOICES: { label: string; sound: string | null }[] = [
  { label: '기본 안내', sound: null },
  ...(Object.keys(VIOLATION_LABEL) as ViolationType[]).map((type) => ({
    label: VIOLATION_LABEL[type],
    sound: type,
  })),
]

export default function QuickControls({ camIds }: { camIds: number[] }) {
  const [target, setTarget] = useState<number | null>(camIds[0] ?? null)
  const [sound, setSound] = useState<string | null>(null)
  const [level, setLevel] = useState<AlertLevel>(2)
  const [notifyDevice, setNotifyDevice] = useState(true)
  const [minutes, setMinutes] = useState<number | null>(null)
  const [reason, setReason] = useState('정비 작업')
  const [mutes, setMutes] = useState<Record<string, MuteAlertResponse>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())

  // 카메라별 창과 **전체 대상 창**을 따로 읽는다. 전체 중지가 걸려 있으면 카메라별
  // 창이 없어도 조용하므로, 하나만 보면 "이 카메라는 안 멈췄다"고 잘못 표시한다.
  const refresh = useCallback(
    (signal?: AbortSignal) => {
      const targets: (number | null)[] = [null, ...camIds]
      void Promise.all(targets.map((camId) => fetchMuteState(camId, signal)))
        .then((states) => {
          const next: Record<string, MuteAlertResponse> = {}
          targets.forEach((camId, index) => {
            next[key(camId)] = states[index]
          })
          setMutes(next)
        })
        .catch((cause: unknown) => {
          if (signal?.aborted) return
          setError(cause instanceof Error ? cause.message : String(cause))
        })
    },
    [camIds],
  )

  useEffect(() => {
    const controller = new AbortController()
    refresh(controller.signal)
    const timer = window.setInterval(() => refresh(), POLL_MS)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [refresh])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS)
    return () => window.clearInterval(timer)
  }, [])

  const broadcast = () => {
    if (target === null) return
    setMessage(null)
    setError(null)
    void postManualAlert({ cam_id: target, sound, level, notify_device: notifyDevice })
      .then((response) => {
        setMessage(
          `${cameraName(target)} 방송 송출 (${notifyDevice ? `경광등 level ${level} 동반` : '스피커만'})` +
            (response ? ` · ${new Date(response.dispatched_at).toLocaleTimeString()}` : ''),
        )
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause))
      })
  }

  const mute = (releaseNow: boolean) => {
    setMessage(null)
    setError(null)
    void postMute({
      cam_id: target,
      minutes: releaseNow ? 0 : minutes,
      reason: releaseNow ? '일시중지 해제' : reason,
    })
      .then(() => {
        refresh()
        setMessage(
          releaseNow
            ? `${scopeName(target)} 경고를 다시 켰다`
            : `${scopeName(target)} 경고를 멈췄다 — 그동안 확정된 이벤트는 시정률에서 제외된다`,
        )
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause))
      })
  }

  const active = Object.entries(mutes).filter(([, state]) => state.muted)

  return (
    <section className="card quick">
      <h2 className="card__title">빠른 제어</h2>

      {/* 꺼져 있다는 사실을 가장 먼저 보여준다. 이것이 이 패널의 존재 이유다. */}
      {active.length > 0 && (
        <ul className="quick__muted">
          {active.map(([scope, state]) => (
            <li key={scope} className="quick__muted-row">
              <span className="badge badge--warn">경고 중지</span>
              <span className="quick__muted-name">{scopeName(state.cam_id)}</span>
              <span className="quick__muted-left">
                {remaining(state.muted_until, now)} 남음 · {state.reason}
              </span>
            </li>
          ))}
        </ul>
      )}

      <label className="quick__field">
        <span>대상</span>
        <select
          value={target === null ? 'all' : String(target)}
          onChange={(event) =>
            setTarget(event.target.value === 'all' ? null : Number(event.target.value))
          }
        >
          {camIds.map((camId) => (
            <option key={camId} value={String(camId)}>
              {cameraName(camId)}
            </option>
          ))}
          <option value="all">전체 카메라</option>
        </select>
      </label>

      <div className="quick__group">
        <h3 className="quick__head">수동 방송 송출</h3>
        <label className="quick__field">
          <span>음원</span>
          <select
            value={sound ?? 'default'}
            onChange={(event) =>
              setSound(event.target.value === 'default' ? null : event.target.value)
            }
          >
            {SOUND_CHOICES.map((choice) => (
              <option key={choice.label} value={choice.sound ?? 'default'}>
                {choice.label}
              </option>
            ))}
          </select>
        </label>
        <label className="quick__field">
          <span>등급</span>
          <select
            value={String(level)}
            onChange={(event) => setLevel(Number(event.target.value) as AlertLevel)}
          >
            <option value="1">1 · 주의 (부저 없음)</option>
            <option value="2">2 · 경고</option>
            <option value="3">3 · 긴급 (연속 부저)</option>
          </select>
        </label>
        <label className="quick__check">
          <input
            type="checkbox"
            checked={notifyDevice}
            onChange={(event) => setNotifyDevice(event.target.checked)}
          />
          {/* §4.5 `notify_device` — 끄면 스피커만 울린다. */}
          <span>경광등도 함께 (level 로 MQTT 발행)</span>
        </label>
        <button
          type="button"
          className="btn btn--primary"
          disabled={target === null}
          onClick={broadcast}
        >
          방송 송출
        </button>
        <p className="card__note">
          일시중지 중에도 나간다 — 사람이 지금 누른 방송이므로 정비 중이라도 그 사람이
          의도한 것이다.
        </p>
      </div>

      <div className="quick__group">
        <h3 className="quick__head">경고 일시중지</h3>
        <label className="quick__field">
          <span>길이</span>
          <select
            value={minutes === null ? 'default' : String(minutes)}
            onChange={(event) =>
              setMinutes(event.target.value === 'default' ? null : Number(event.target.value))
            }
          >
            {MUTE_CHOICES.map((choice) => (
              <option key={choice.label} value={choice.minutes === null ? 'default' : String(choice.minutes)}>
                {choice.label}
              </option>
            ))}
          </select>
        </label>
        <label className="quick__field">
          <span>사유</span>
          <input value={reason} onChange={(event) => setReason(event.target.value)} />
        </label>
        <div className="quick__buttons">
          <button type="button" className="btn" onClick={() => mute(false)}>
            일시중지
          </button>
          <button type="button" className="btn" onClick={() => mute(true)}>
            즉시 해제
          </button>
        </div>
        <p className="card__note">
          기한 없는 중지는 만들 수 없다 — 「기본」은 정책값(<code>mute_default_duration_s</code>)
          을 서버가 붙인다. 멈춘 동안 확정된 이벤트는 <b>시정률에서 제외</b>되고
          「방송 없이 확정」으로 따로 집계된다(§4.8).
        </p>
      </div>

      {message && <p className="quick__ok">{message}</p>}
      {error && <p className="quick__error">{error}</p>}
    </section>
  )
}

function key(camId: number | null): string {
  return camId === null ? 'all' : String(camId)
}

function scopeName(camId: number | null): string {
  return camId === null ? '전체 카메라' : cameraName(camId)
}

/** 남은 시간. 이미 지났으면 「곧 해제」 — 음수 시간을 보여주지 않는다. */
function remaining(until: string | null, now: number): string {
  if (!until) return '—'
  const at = new Date(until).getTime()
  if (Number.isNaN(at)) return until
  const seconds = Math.round((at - now) / 1000)
  if (seconds <= 0) return '곧 해제'
  if (seconds < 60) return `${seconds}초`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}분 ${seconds % 60}초`
}
