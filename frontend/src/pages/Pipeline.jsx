import { api } from '../api.js'
import { Columns, Stat } from '../components/charts.jsx'
import { usePolling } from '../components/bits.jsx'

const ORDER = ['postgres', 'mongo', 'rabbitmq', 'worker', 'delta', 'elasticsearch', 'nifi', 'airflow']
const NAMES = { postgres: 'PostgreSQL', mongo: 'MongoDB', rabbitmq: 'RabbitMQ', worker: 'Matching worker', delta: 'Delta Lake',
  elasticsearch: 'Elasticsearch', nifi: 'Apache NiFi', airflow: 'Apache Airflow' }

function metrics(key, s) {
  switch (key) {
    case 'postgres': return [`${s.donations ?? 0} donations`, `${s.rejected_rows ?? 0} rejected rows`]
    case 'mongo': return [`${s.raw_rows ?? 0} raw rows`, `${s.events ?? 0} event payloads`]
    case 'rabbitmq': return [`queue depth ${s.queue_depth ?? '-'}`, `${s.published ?? 0} published · ${s.delivered ?? 0} delivered`]
    case 'worker': return [`${s.lag_seconds ?? 0}s oldest unmatched`]
    case 'delta': return s.versions ? [`donations v${s.versions.donation_history ?? '-'}`, `status events v${s.versions.status_events ?? '-'}`] : []
    default: return []
  }
}

export default function Pipeline() {
  const [h, err] = usePolling(() => api('/health/pipeline'), 3000)
  if (!h) return <section className="card">{err ? <div className="alert error">{err}</div> : 'Checking the pipeline…'}</section>
  const p = h.pipeline
  return (
    <>
      {h.alerts.length > 0
        ? <div className="alert error" role="alert">{h.alerts.map((a) => <div key={a}>⚠ {a}</div>)}</div>
        : <div className="alert ok">All enabled stages are healthy.</div>}

      <section className="health-grid">
        {ORDER.map((k) => {
          const s = h.services[k]
          if (!s) return null
          const state = s.ok === null ? 'off' : s.ok ? 'ok' : 'bad'
          return (
            <div key={k} className={`svc ${state}`} data-testid={`svc-${k}`}>
              <div className="svc-head"><i />{NAMES[k]}</div>
              <div className="svc-state">{state === 'off' ? 'not enabled' : state === 'ok' ? 'healthy' : 'down'}</div>
              {metrics(k, s).map((m) => <div key={m} className="small muted">{m}</div>)}
              {state === 'bad' && <div className="small" style={{ color: '#991b1b' }}>{s.detail}</div>}
              {state === 'off' && <div className="small muted">start the matching compose profile</div>}
            </div>
          )
        })}
      </section>

      <section className="counters">
        <Stat title="Rows / 5 min" value={p.rows_last_5min} hint={`${p.batches_last_5min} batches`} />
        <Stat title="Reject rate (1 h)" value={`${Math.round(p.reject_rate_1h * 100)}%`} />
        <Stat title="Last batch" value={p.last_batch_age_s == null ? '-' : `${p.last_batch_age_s}s`} hint="ago" />
        <Stat title="Queue depth" value={h.services.rabbitmq.queue_depth ?? '-'} />
        <Stat title="Worker lag" value={`${p.oldest_unmatched_age_s}s`} hint="oldest unmatched donation" />
        <Stat title="Consumers" value={h.services.rabbitmq.consumers ?? 0} />
      </section>

      <section className="card">
        <h2>Ingest throughput <span className="muted small">rows per minute, last 15 minutes</span></h2>
        <Columns points={h.throughput.map((t) => ({ label: new Date(t.ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }), a: t.rows }))}
          aLabel="rows" />
      </section>
    </>
  )
}
