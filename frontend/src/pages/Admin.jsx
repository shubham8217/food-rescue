import { useEffect, useRef, useState } from 'react'
import { api, loadAuth, wsUrl } from '../api.js'
import MapView from '../components/MapView.jsx'
import { STATUSES, STATUS_COLOR, label } from '../components/bits.jsx'

const EMPTY = {
  demo: { state: 'idle', running: false, speed: 1, batch_no: 0, total_batches: 20, next_batch_in: 0 },
  stats: { batches: 0, accepted_rows: 0, rejected_rows: 0, matches: 0, kg_rescued: 0, meals: 0, kg_in_flight: 0, donations_by_status: {}, total_donations: 0 },
  pins: [], rejected: [], events: [],
}

/** WebSocket first; if it fails or drops, fall back to polling /admin/live and retry the socket. */
function useLive() {
  const [data, setData] = useState(EMPTY)
  const [events, setEvents] = useState([])
  const [mode, setMode] = useState('connecting')
  const lastId = useRef(0)

  useEffect(() => {
    let ws, poll, retry, closed = false
    const apply = (p) => {
      lastId.current = p.last_event_id
      setData(p)
      if (p.events.length) setEvents((old) => [...old, ...p.events].slice(-300))
    }
    const startPolling = () => {
      if (poll) return
      setMode('polling')
      const tick = async () => { try { apply(await api(`/admin/live?after=${lastId.current}`)) } catch { /* retry next tick */ } }
      tick()
      poll = setInterval(tick, 2000)
    }
    const connect = () => {
      if (closed) return
      try { ws = new WebSocket(wsUrl(loadAuth().access_token)) } catch { return startPolling() }
      ws.onopen = () => { setMode('websocket'); if (poll) { clearInterval(poll); poll = null } }
      ws.onmessage = (m) => apply(JSON.parse(m.data))
      ws.onclose = () => { if (closed) return; startPolling(); retry = setTimeout(connect, 8000) }
    }
    connect()
    return () => { closed = true; clearTimeout(retry); clearInterval(poll); ws && ws.close() }
  }, [])
  return { data, events, mode }
}

const Counter = ({ title, value, hint, tone }) => (
  <div className={`counter ${tone || ''}`}>
    <div className="cval">{typeof value === 'number' ? value.toLocaleString('en-IN') : value}</div>
    <div className="clabel">{title}</div>
    {hint && <div className="chint">{hint}</div>}
  </div>
)

