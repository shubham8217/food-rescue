import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { homeFor, useAuth } from '../auth.jsx'

const DEMOS = [
  ['Donor', 'donor@foodrescue.demo'],
  ['NGO', 'ngo@foodrescue.demo'],
  ['Admin', 'admin@foodrescue.demo'],
]

export default function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    setBusy(true)
    try {
      const a = await login(email, password)
      nav(homeFor(a.role), { replace: true })
    } catch (ex) {
      setErr(ex.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login" onSubmit={submit}>
        <h1>🍲 FoodRescue</h1>
        <p className="muted">Matching surplus food with NGOs across Navi Mumbai</p>
        <label>Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </label>
        <label>Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {err && <div className="alert error" role="alert">{err}</div>}
        <button className="btn primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <div className="demo-accounts">
          <span className="muted">Demo accounts (password <code>demo123</code>)</span>
          <div>
            {DEMOS.map(([name, mail]) => (
              <button type="button" key={mail} className="btn ghost small"
                onClick={() => { setEmail(mail); setPassword('demo123') }}>{name}</button>
            ))}
          </div>
        </div>
      </form>
    </div>
  )
}
