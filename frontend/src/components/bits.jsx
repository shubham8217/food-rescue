import { useEffect, useRef, useState } from 'react'

export const STATUSES = ['listed', 'matched', 'accepted', 'picked_up', 'delivered']
export const STATUS_COLOR = {
  listed: '#9aa5b1', matched: '#3b82f6', accepted: '#f59e0b', picked_up: '#8b5cf6', delivered: '#16a34a', expired: '#dc2626',
}
export const label = (s) => (s || '').replace(/_/g, ' ')

export function Badge({ status }) {
  return <span className="badge" style={{ background: STATUS_COLOR[status] || '#666' }}>{label(status)}</span>
}

/** 5-step progress for the listed -> delivered flow */
export function Steps({ status }) {
  const idx = STATUSES.indexOf(status)
  if (status === 'expired') return <Badge status="expired" />
  return (
    <div className="steps" title={label(status)}>
      {STATUSES.map((s, i) => (
        <span key={s} className={`step ${i <= idx ? 'on' : ''}`} style={i <= idx ? { background: STATUS_COLOR[s] } : null} />
      ))}
      <span className="steplabel">{label(status)}</span>
    </div>
  )
}

export const fmtTime = (iso) =>
  new Date(iso).toLocaleString('en-IN', { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short' })

export function timeLeft(iso) {
  const ms = new Date(iso) - Date.now()
  if (ms <= 0) return 'expired'
  const h = Math.floor(ms / 3.6e6), m = Math.floor((ms % 3.6e6) / 6e4)
  return h ? `${h}h ${m}m left` : `${m}m left`
}

/** Poll an async loader every `ms`; returns [data, error, reload] */
export function usePolling(loader, ms = 4000, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const ref = useRef(loader)
  ref.current = loader
  const load = async () => {
    try { setData(await ref.current()); setError('') } catch (e) { setError(e.message) }
  }
  useEffect(() => {
    load()
    const t = setInterval(load, ms)
    return () => clearInterval(t)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return [data, error, load]
}

export function ScoreBar({ m }) {
  return (
    <div className="scorebar" title={`distance ${m.distance_score} · urgency ${m.urgency_score} · fit ${m.fit_score}`}>
      <div className="bar"><i style={{ width: `${Math.round(m.score * 100)}%` }} /></div>
      <b>{m.score.toFixed(2)}</b>
    </div>
  )
}

export const CATEGORIES = [
  ['cooked_meals', 'Cooked meals'], ['bakery', 'Bakery'], ['produce', 'Produce'],
  ['dairy', 'Dairy'], ['packaged', 'Packaged'], ['beverages', 'Beverages'],
]
export const AREAS = ['Nerul', 'Vashi', 'Belapur', 'Kharghar', 'Sanpada', 'Airoli', 'Seawoods']
