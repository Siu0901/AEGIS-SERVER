import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './layout/AppLayout'
import OverviewPage from './pages/OverviewPage'
import LivePage from './pages/LivePage'
import EventsPage from './pages/EventsPage'
import SearchPage from './pages/SearchPage'
import AnalysisPage from './pages/AnalysisPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/live" element={<LivePage />} />
        <Route path="/events" element={<EventsPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        {/* 챗봇 전용 화면은 없앴다 — 실시간 관제 사이드로 들어갔다. 옛 링크·북마크는
            아래 `*` 가 개요로 돌린다. */}
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
