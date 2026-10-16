import { useEffect, useMemo, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster'
import 'leaflet.markercluster/dist/MarkerCluster.css'
import 'leaflet.markercluster/dist/MarkerCluster.Default.css'
import { Circle, CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import { CATEGORIES, STATUSES, STATUS_COLOR, label } from './bits.jsx'

const LINE_STATUSES = ['accepted', 'picked_up', 'delivered']
const ngoIcon = L.divIcon({ className: 'ngo-icon', html: '<i></i>', iconSize: [16, 16], iconAnchor: [8, 8] })

/** Imperative marker-cluster layer. Rebuilt only when the visible pin set actually changes. */
function ClusterLayer({ pins, onPick }) {
  const map = useMap()
  const sig = useMemo(() => pins.map((p) => `${p.id}:${p.status}`).join('|'), [pins])
  useEffect(() => {
    const group = L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 38, chunkedLoading: true })
    pins.forEach((p) => {
      const m = L.circleMarker([p.lat, p.lng], {
        radius: Math.min(10, 4 + p.kg / 10), color: '#fff', weight: 1,
        fillColor: STATUS_COLOR[p.status] || '#666', fillOpacity: 0.9,
      })
      m.bindPopup(`<b>${p.food}</b><br/>${p.kg} kg · ${label(p.category)}<br/>${p.area} · <i>${label(p.status)}</i>`)
      m.on('click', () => onPick(p))
      group.addLayer(m)
    })
    map.addLayer(group)
    return () => { map.removeLayer(group) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, map])
  return null
}

export default function MapView({ pins, ngos = [] }) {
  const [hidden, setHidden] = useState(new Set(['delivered']))   // delivered pins hidden by default: keeps the map readable
  const [category, setCategory] = useState('')
  const [cluster, setCluster] = useState(true)
  const [lines, setLines] = useState(true)
  const [showNgos, setShowNgos] = useState(true)
  const [picked, setPicked] = useState(null)

  const toggle = (s) => setHidden((h) => { const n = new Set(h); n.has(s) ? n.delete(s) : n.add(s); return n })
  const visible = useMemo(() => pins.filter((p) => !hidden.has(p.status) && (!category || p.category === category)),
    [pins, hidden, category])
  const linked = visible.filter((p) => p.ngo && LINE_STATUSES.includes(p.status))

  return (
    <div>
      <div className="mapbar">
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category filter">
          <option value="">All categories</option>
          {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <label><input type="checkbox" checked={cluster} onChange={(e) => setCluster(e.target.checked)} />cluster</label>
        <label><input type="checkbox" checked={lines} onChange={(e) => setLines(e.target.checked)} />match lines</label>
        <label><input type="checkbox" checked={showNgos} onChange={(e) => setShowNgos(e.target.checked)} />NGOs</label>
        <span className="muted small">{visible.length} of {pins.length} pins</span>
      </div>
      <MapContainer center={[19.06, 73.02]} zoom={12} scrollWheelZoom className="map" data-testid="map">
        <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {lines && linked.map((p) => (
          <Polyline key={`l${p.id}`} positions={[[p.lat, p.lng], p.ngo]}
            pathOptions={{ color: STATUS_COLOR[p.status], weight: 2, opacity: 0.55, dashArray: p.status === 'accepted' ? '4 6' : undefined }} />
        ))}
        {showNgos && ngos.map((n) => (
          <Marker key={`n${n.id}`} position={[n.lat, n.lng]} icon={ngoIcon}>
            <Popup><b>{n.name}</b><br />NGO · {n.area}</Popup>
          </Marker>
        ))}
        {picked && (
          <Circle center={[picked.lat, picked.lng]} radius={15000}
            pathOptions={{ color: '#15803d', weight: 1, dashArray: '6 6', fillOpacity: 0.04 }} />
        )}
        {cluster
          ? <ClusterLayer pins={visible} onPick={setPicked} />
          : visible.map((p) => (
            <CircleMarker key={p.id} center={[p.lat, p.lng]} radius={Math.min(10, 4 + p.kg / 10)} eventHandlers={{ click: () => setPicked(p) }}
              pathOptions={{ color: '#fff', weight: 1, fillColor: STATUS_COLOR[p.status] || '#666', fillOpacity: 0.85 }}>
              <Popup><b>{p.food}</b><br />{p.kg} kg · {label(p.category)}<br />{p.area} · <i>{label(p.status)}</i></Popup>
            </CircleMarker>
          ))}
      </MapContainer>
      <div className="legend">
        {[...STATUSES, 'expired'].map((s) => (
          <button key={s} type="button" className={`legbtn ${hidden.has(s) ? 'off' : ''}`} onClick={() => toggle(s)}
            title="Click to show / hide" aria-pressed={!hidden.has(s)}>
            <i style={{ background: STATUS_COLOR[s] }} />{label(s)}
          </button>
        ))}
        <span className="legbtn static"><i className="sq" />NGO</span>
        {picked && <button type="button" className="link" onClick={() => setPicked(null)}>clear 15 km radius</button>}
      </div>
    </div>
  )
}
