import { useState } from 'react'
import { api } from '../api.js'
import { CATEGORIES, ScoreBar, Steps, fmtTime, label, timeLeft, usePolling } from '../components/bits.jsx'

export default function Ngo() {
  const [matches, merr, reloadM] = usePolling(() => api('/ngo/matches'), 4000)
  const [pickups, , reloadP] = usePolling(() => api('/ngo/pickups'), 4000)
  const [reqs, , reloadR] = usePolling(() => api('/ngo/requests'), 6000)
  const [msg, setMsg] = useState(null)
  const [req, setReq] = useState({ category: '', quantity_kg: '', hours: 4 })

  const act = async (fn, okText) => {
    setMsg(null)
    try { await fn(); setMsg({ ok: true, text: okText }) } catch (e) { setMsg({ ok: false, text: e.message }) }
    reloadM(); reloadP(); reloadR()
  }
  const accept = (m) => act(() => api(`/matches/${m.id}/accept`, { method: 'POST' }), `Accepted donation #${m.donation.id}. Arrange pickup.`)
  const move = (d, status) => act(() => api(`/donations/${d.id}/status`, { method: 'PATCH', body: { status } }), `Donation #${d.id} marked ${label(status)}.`)
  const postReq = (e) => {
    e.preventDefault()
    act(async () => {
      await api('/ngo/requests', { method: 'POST', body: {
        category: req.category || null, quantity_kg: Number(req.quantity_kg),
        needed_by: new Date(Date.now() + req.hours * 3600e3).toISOString() } })
      setReq({ category: '', quantity_kg: '', hours: 4 })
    }, 'Need posted. Donations will be matched against it.')
  }

  return (
    <>
      {msg && <div className={`alert ${msg.ok ? 'ok' : 'error'}`} role="alert">{msg.text}</div>}
      <div className="grid two">
        <section className="card">
          <h2>Ranked matches {matches && <span className="muted">({matches.length})</span>}</h2>
          {merr && <div className="alert error">{merr}</div>}
          {matches && matches.length === 0 && <p className="muted">No open matches right now. New donations appear here automatically.</p>}
          <div className="list">
            {(matches || []).map((m) => (
              <div key={m.id} className="item">
                <div className="item-head">
                  <div>
                    <b>{m.donation.food_type}</b> <span className="muted">· {m.donation.quantity_kg} kg · {label(m.donation.category)}</span>
                    <div className="muted small">{m.donation.donor_name} · {m.donation.area} · {m.distance_km} km away · {timeLeft(m.donation.expiry_time)}</div>
                  </div>
                  <ScoreBar m={m} />
                </div>
                <div className="chips small">
                  <span>📍 distance {m.distance_score.toFixed(2)}</span><span>⏳ urgency {m.urgency_score.toFixed(2)}</span>
                  <span>⚖️ fit {m.fit_score.toFixed(2)}</span><span className="muted">rank #{m.rank}</span>
                </div>
                <button className="btn primary small" onClick={() => accept(m)}>Accept donation</button>
              </div>
            ))}
          </div>
        </section>

        <div className="stack">
          <section className="card">
            <h2>My pickups</h2>
            {pickups && pickups.length === 0 && <p className="muted">Accepted donations will be tracked here.</p>}
            <div className="list">
              {(pickups || []).slice(0, 12).map((d) => (
                <div key={d.id} className="item">
                  <div className="item-head">
                    <div>
                      <b>{d.food_type}</b> <span className="muted">· {d.quantity_kg} kg · {d.donor_name} ({d.area})</span>
                    </div>
                    <Steps status={d.status} />
                  </div>
                  {d.status === 'accepted' && <button className="btn small" onClick={() => move(d, 'picked_up')}>Mark picked up</button>}
                  {d.status === 'picked_up' && <button className="btn small primary" onClick={() => move(d, 'delivered')}>Mark delivered</button>}
                  {d.status === 'delivered' && <span className="small muted">Delivered {fmtTime(d.status_changed_at)}</span>}
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <h2>Post a need</h2>
            <form className="form" onSubmit={postReq}>
              <div className="row">
                <label>Category
                  <select value={req.category} onChange={(e) => setReq({ ...req, category: e.target.value })}>
                    <option value="">Any</option>
                    {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </label>
                <label>Quantity (kg)
                  <input type="number" min="1" max="5000" value={req.quantity_kg} required
                    onChange={(e) => setReq({ ...req, quantity_kg: e.target.value })} />
                </label>
                <label>Needed within
                  <select value={req.hours} onChange={(e) => setReq({ ...req, hours: Number(e.target.value) })}>
                    {[2, 4, 8, 24].map((h) => <option key={h} value={h}>{h} hours</option>)}
                  </select>
                </label>
              </div>
              <button className="btn">Post need</button>
            </form>
            {reqs && reqs.length > 0 && (
              <table className="mini">
                <thead><tr><th>Category</th><th>Needed</th><th>Filled</th><th>Status</th></tr></thead>
                <tbody>
                  {reqs.slice(0, 6).map((r) => (
                    <tr key={r.id}><td>{r.category ? label(r.category) : 'any'}{r.standing && ' (standing)'}</td>
                      <td>{r.quantity_kg} kg</td><td>{r.fulfilled_kg} kg</td><td>{r.status}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      </div>
    </>
  )
}
