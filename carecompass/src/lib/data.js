import procedures from '../data/procedures.json'
import { miles } from './geo'

export const DATA = import.meta.env.VITE_DATA_URL || 'https://huggingface.co/buckets/ratecommons/work/resolve/shop/v1'
export const PROCS = procedures
export const PROC_BY_ID = Object.fromEntries(procedures.map((p) => [p.id, p]))
export const CATEGORIES = [...new Set(procedures.map((p) => p.cat))]

const cache = new Map()
async function getJSON(path) {
  if (cache.has(path)) return cache.get(path)
  const pr = fetch(`${DATA}/${path}`).then((r) => (r.ok ? r.json() : null)).catch(() => null)
  cache.set(path, pr)
  return pr
}

export const loadProducts = () => getJSON('meta/products.json')
export const loadZip3Index = () => getJSON('meta/zip3.json')

export async function zipToPoint(zip) {
  if (!/^\d{5}$/.test(zip || '')) return null
  const z = await getJSON(`meta/zip/${zip.slice(0, 3)}.json`)
  const v = z?.[zip]
  return v ? { lat: v[0], lng: v[1], state: v[2] } : null
}

/** Offer files near a point: every ZIP3 area whose centre is within radius + a margin. */
export async function loadPlaces(procId, origin, radius) {
  const idx = await loadZip3Index()
  if (!idx || !origin) return []
  const want = []
  for (const [z3, [lat, lng, r3, states]] of Object.entries(idx)) {
    const d = miles(origin, { lat, lng })
    if (d <= radius + r3 + 2) for (const st of states) want.push(`offers/${procId}/${z3}-${st}.json`)
  }
  const files = await Promise.all(want.slice(0, 160).map(getJSON))
  const out = []
  for (const f of files) if (f) for (const p of f.places) { p.g = f.g || {}; out.push(p) }
  return out
}

// offer tuple fields
const PAYER = 0, ROLE = 1, CODE = 2, NTYPE = 3, RATE = 4, INST = 5, OFFICE = 6, BADGE = 7, PRODS = 8, TINS = 9,
  GNAMES = 10, NQ = 11, NEV = 12, LO = 13, HI = 14, N = 15
export const BADGE_RANK = { c: 3, l: 2, h: 1, x: 0 }
const DOLLAR = (o) => o[BADGE] !== 'x'

const median = (xs) => {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b)
  return s[Math.floor((s.length - 1) / 2)]
}

function pick(offers, filter, g = {}) {
  let xs = offers.filter(filter)
  if (!xs.length) return null
  // prefer the strongest evidence: confirmed over likely over hidden
  const top = Math.max(...xs.map((o) => BADGE_RANK[o[BADGE]]))
  xs = xs.filter((o) => BADGE_RANK[o[BADGE]] === top)
  const rates = xs.map((o) => o[RATE])
  const best = xs.reduce((b, o) => (BADGE_RANK[o[BADGE]] > BADGE_RANK[b[BADGE]] ? o : b), xs[0])
  const groups = [...new Set(xs.flatMap((o) => o[GNAMES] || (o[TINS] || []).map((t) => g[t]).filter(Boolean)))]
  return {
    rate: median(rates), lo: Math.min(...xs.map((o) => o[LO] ?? o[RATE])), hi: Math.max(...xs.map((o) => o[HI] ?? o[RATE])),
    n: xs.reduce((s, o) => s + (o[N] || 1), 0), badge: best[BADGE],
    groups, tins: [...new Set(xs.flatMap((o) => o[TINS] || []))], nq: Math.max(...xs.map((o) => o[NQ] || 0)),
    nev: Math.max(...xs.map((o) => o[NEV] || 0)), offers: xs,
  }
}

/**
 * The price at one place for one procedure and plan.
 * Returns null when the place has nothing usable, else {total, bills[], badge, notes[], ...}.
 */
export function priceAt(place, proc, sel) {
  const r = priceAt0(place, proc, sel)
  if (r) {
    const m = r.complete || r.facility || r.flat || r.base || r.reading
    r.nq = m?.nq || 0
    r.nev = m?.nev || 0
  }
  return r
}

