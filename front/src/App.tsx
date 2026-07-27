import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './layout/AppLayout'
import OverviewPage from './pages/OverviewPage'
import LivePage from './pages/LivePage'
import EventsPage from './pages/EventsPage'
import SearchPage from './pages/SearchPage'
import AnalysisPage from './pages/AnalysisPage'
import AssistantPage from './pages/AssistantPage'
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
        <Route path="/assistant" element={<AssistantPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
