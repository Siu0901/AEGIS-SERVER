import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

type TopBarProps = {
  title: string
  subtitle: string
  /** 우측 슬롯 — 페이지별 주요 액션 버튼이 들어갈 자리 */
  actions?: ReactNode
}

/**
 * 밀리초까지 흐르는 기준 시계. **현지 시간대로 찍는다.**
 *
 * 장식이 아니라 **측정 도구다.** 영상에는 카메라가 프레임을 만든 시각이 소성돼 있고
 * 이 시계는 지금 시각이므로, 한 화면을 캡처하면 두 값의 차이가 곧 영상 지연이다.
 * 다른 창의 시계와 비교하면 캡처 시점이 어긋나 그 자체가 오차가 된다.
 *
 * UTC 로 찍던 시절에는 이 화면을 보는 사람이 9시간을 암산해야 했다 — 지연을 눈으로
 * 재라고 둔 시계가 오히려 방해가 됐다. 저장과 API 는 UTC 그대로다(§1.2).
 *
 * `requestAnimationFrame` 으로 돌린다. `setInterval` 은 화면 갱신과 어긋나서
 * 캡처된 프레임과 표시된 숫자가 서로 다른 순간의 것이 될 수 있다.
 */
function ReferenceClock() {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    let handle = 0
    const tick = () => {
      setNow(Date.now())
      handle = requestAnimationFrame(tick)
    }
    handle = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(handle)
  }, [])

  return (
    <span className="topbar__clock" title="기준 시계. 영상 속 타임코드와의 차이가 영상 지연이다">
      {formatLocalTime(now)}
    </span>
  )
}

/** `HH:MM:SS.mmm` — 현지 시간대. `toISOString()` 은 항상 UTC 라 쓸 수 없다. */
function formatLocalTime(epochMs: number): string {
  const at = new Date(epochMs)
  const pad = (value: number, width = 2) => String(value).padStart(width, '0')
  return (
    `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}` +
    `.${pad(at.getMilliseconds(), 3)}`
  )
}

export default function TopBar({ title, subtitle, actions }: TopBarProps) {
  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>
      <span className="topbar__divider" />
      <span className="topbar__subtitle">{subtitle}</span>
      <div className="topbar__right">
        <ReferenceClock />
        {actions}
      </div>
    </header>
  )
}
