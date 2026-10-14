import { useAuth } from '../auth.jsx'

const ROLE_LABEL = { donor: 'Donor', ngo: 'NGO', admin: 'Admin' }

export default function Layout({ children }) {
  const { auth, logout } = useAuth()
  return (
    <>
      <header className="topbar">
        <div className="brand">🍲 FoodRescue <span>Navi Mumbai</span></div>
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
