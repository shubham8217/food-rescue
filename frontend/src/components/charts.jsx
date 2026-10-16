// Tiny dependency-free SVG charts (bar, line/area, funnel) that follow the app palette.
import { useState } from 'react'

const GREEN = '#15803d'
const COLORS = ['#15803d', '#0ea5e9', '#f59e0b', '#8b5cf6', '#ef4444', '#64748b', '#14b8a6']
const nf = (n) => (typeof n === 'number' ? n.toLocaleString('en-IN', { maximumFractionDigits: 1 }) : n)

export function Empty({ text = 'No data yet' }) {
  return <div className="chart-empty muted">{text}</div>
}

/** Horizontal bars: rows = [{label, value}] */
export function HBars({ rows, unit = '', color = GREEN, max }) {
  if (!rows?.length) return <Empty />
  const top = max || Math.max(...rows.map((r) => r.value), 1)
  return (
    <div className="hbars">
      {rows.map((r, i) => (
        <div key={r.label} className="hbar" title={`${r.label}: ${nf(r.value)}${unit}`}>
          <span className="hl">{r.label}</span>
          <span className="hb"><i style={{ width: `${(r.value / top) * 100}%`, background: Array.isArray(color) ? color[i % color.length] : color }} /></span>
          <span className="hv">{nf(r.value)}{unit}</span>
        </div>
      ))}
    </div>
  )
}

/** Vertical columns with optional second overlaid series. points = [{label, a, b}] */
export function Columns({ points, aLabel = '', bLabel = '', height = 190, highlight }) {
  const [tip, setTip] = useState(null)
  if (!points?.length) return <Empty />
  const W = 640, H = height, pad = { l: 40, r: 8, t: 10, b: 26 }
  const max = Math.max(...points.map((p) => Math.max(p.a || 0, p.b || 0)), 1)
  const bw = (W - pad.l - pad.r) / points.length
  const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - v / max)
  const ticks = [0, 0.5, 1].map((f) => f * max)
  const every = Math.ceil(points.length / 12)
  return (
    <div className="chartbox">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${aLabel} chart`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="#e3e8e4" />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" fontSize="10" fill="#6b7a72">{nf(Math.round(t))}</text>
          </g>
        ))}
        {points.map((p, i) => {
          const x = pad.l + i * bw
          const hot = highlight && highlight(p)
          return (
            <g key={i} onMouseEnter={() => setTip({ x: x + bw / 2, p })} onMouseLeave={() => setTip(null)}>
              <rect x={x + 1} y={y(p.a || 0)} width={Math.max(bw - 2, 1)} height={H - pad.b - y(p.a || 0)} fill={hot ? '#f59e0b' : GREEN} opacity={p.b != null ? 0.35 : 0.9} rx="2" />
              {p.b != null && <rect x={x + bw * 0.2} y={y(p.b)} width={Math.max(bw * 0.6, 1)} height={H - pad.b - y(p.b)} fill={GREEN} rx="2" />}
              {i % every === 0 && <text x={x + bw / 2} y={H - 8} textAnchor="middle" fontSize="10" fill="#6b7a72">{p.label}</text>}
            </g>
          )
        })}
      </svg>
      {tip && (
        <div className="charttip" style={{ left: `${(tip.x / W) * 100}%` }}>
          <b>{tip.p.label}</b><br />{aLabel}: {nf(tip.p.a)}{tip.p.b != null && <><br />{bLabel}: {nf(tip.p.b)}</>}
        </div>
      )}
    </div>
  )
}

/** Funnel: stages = [{stage, count}] */
export function Funnel({ stages }) {
  if (!stages?.length) return <Empty />
  const top = Math.max(stages[0].count, 1)
  return (
    <div className="funnel">
      {stages.map((s, i) => (
        <div key={s.stage} className="fstep">
          <div className="fbar" style={{ width: `${Math.max((s.count / top) * 100, 4)}%`, background: COLORS[i % COLORS.length] }}>
            <b>{nf(s.count)}</b>
          </div>
          <span>{s.stage.replace('_', ' ')}{i > 0 && stages[i - 1].count ? ` · ${Math.round((s.count / stages[i - 1].count) * 100)}% of previous` : ''}</span>
        </div>
      ))}
    </div>
  )
}

export function Stat({ title, value, hint }) {
  return (
    <div className="counter">
      <div className="cval">{nf(value)}</div>
      <div className="clabel">{title}</div>
      {hint && <div className="chint">{hint}</div>}
    </div>
  )
}

export const PALETTE = COLORS
