import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'

export type NavItem = {
  path: string
  label: string
  subtitle: string
  icon: ReactNode
}

const iconProps = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

export const NAV_ITEMS: NavItem[] = [
  {
    path: '/',
    label: '개요',
    subtitle: '제조현장 · 상시근로자 5~50인',
    icon: (
      <svg {...iconProps}>
        <rect x="3" y="3" width="7" height="8" rx="1.5" />
        <rect x="14" y="3" width="7" height="5" rx="1.5" />
        <rect x="14" y="11" width="7" height="10" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
      </svg>
    ),
  },
  {
    path: '/live',
    label: '실시간 관제',
    subtitle: '2채널 라이브 + 감지 오버레이',
    icon: (
      <svg {...iconProps}>
        <rect x="2.5" y="5" width="13" height="14" rx="2" />
        <path d="M15.5 10.5 21.5 7v10l-6-3.5z" />
      </svg>
    ),
  },
  {
    path: '/events',
    label: '이벤트',
    subtitle: '목록 · 상태 추적 · 상세',
    icon: (
      <svg {...iconProps}>
        <path d="M12 3.5 21 19.5H3L12 3.5z" />
        <path d="M12 10v4" />
        <path d="M12 17h.01" />
      </svg>
    ),
  },
  {
    path: '/search',
    label: '영상 검색',
    subtitle: '자연어 장면 검색 · 멀티모달 임베딩',
    icon: (
      <svg {...iconProps}>
        <circle cx="11" cy="11" r="6.5" />
        <path d="m16 16 4.5 4.5" />
      </svg>
    ),
  },
  {
    path: '/analysis',
    label: '분석 · 보고서',
    subtitle: '추세 · 반복 위반 · 이상 탐지 · 보고서',
    icon: (
      <svg {...iconProps}>
        <path d="M4 20V4" />
        <path d="M4 20h16" />
        <path d="M8 16v-5" />
        <path d="M13 16V7" />
        <path d="M18 16v-8" />
      </svg>
    ),
  },
  {
    path: '/assistant',
    label: '챗봇',
    subtitle: '안전관리 어시스턴트',
    icon: (
      <svg {...iconProps}>
        <path d="M20 12.5c0 3.9-3.6 7-8 7-1 0-2-.15-2.9-.44L4 20.5l1.5-3.6A6.7 6.7 0 0 1 4 12.5c0-3.9 3.6-7 8-7s8 3.1 8 7z" />
      </svg>
    ),
  },
  {
    path: '/settings',
    label: '설정',
    subtitle: '금지구역 · 캘리브레이션 · 음원 · 정책 · 시스템',
    icon: (
      <svg {...iconProps}>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.6 1.6 0 0 0 .32 1.77l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.6 1.6 0 0 0-1.77-.32 1.6 1.6 0 0 0-1 1.47V21a2 2 0 1 1-4 0v-.11a1.6 1.6 0 0 0-1.05-1.46 1.6 1.6 0 0 0-1.77.32l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.6 1.6 0 0 0 4.6 15a1.6 1.6 0 0 0-1.47-1H3a2 2 0 1 1 0-4h.11A1.6 1.6 0 0 0 4.6 8.9a1.6 1.6 0 0 0-.32-1.77l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.6 1.6 0 0 0 1.77.32H9a1.6 1.6 0 0 0 1-1.47V3a2 2 0 1 1 4 0v.11a1.6 1.6 0 0 0 1 1.47 1.6 1.6 0 0 0 1.77-.32l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.6 1.6 0 0 0-.32 1.77V9a1.6 1.6 0 0 0 1.47 1H21a2 2 0 1 1 0 4h-.11a1.6 1.6 0 0 0-1.47 1z" />
      </svg>
    ),
  },
]

type StatusLine = { tone: 'ok' | 'warn' | 'danger'; text: string }

const SYSTEM_STATUS: StatusLine[] = [
  { tone: 'ok', text: 'Jetson 엣지 · 정상' },
  { tone: 'ok', text: '카메라 2/2 · ESP32' },
  { tone: 'ok', text: '클라우드 API · 정상' },
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <span className="sidebar__brand-mark">AEGIS</span>
        <span className="sidebar__brand-sub">안전관제</span>
      </div>

      <nav className="sidebar__nav">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              isActive ? 'sidebar__link sidebar__link--active' : 'sidebar__link'
            }
          >
            <span className="sidebar__icon">{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar__status">
        {SYSTEM_STATUS.map((line) => (
          <div key={line.text} className="sidebar__status-row">
            <span className={`dot dot--${line.tone}`} />
            <span>{line.text}</span>
          </div>
        ))}
      </div>
    </aside>
  )
}
