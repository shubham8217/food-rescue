import { useState } from 'react'
import { api, uploadFile } from '../api.js'
import { AREAS, CATEGORIES, Steps, fmtTime, label, timeLeft, usePolling } from '../components/bits.jsx'

const localInput = (d) => {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}
const blank = () => ({ food_type: '', category: 'cooked_meals', quantity_kg: '', area: 'Vashi',
  expiry: localInput(new Date(Date.now() + 4 * 3600e3)) })

export default function Donor() {
  const [form, setForm] = useState(blank())
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(null)
  const [matches, setMatches] = useState([])
  const [rows, err, reload] = usePolling(() => api('/donations/mine'), 4000)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setMsg(null)
    setBusy(true)
    try {
      await api('/donations', { method: 'POST', body: {
        food_type: form.food_type, category: form.category, quantity_kg: Number(form.quantity_kg),
        area: form.area, expiry_time: new Date(form.expiry).toISOString() } })
      setMsg({ ok: true, text: 'Donation listed. Matching NGOs are being found…' })
      setForm(blank())
      reload()
    } catch (ex) {
      setMsg({ ok: false, text: ex.message })
    } finally {
      setBusy(false)
    }
  }

  const [up, setUp] = useState(null)
  const upload = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setUp({ busy: true })
    try {
      const r = await uploadFile('/ingest/batch', file)
      setUp({ ok: true, r })
      reload()
    } catch (ex) { setUp({ ok: false, text: ex.message }) }
  }

  const toggle = async (id) => {
    if (open === id) return setOpen(null)
    setOpen(id)
    setMatches([])
    try { setMatches(await api(`/donations/${id}/matches`)) } catch { setMatches([]) }
  }

  return (
    <div className="grid two">
      <section className="card">
        <h2>Donate surplus food</h2>
        <form onSubmit={submit} className="form">
          <label>What food?
            <input value={form.food_type} onChange={set('food_type')} placeholder="e.g. Veg biryani" required minLength={2} />
          </label>
          <div className="row">
            <label>Category
              <select value={form.category} onChange={set('category')}>
                {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label>Quantity (kg)
              <input type="number" min="0.5" max="5000" step="0.5" value={form.quantity_kg} onChange={set('quantity_kg')} required />
            </label>
          </div>
          <div className="row">
            <label>Area
              <select value={form.area} onChange={set('area')}>{AREAS.map((a) => <option key={a}>{a}</option>)}</select>
            </label>
            <label>Use before
              <input type="datetime-local" value={form.expiry} onChange={set('expiry')} required />
            </label>
          </div>
          {msg && <div className={`alert ${msg.ok ? 'ok' : 'error'}`} role="alert">{msg.text}</div>}
          <button className="btn primary" disabled={busy}>{busy ? 'Listing…' : 'List donation'}</button>
        </form>
        <div className="uploadbox">
          <b>Have many items? Upload a CSV or JSON file</b>
          <div className="muted small">Columns: food_type, category, quantity_kg, expiry_time, area (org_name is filled in for you)</div>
          <input type="file" accept=".csv,.json" onChange={upload} aria-label="Upload CSV" />
          {up?.busy && <div className="muted small">Uploading…</div>}
          {up?.ok && (
            <div className="alert ok">
              {up.r.accepted_donations} donation(s) accepted, {up.r.rejected_rows} rejected.
              {up.r.rejected.slice(0, 3).map((x) => <div key={x.row_number} className="small">row {x.row_number}: {x.reason}</div>)}
            </div>
          )}
          {up && up.ok === false && <div className="alert error">{up.text}</div>}
        </div>
      </section>

      <section className="card">
        <h2>My donations {rows && <span className="muted">({rows.length})</span>}</h2>
        {err && <div className="alert error">{err}</div>}
        {rows && rows.length === 0 && <p className="muted">Nothing yet. List your first donation on the left.</p>}
        <div className="list">
          {(rows || []).map((d) => (
            <div key={d.id} className="item">
              <div className="item-head" onClick={() => toggle(d.id)}>
                <div>
                  <b>{d.food_type}</b> <span className="muted">· {d.quantity_kg} kg · {label(d.category)} · {d.area}</span>
                  <div className="muted small">Use before {fmtTime(d.expiry_time)} ({timeLeft(d.expiry_time)})</div>
                </div>
                <Steps status={d.status} />
              </div>
              {d.accepted_ngo_name && <div className="small">✅ Accepted by <b>{d.accepted_ngo_name}</b></div>}
              {d.status === 'listed' && <div className="small muted">Finding NGOs within 15 km…</div>}
              {!d.accepted_ngo_name && d.match_count > 0 && <div className="small muted">{d.match_count} NGOs matched. Click to view</div>}
              {open === d.id && (
                <table className="mini">
                  <thead><tr><th>#</th><th>NGO</th><th>Distance</th><th>Score</th><th>Status</th></tr></thead>
                  <tbody>
                    {matches.map((m) => (
                      <tr key={m.id}><td>{m.rank}</td><td>{m.ngo_name}</td><td>{m.distance_km} km</td><td>{m.score.toFixed(2)}</td><td>{m.status}</td></tr>
                    ))}
                    {matches.length === 0 && <tr><td colSpan="5" className="muted">No matches yet</td></tr>}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
