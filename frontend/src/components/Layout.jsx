import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth.jsx'

const ROLE_LABEL = { donor: 'Donor', ngo: 'NGO', admin: 'Admin' }
const ADMIN_NAV = [['/admin', 'Live demo'], ['/admin/analytics', 'Analytics'], ['/admin/pipeline', 'Pipeline health']]

export default function Layout({ children }) {
  const { auth, logout } = useAuth()
  return (
    <>
      <header className="topbar">
        <div className="brand">🍲 FoodRescue <span>Navi Mumbai</span></div>
        {auth.role === 'admin' && (
          <nav className="nav" aria-label="Admin pages">
            {ADMIN_NAV.map(([to, text]) => (
              <NavLink key={to} to={to} end className={({ isActive }) => (isActive ? 'active' : '')}>{text}</NavLink>
            ))}
          </nav>
        )}
        <div className="who">
          <span className={`pill role-${auth.role}`}>{ROLE_LABEL[auth.role]}</span>
          <span className="muted">{auth.name}</span>
          <button className="btn ghost" onClick={logout}>Sign out</button>
        </div>
      </header>
      <main className="page">{children}</main>
    </>
  )
}
