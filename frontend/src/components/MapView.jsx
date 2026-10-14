import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { STATUSES, STATUS_COLOR, label } from './bits.jsx'

export default function MapView({ pins }) {
  return (
    <div>
      <MapContainer center={[19.06, 73.02]} zoom={12} scrollWheelZoom className="map">
        <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {pins.map((p) => (
          <CircleMarker key={p.id} center={[p.lat, p.lng]} radius={Math.min(10, 4 + p.kg / 10)}
            pathOptions={{ color: '#fff', weight: 1, fillColor: STATUS_COLOR[p.status] || '#666', fillOpacity: 0.85 }}>
            <Popup>
              <b>{p.food}</b><br />{p.kg} kg · {label(p.category)}<br />{p.area} · <i>{label(p.status)}</i>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
      <div className="legend">
        {[...STATUSES, 'expired'].map((s) => (
          <span key={s}><i style={{ background: STATUS_COLOR[s] }} />{label(s)}</span>
        ))}
      </div>
    </div>
  )
}
