export function miles(a, b) {
  const r = (d) => (d * Math.PI) / 180
  const dLat = r(b.lat - a.lat)
  const dLng = r(b.lng - a.lng)
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(dLng / 2) ** 2
  return 7917.6 * Math.asin(Math.sqrt(h))
}
export const directionsUrl = (p) =>
  `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(`${p.name}, ${p.a}, ${p.c}, ${p.s} ${p.z}`)}`
export const titleCase = (s) =>
  String(s || '').toLowerCase().replace(/(^|[\s\-/(&.,])([a-z])/g, (m, a, b) => a + b.toUpperCase())
    .replace(/\b(Llc|Pc|Pllc|Pa|Lp|Md|Do|Np|Inc|Ii|Iii|Ut|Ssm|Bjc|Mri|Ct|Us|Usa|Er|Tms|Hca|Aprn|Lcsw|Lpc|Lcpc|Ms|Phd|Psyd)\b/g, (m) => m.toUpperCase())