export default function Admin() {
  const { data, events, mode } = useLive()
  const { demo, stats, pins, rejected } = data
  const [speed, setSpeed] = useState(1)
  const [hour, setHour] = useState('')
  const [reset, setReset] = useState(true)
  const [err, setErr] = useState('')
  const logRef = useRef(null)

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight }, [events])
  useEffect(() => { if (demo.running) setSpeed(demo.speed) }, [demo.running, demo.speed])

  const call = async (fn) => { setErr(''); try { await fn() } catch (e) { setErr(e.message) } }
  const start = () => call(() => api('/demo/start', { method: 'POST', body: { speed, reset, start_hour: hour === '' ? null : Number(hour) } }))
  const stop = () => call(() => api('/demo/stop', { method: 'POST' }))
  const changeSpeed = (s) => { setSpeed(s); if (demo.running) call(() => api('/demo/speed', { method: 'POST', body: { speed: s } })) }
  const wipe = () => window.confirm('Delete all donations, matches, batches and events?') && call(() => api('/demo/reset', { method: 'POST' }))

  const pct = demo.total_batches ? Math.round((demo.batch_no / demo.total_batches) * 100) : 0
  const by = stats.donations_by_status || {}

  return (
    <>
      <section className="card demo-bar">
        <div className="demo-main">
          <div>
            <h2>Live Demo</h2>
            <div className="muted small">
              {demo.running
                ? `Batch ${demo.batch_no}/${demo.total_batches} · next in ${Math.ceil(demo.next_batch_in)}s · ${demo.speed}x`
                : demo.state === 'finished' ? 'Finished: all batches sent'
                  : demo.state === 'stopped' ? 'Stopped' : 'Ready: 10 minutes, one batch every 30 s (20 batches)'}
            </div>
          </div>
          <div className="controls">
            <div className="seg" role="group" aria-label="Speed">
              {[1, 2, 5].map((s) => (
                <button key={s} className={speed === s ? 'on' : ''} onClick={() => changeSpeed(s)}>{s}x</button>
              ))}
            </div>
            {!demo.running && (
              <select value={hour} onChange={(e) => setHour(e.target.value)} title="Surplus volume follows the time of day">
                <option value="">Real clock</option><option value="13">Lunch rush</option><option value="20">Dinner rush</option><option value="4">Quiet night</option>
              </select>
            )}
            {demo.running
              ? <button className="btn danger" onClick={stop}>■ Stop</button>
              : <button className="btn primary" onClick={start}>▶ Start Live Demo</button>}
          </div>
        </div>
        <div className="progress"><i style={{ width: `${pct}%` }} /></div>
        <div className="demo-foot small muted">
          <label><input type="checkbox" checked={reset} onChange={(e) => setReset(e.target.checked)} disabled={demo.running} /> clear previous data on start</label>
          <span>CSV → <code>data/inbox/</code> {demo.last_file && <>· last: <code>{demo.last_file}</code></>}</span>
          <span>direct ingest ok {demo.direct_ok ?? 0} · fallback {demo.fallbacks ?? 0}</span>
          <span className={`live ${mode}`}>● {mode === 'websocket' ? 'live (WebSocket)' : mode}</span>
          {!demo.running && <button className="link" onClick={wipe}>reset data</button>}
        </div>
        {err && <div className="alert error" role="alert">{err}</div>}
      </section>

      <section className="counters">
        <Counter title="Batches" value={stats.batches} hint={`${stats.total_donations} donations`} />
        <Counter title="Accepted rows" value={stats.accepted_rows} tone="good" />
        <Counter title="Rejected rows" value={stats.rejected_rows} tone="bad" />
        <Counter title="Matches" value={stats.matches} />
        <Counter title="Kg rescued" value={stats.kg_rescued} hint={`${stats.kg_in_flight} kg in transit`} tone="good" />
        <Counter title="Meals" value={stats.meals} hint="kg ÷ 0.4" tone="good" />
      </section>

      <section className="pipeline card">
        {[...STATUSES, 'expired'].map((s) => (
          <div key={s}><i style={{ background: STATUS_COLOR[s] }} /><b>{by[s] || 0}</b> {label(s)}</div>
        ))}
      </section>

      <div className="grid two">
        <section className="card">
          <h2>Donation map</h2>
          <MapView pins={pins} />
        </section>
        <section className="card">
          <h2>Live event log</h2>
          <div className="log" ref={logRef}>
            {events.length === 0 && <div className="muted">Waiting for events. Press “Start Live Demo”.</div>}
            {events.map((e) => (
              <div key={e.id} className={`ev ${e.kind}`}>
                <time>{new Date(e.ts).toLocaleTimeString('en-IN')}</time>
                <span className="tag">{e.kind}</span>
                <span>{e.message}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="card">
        <h2>Rejected rows <span className="muted">(latest {rejected.length})</span></h2>
        <div className="tablewrap">
          <table>
            <thead><tr><th>Batch</th><th>Row</th><th>Type</th><th>Reason</th><th>Raw data</th></tr></thead>
            <tbody>
              {rejected.length === 0 && <tr><td colSpan="5" className="muted">No rejected rows yet</td></tr>}
              {rejected.map((r) => (
                <tr key={r.id}>
                  <td>#{r.batch_id}</td><td>{r.row_number}</td><td>{r.type}</td>
                  <td><span className="reason">{r.reason}</span></td>
                  <td className="raw">{[r.raw.org_name, r.raw.food_type, r.raw.category, r.raw.quantity_kg && `${r.raw.quantity_kg}kg`].filter(Boolean).join(' · ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
