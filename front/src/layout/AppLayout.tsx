import { Outlet, useLocation } from 'react-router-dom'
import Sidebar, { NAV_ITEMS } from './Sidebar'
import TopBar from './TopBar'
import './layout.css'

export default function AppLayout() {
  const { pathname } = useLocation()
  const current = NAV_ITEMS.find((item) => item.path === pathname) ?? NAV_ITEMS[0]

  return (
    <div className="app">
      <Sidebar />
      <div className="app__main">
        <TopBar title={current.label} subtitle={current.subtitle} />
        <main className="app__content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
