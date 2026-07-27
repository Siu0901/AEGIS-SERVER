import type { ReactNode } from 'react'

type TopBarProps = {
  title: string
  subtitle: string
  /** 우측 슬롯 — 페이지별 주요 액션 버튼이 들어갈 자리 (M0에서는 비어 있음) */
  actions?: ReactNode
}

export default function TopBar({ title, subtitle, actions }: TopBarProps) {
  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>
      <span className="topbar__divider" />
      <span className="topbar__subtitle">{subtitle}</span>
      <div className="topbar__right">
        <span className="topbar__timestamp">--:--:--</span>
        {actions}
      </div>
    </header>
  )
}
