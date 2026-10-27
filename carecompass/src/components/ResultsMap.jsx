import { useEffect, useMemo } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Circle, MapContainer, Marker, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { moneyRound } from '../lib/format'

function Fit({ points, origin, radius }) {
  const map = useMap()
  const key = points.map((p) => p.id).join(',') + (origin ? `${origin.lat},${origin.lng}` : '')
  useEffect(() => {
    const fit = () => {
      const ll = points.map((p) => [p.lat, p.lng])
      if (origin) ll.push([origin.lat, origin.lng])
      if (!ll.length) return
      if (ll.length === 1) map.setView(ll[0], 11)
      else map.fitBounds(L.latLngBounds(ll).pad(0.12), { maxZoom: 13 })
    }
    const el = map.getContainer()
    let hidden = el.clientWidth === 0
    if (!hidden) fit()
    const ro = new ResizeObserver(() => {
      map.invalidateSize()
      if (hidden && el.clientWidth > 0) { hidden = false; fit() } else if (el.clientWidth === 0) hidden = true
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [key, radius]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

function FlyTo({ target }) {
  const map = useMap()
  useEffect(() => { if (target) map.flyTo([target.lat, target.lng], Math.max(map.getZoom(), 13), { duration: 0.6 }) }, [target, map])
  return null
}

const label = (r) => r.price.total == null ? '%' : moneyRound(r.est.patient)

export default function ResultsMap({ rows, origin, radius, activeId, hoverId, onSelect, onHover, flyTarget }) {
  const pts = useMemo(() => {
    const seen = {}
    return rows.map((r) => {
      const k = `${r.place.lat.toFixed(4)},${r.place.lng.toFixed(4)}`
      const n = (seen[k] = (seen[k] || 0) + 1) - 1
      const a = n * 2.1
      return { ...r, lat: r.place.lat + (n ? 0.0009 * Math.sin(a) : 0), lng: r.place.lng + (n ? 0.0012 * Math.cos(a) : 0) }
    })
  }, [rows])
  const home = L.divIcon({ className: 'home-pin', html: '<div></div>', iconSize: [0, 0] })
  const icon = (r) => L.divIcon({
    className: `price-pin ${r.tier} ${r.id === activeId || r.id === hoverId ? 'active' : ''} ${r.price.badge === 'h' ? 'warn' : ''}`,
    html: `<div>${label(r)}</div>`, iconSize: [0, 0],
  })
  return (
    <MapContainer center={[38.5, -92.4]} zoom={7} scrollWheelZoom className="h-full w-full" zoomControl={false} attributionControl>
      <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        attribution="Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors" maxZoom={16} />
      <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}" maxZoom={16} />
      <Fit points={pts} origin={origin} radius={radius} />
      <FlyTo target={flyTarget} />
      {origin && <Circle center={[origin.lat, origin.lng]} radius={radius * 1609.34}
        pathOptions={{ color: '#2a6fd0', weight: 1, fillOpacity: 0.04, dashArray: '4 6' }} />}
      {origin && <Marker position={[origin.lat, origin.lng]} icon={home} interactive={false} />}
      {pts.map((r) => (
        <Marker key={r.id} position={[r.lat, r.lng]} icon={icon(r)} zIndexOffset={r.id === activeId || r.id === hoverId ? 1000 : 0}
          eventHandlers={{ click: () => onSelect(r.id), mouseover: () => onHover?.(r.id), mouseout: () => onHover?.(null) }}>
          <Tooltip direction="top" offset={[0, -30]} opacity={1}>
            <div className="text-[12px] font-semibold">{r.place.name}</div>
            <div className="text-[11px] text-slate-500">{r.place.city}{r.distance == null ? '' : ` · ${r.distance.toFixed(1)} mi`}</div>
          </Tooltip>
        </Marker>
      ))}
    </MapContainer>
  )
}
