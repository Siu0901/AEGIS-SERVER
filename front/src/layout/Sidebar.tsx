import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useSystemStatus } from '../api/useSystemStatus'
import type { SystemStatusView } from '../api/useSystemStatus'

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
  /* 챗봇은 전용 화면을 두지 않는다 — 실시간 관제 사이드에 들어갔다(FN-UI-02 · FN-UI-06).
     「지금 상황은?」이 현재 프레임을 읽어 답하므로 영상을 보면서 묻는 자리가 맞고,
     같은 것을 두 곳에서 열 수 있으면 대화 세션이 어디에 있는지 헷갈린다. */
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

/**
 * 실제 관측값으로 만든 상태 줄 (API명세서 §4.6).
 *
 * 원래 여기에는 '정상' 세 줄이 고정으로 박혀 있었다. 카메라가 실제로 끊겨도 사이드바는
 * 계속 정상이라고 말하므로, 상태 표시가 없는 것보다 나쁘다. M1 에서 관측 가능한 값이
 * 생겼으니 그것으로 대체한다. 아직 관측 주체가 없는 항목(엣지·MCU·클라우드)은
 * '정상'이 아니라 **미연결**로 적는다.
 */
function statusLines(view: SystemStatusView): StatusLine[] {
  const { status } = view
  if (!status) {
    return [{ tone: 'danger', text: view.error ? '서버 응답 없음' : '상태 확인 중…' }]
  }

  const live = status.cameras.filter((camera) => camera.main_state === 'ok').length
  const total = status.cameras.length
  const recorderUp = status.storage.retention_days !== null

  return [
    {
      tone: live === total ? 'ok' : live === 0 ? 'danger' : 'warn',
      text: `카메라 메인 ${live}/${total}`,
    },
    {
      tone: recorderUp ? 'ok' : 'danger',
      text: recorderUp ? `녹화 · 보존 ${status.storage.retention_days}일` : '녹화(REC) 응답 없음',
    },
    {
      tone: status.edge.online ? 'ok' : 'warn',
      text: status.edge.online ? 'Jetson 엣지 · 정상' : 'Jetson 엣지 · 미연결',
    },
  ]
}

export default function Sidebar() {
  const view = useSystemStatus()
  const lines = statusLines(view)

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
        {lines.map((line) => (
          <div key={line.text} className="sidebar__status-row">
            <span className={`dot dot--${line.tone}`} />
            <span>{line.text}</span>
          </div>
        ))}
      </div>
    </aside>
  )
}