function priceAt0(place, proc, sel) {
  const { payer, product, showHidden, patient = 'returning' } = sel
  const ok = (o) => o[PAYER] === payer && (product == null || (o[PRODS] || []).includes(product))
    && (o[BADGE] === 'c' || o[BADGE] === 'l' || (showHidden && o[BADGE] === 'h'))
  const offers = (place.o || []).filter(ok)
  const P = (f) => pick(offers, f, place.g)
  const pct = (place.o || []).filter((o) => o[PAYER] === payer && o[BADGE] === 'x' && o[NTYPE] === 'percentage'
    && (product == null || (o[PRODS] || []).includes(product)))
  const notes = []
  if (proc.kind === 'imaging') {
    const code = proc.codes[0]
    const hosp = place.kind === 'hospital'
    // at a hospital the facility fee is the hospital's own (institutional) contract; a physician group's TC price is not it
    const complete = hosp ? null : P((o) => o[ROLE] === 'global' && !o[INST] && o[CODE] === code)
    const facility = hosp
      ? P((o) => o[CODE] === code && o[INST] && (o[ROLE] === 'tc' || o[ROLE] === 'global'))
      : P((o) => o[CODE] === code && (o[ROLE] === 'tc' || (o[ROLE] === 'global' && o[INST])))
    let reading = P((o) => o[ROLE] === 'pro' && o[CODE] === code)
    // who reads here: groups with reading contracts at this address, plus groups whose radiologists Medicare
    // lists at this hospital
    const byTin = {}
    const add = (tin, rate, nrad, here) => {
      const r = (byTin[tin] ||= { tin, name: place.g?.[tin] || `Tax ID ${tin}`, nrad: 0, rates: [], here: false })
      r.rates.push(rate); r.nrad = Math.max(r.nrad, nrad || 0); r.here ||= here
    }
    for (const o of reading ? reading.offers : []) add((o[TINS] || [])[0], o[RATE], o[NQ], true)
    for (const t of (place.t || []).filter((t) => t[0] === payer && (product == null || (t[4] || []).includes(product)) && t[1] === code)) {
      add(t[5], t[3], t[7], false)
    }
    let readers = Object.values(byTin).filter((r) => r.tin).map((r) => ({ ...r, rate: median(r.rates) }))
      .sort((a, b) => b.here - a.here || b.nrad - a.nrad)
    if (!readers.length) readers = null
    if (!reading && readers) {
      reading = { rate: median(readers.map((r) => r.rate)), lo: Math.min(...readers.map((r) => r.rate)),
        hi: Math.max(...readers.map((r) => r.rate)), badge: 'l', groups: readers.map((r) => r.name), fromTeam: true }
    }
    const facPct = pct.find((o) => o[CODE] === code && (o[ROLE] === 'tc' || o[ROLE] === 'global') && (!hosp || o[INST]))
    if (complete && !facility) {
      return { kind: 'complete', total: complete.rate, lo: complete.lo, hi: complete.hi, badge: complete.badge,
        bills: [{ key: 'complete', label: 'Scan and reading (one bill)', short: 'scan + reading', allowed: complete.rate,
          from: complete.groups[0] }], complete, facility, reading, readers, notes }
    }
    if (complete && facility && !hosp && complete.rate <= facility.rate + (reading?.rate || 0)) {
      return { kind: 'complete', total: complete.rate, lo: complete.lo, hi: complete.hi, badge: complete.badge,
        bills: [{ key: 'complete', label: 'Scan and reading (one bill)', short: 'scan + reading', allowed: complete.rate,
          from: complete.groups[0] }], complete, facility, reading, readers, notes }
    }
    if (facility) {
      const bills = [{ key: 'facility', label: 'Facility bill (technical fee)', short: 'facility', allowed: facility.rate,
        from: facility.groups[0] }]
      if (reading) bills.push({ key: 'professional', label: 'Radiologist bill (reading fee)', short: 'radiologist',
        allowed: reading.rate, from: reading.groups[0] })
      else notes.push('The radiologist reading fee is not in the published data for this place; expect a separate bill.')
      return { kind: 'split', total: bills.reduce((s, b) => s + b.allowed, 0), badge: facility.badge, bills, facility,
        reading, readers, notes, partial: !reading }
    }
    if (reading && (hosp || facPct)) {
      notes.push(facPct
        ? `The hospital's facility fee is a contract of ${facPct[RATE]}% of its own charges, so no dollar amount is published. Ask the hospital for its price for code ${code}.`
        : `The hospital's facility fee for code ${code} is not in the published data. Ask the hospital for its price.`)
      return { kind: 'pct', total: reading.rate, badge: reading.badge, bills: [{ key: 'professional', label: 'Radiologist bill (reading fee)',
        short: 'radiologist', allowed: reading.rate, from: reading.groups[0] }], reading, readers, facilityPct: facPct?.[RATE],
      notes, partial: true }
    }
    return null
  }
  // visits and services
  const main = proc.codes.length > 1 && proc.kind === 'visit' && patient === 'new' ? proc.codes[1] : proc.codes[0]
  const flat = P((o) => o[CODE] === 'FLAT' && DOLLAR(o))
  const base = P((o) => o[CODE] === main)
  const addon = (proc.addon || []).length ? P((o) => proc.addon.includes(o[CODE])) : null
  const alt = (proc.alt || []).length ? P((o) => proc.alt.includes(o[CODE])) : null
  const second = proc.codes.length > 1 && proc.kind === 'service' ? P((o) => o[CODE] === proc.codes[1]) : null
  if (flat && proc.kind === 'visit') {
    return { kind: 'flat', total: flat.rate, lo: flat.lo, hi: flat.hi, badge: flat.badge, flat, base, addon, alt,
      bills: [{ key: 'flat', label: 'Flat per-visit amount', short: 'flat visit fee', allowed: flat.rate, from: flat.groups[0] }],
      notes: [`${flat.groups[0] || 'This clinic'} has a flat per-visit contract with this insurer, so the visit is not priced code by code.`] }
  }
  if (!base) {
    const p = pct.find((o) => o[CODE] === main)
    if (p) return { kind: 'pctonly', total: null, badge: 'x', bills: [], notes: [`This contract pays ${p[RATE]}% of the provider's own charges, so no dollar price is published. Ask the office for its price.`] }
    return null
  }
  const bills = [{ key: 'base', label: proc.kind === 'visit' ? 'Visit' : proc.short, short: proc.short.toLowerCase(),
    allowed: base.rate, from: base.groups[0] }]
  if (second) notes.push(`A related code (${proc.codes[1]}) is priced at about $${Math.round(second.rate)} here; ask which one your visit will use.`)
  if (addon) notes.push(`Some clinics also bill an urgent-care center fee (${addon.rate ? `about $${Math.round(addon.rate)}` : 'extra'}) with the visit.`)
  return { kind: 'single', total: base.rate, lo: base.lo, hi: base.hi, badge: base.badge, base, addon, alt, second, bills, notes }
}

export function placeKindLabel(k) {
  return { hospital: 'Hospital', imaging: 'Imaging center', urgent: 'Urgent care', lab: 'Lab', clinic: 'Clinic / practice' }[k] || 'Clinic / practice'
}
