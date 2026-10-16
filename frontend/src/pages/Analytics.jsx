import { useState } from 'react'
import { api } from '../api.js'
import { Columns, Funnel, HBars, PALETTE, Stat } from '../components/charts.jsx'
import SearchBox from '../components/SearchBox.jsx'
import { AREAS, label, usePolling } from '../components/bits.jsx'

const hourLabel = (iso) => new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', hour12: true }).replace(' ', '')
const dayHour = (iso) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', hour12: true })
const istHour = (iso) => Number(new Date(iso).toLocaleString('en-GB', { hour: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }))

async function loadAll(hours, area) {
  const [summary, byArea, byCat, timeline, funnel, rej, top, fc] = await Promise.all([
    api('/analytics/summary'), api('/analytics/by-area'), api('/analytics/by-category'),
    api(`/analytics/timeline?hours=${hours}`), api('/analytics/funnel'), api('/analytics/rejections'),
    api('/analytics/top'), api(`/forecast?hours=24${area ? `&area=${area}` : ''}`),
  ])
  return { summary, byArea, byCat, timeline, funnel, rej, top, fc }
}

export default function Analytics() {
  const [hours, setHours] = useState(24)
  const [area, setArea] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [d, err, reload] = usePolling(() => loadAll(hours, area), 15000, [hours, area])

  const backfill = async () => {
    setBusy(true); setMsg('')
    try {
      const r = await api('/forecast/backfill?days=7', { method: 'POST' })
      setMsg(`Added ${r.donations.toLocaleString('en-IN')} historical donations over ${r.days} days.`)
      reload()
    } catch (e) { setMsg(e.message) } finally { setBusy(false) }
  }

  if (!d) return <section className="card">{err ? <div className="alert error">{err}</div> : 'Loading analytics…'}</section>
  const { summary: s } = d
  const pct = (x) => `${Math.round((x || 0) * 100)}%`
  const empty = s.total_donations === 0

  return (
    <>
      <section className="card demo-bar">
        <div className="demo-main">
          <div>
            <h2>Analytics</h2>
            <div className="muted small">DuckDB SQL over Polars frames from PostgreSQL, plus the Delta Lake status history</div>
          </div>
          <div className="controls">
            <div className="seg" role="group" aria-label="Range">
              {[[24, '24 h'], [72, '3 days'], [168, '7 days']].map(([h, l]) => (
                <button key={h} className={hours === h ? 'on' : ''} onClick={() => setHours(h)}>{l}</button>
              ))}
            </div>
            <button className="btn" onClick={backfill} disabled={busy}>{busy ? 'Seeding…' : 'Seed 7 days of history'}</button>
          </div>
        </div>
        {msg && <div className="alert ok" style={{ marginTop: '.6rem' }}>{msg}</div>}
        {empty && <div className="alert error" style={{ marginTop: '.6rem' }}>No data yet. Run the live demo or press “Seed 7 days of history”.</div>}
      </section>

      <section className="counters">
        <Stat title="Donations" value={s.total_donations} hint={`${Math.round(s.total_kg).toLocaleString('en-IN')} kg offered`} />
        <Stat title="Kg rescued" value={s.kg_rescued} />
        <Stat title="Meals" value={s.meals} hint="kg ÷ 0.4" />
        <Stat title="Delivered" value={pct(s.delivery_rate)} hint={`accepted ${pct(s.acceptance_rate)}`} />
        <Stat title="Expired" value={pct(s.expired_rate)} />
        <Stat title="Min to accept" value={s.avg_minutes_to_accept ?? '-'} hint={s.avg_minutes_accept_to_delivery != null ? `${s.avg_minutes_accept_to_delivery} min to deliver` : 'from Delta Lake'} />
      </section>

      <div className="grid two">
        <section className="card">
          <h2>Donations over time</h2>
          <div className="muted small">Bars: kg offered per hour · solid: kg delivered</div>
          <Columns points={d.timeline.map((t) => ({ label: hours > 24 ? dayHour(t.ts) : hourLabel(t.ts), a: t.kg, b: t.delivered_kg }))}
            aLabel="kg offered" bLabel="kg delivered" />
        </section>
        <section className="card">
          <h2>Donation funnel</h2>
          <Funnel stages={d.funnel} />
        </section>
        <section className="card">
          <h2>Kg rescued by area</h2>
          <HBars rows={d.byArea.map((a) => ({ label: a.area, value: a.rescued_kg }))} unit=" kg" />
        </section>
        <section className="card">
          <h2>By food category</h2>
          <HBars rows={d.byCat.map((c) => ({ label: label(c.category), value: c.kg }))} unit=" kg" color={PALETTE} />
        </section>
        <section className="card">
          <h2>Why rows were rejected</h2>
          <HBars rows={d.rej.map((r) => ({ label: r.reason, value: r.count }))} color="#dc2626" />
        </section>
        <section className="card">
          <h2>Top donors and NGOs</h2>
          <div className="muted small">Donors by kg offered</div>
          <HBars rows={d.top.donors.map((x) => ({ label: x.name, value: x.kg }))} unit=" kg" color="#0ea5e9" />
          <div className="muted small" style={{ marginTop: '.8rem' }}>NGOs by kg delivered</div>
          <HBars rows={d.top.ngos.map((x) => ({ label: x.name, value: x.kg }))} unit=" kg" color="#f59e0b" />
        </section>
      </div>

      <section className="card">
        <div className="demo-main">
          <div>
            <h2>Surplus forecast: next 24 hours</h2>
            <div className="muted small">
              Recency-weighted average by hour, learned from {d.fc.history_days} day(s) of history. Orange = lunch and dinner rush.
            </div>
          </div>
          <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Forecast area">
            <option value="">All areas</option>
            {AREAS.map((a) => <option key={a}>{a}</option>)}
          </select>
        </div>
        {d.fc.points.length === 0
          ? <div className="chart-empty muted">{d.fc.note || 'No forecast yet'}</div>
          : <Columns points={d.fc.points.map((p) => ({ label: hourLabel(p.ts), a: p.predicted_kg, hour: istHour(p.ts) }))}
            aLabel="predicted kg" highlight={(p) => [12, 13, 14, 19, 20, 21].includes(p.hour)} />}
      </section>

      <SearchBox />
    </>
  )
}
