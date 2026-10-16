import { useState } from 'react'
import { api } from '../api.js'
import { AREAS, CATEGORIES, Badge, label, timeLeft } from './bits.jsx'

/** Full-text + filter search over donations (Elasticsearch). Shows a clear message if search is not enabled. */
export default function SearchBox({ title = 'Search donations' }) {
  const [f, setF] = useState({ q: '', category: '', area: '', min_kg: '' })
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const run = async (e) => {
    e?.preventDefault()
    setBusy(true)
    setErr('')
    const qs = new URLSearchParams()
    Object.entries(f).forEach(([k, v]) => v !== '' && qs.set(k, v))
    try { setRes(await api(`/search/donations?${qs}`)) } catch (ex) { setErr(ex.message); setRes(null) } finally { setBusy(false) }
  }

  return (
    <section className="card">
      <h2>{title}</h2>
      <form className="searchbar" onSubmit={run}>
        <input placeholder="Search food, donor, area… e.g. biryani" value={f.q} onChange={set('q')} aria-label="Search" />
        <select value={f.category} onChange={set('category')} aria-label="Category">
          <option value="">Any category</option>
          {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select value={f.area} onChange={set('area')} aria-label="Area">
          <option value="">Any area</option>
          {AREAS.map((a) => <option key={a}>{a}</option>)}
        </select>
        <input type="number" min="0" placeholder="min kg" value={f.min_kg} onChange={set('min_kg')} aria-label="Minimum kg" style={{ width: 90 }} />
        <button className="btn primary" disabled={busy}>{busy ? 'Searching…' : 'Search'}</button>
      </form>
      {err && <div className="alert error" role="alert">{err}</div>}
      {res && (
        <>
          <div className="muted small" style={{ margin: '.5rem 0' }}>{res.total} result{res.total === 1 ? '' : 's'}</div>
          <div className="list" style={{ maxHeight: 260 }}>
            {res.hits.map((h) => (
              <div key={h.id} className="item">
                <div className="item-head">
                  <div>
                    <b>{h.food_type}</b> <span className="muted">· {h.quantity_kg} kg · {label(h.category)}</span>
                    <div className="muted small">{h.donor} · {h.area} · {timeLeft(h.expiry_time)}</div>
                  </div>
                  <Badge status={h.status} />
                </div>
              </div>
            ))}
            {res.hits.length === 0 && <div className="muted">Nothing matched.</div>}
          </div>
        </>
      )}
    </section>
  )
}
