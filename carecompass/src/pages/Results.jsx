import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle, ArrowDownUp, ArrowLeft, Baby, Building2, CheckCircle2, Clock, Eye, EyeOff, ExternalLink, Globe, List,
  Loader2, Map as MapIcon, MapPin, Navigation, Pencil, Phone, Search, SlidersHorizontal, Stethoscope, Users, X,
} from 'lucide-react'
import { PROC_BY_ID, loadPlaces, placeKindLabel, priceAt, zipToPoint } from '../lib/data'
import { estimate, isPersonalized } from '../lib/cost'
import { money, moneyRound, PAYER_NAMES } from '../lib/format'
import { miles, titleCase } from '../lib/geo'
import { useProfile } from '../lib/store'
import InfoTip from '../components/InfoTip'
import Badge from '../components/Badge'
import Modal from '../components/Modal'
import SearchForm, { usePlans } from '../components/SearchForm'
import CostProfileForm from '../components/CostProfileForm'
import { Tag } from '../components/ProcedurePicker'

const ResultsMap = lazy(() => import('../components/ResultsMap'))

const KINDS = ['hospital', 'imaging', 'urgent', 'clinic', 'lab']
const directions = (p) => `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(`${p.name}, ${p.a}, ${p.city}, ${p.s} ${p.z}`)}`
const phoneFmt = (p) => (p && /^\d{10}$/.test(p) ? `${p.slice(0, 3)}-${p.slice(3, 6)}-${p.slice(6)}` : p)

function usePlaces(procId, origin, radius) {
  const [st, setSt] = useState({ loading: true, places: [] })
  useEffect(() => {
    let live = true
    if (!origin) return undefined
    setSt({ loading: true, places: [] })
    loadPlaces(procId, origin, radius).then((places) => live && setSt({ loading: false, places }))
    return () => { live = false }
  }, [procId, origin?.lat, origin?.lng, radius]) // eslint-disable-line react-hooks/exhaustive-deps
  return st
}

export default function Results() {
  const [sp, setSp] = useSearchParams()
  const procId = sp.get('proc')
  const proc = PROC_BY_ID[procId]
  const zip = sp.get('zip') || ''
  const payer = sp.get('payer') || 'aetna'
  const prodRaw = sp.get('prod')
  const product = prodRaw === null || prodRaw === '' ? null : parseInt(prodRaw, 10)
  const radius = parseInt(sp.get('r') || '25', 10)
  const patient = sp.get('pt') || 'returning'
  const kid = sp.get('kid') === '1'
  const showHidden = sp.get('hidden') === '1'
  const plans = usePlans(payer)
  const planName = product != null && plans ? plans[product] : null
  const payerName = PAYER_NAMES[payer] || payer
  const { profile } = useProfile()
  const personal = isPersonalized(profile)

  const [origin, setOrigin] = useState(undefined)
  useEffect(() => { zipToPoint(zip).then((p) => setOrigin(p)) }, [zip])
  const { loading, places } = usePlaces(procId, origin, radius)

  const [sort, setSort] = useState('cost')
  const [kinds, setKinds] = useState([])
  const [q, setQ] = useState('')
  const [view, setView] = useState('list')
  const [active, setActive] = useState(null)
  const [hover, setHover] = useState(null)
  const [edit, setEdit] = useState(false)
  const [personalize, setPersonalize] = useState(false)
  const listRef = useRef(null)

  const setParam = (k, v) => {
    const n = new URLSearchParams(sp)
    if (v === null || v === '' || v === false) n.delete(k)
    else n.set(k, v)
    setSp(n, { replace: true })
  }

  const all = useMemo(() => {
    if (!proc || !origin) return { rows: [], hiddenCount: 0 }
    const sel = { payer, product, showHidden, patient }
    const rows = []
    let hiddenCount = 0
    for (const place of places) {
      const d = miles(origin, place)
      if (d > radius) continue
      const price = priceAt(place, proc, sel)
      if (!price) {
        if (!showHidden && priceAt(place, proc, { ...sel, showHidden: true })) hiddenCount++
        continue
      }
      const est = price.total == null ? null : estimate(price.bills, profile, payerName)
      rows.push({ id: place.k, place: { ...place, name: titleCase(place.n), city: titleCase(place.c) }, price, est, distance: d })
    }
    return { rows, hiddenCount }
  }, [places, proc, origin, radius, payer, product, showHidden, patient, profile, payerName])

  const rows = useMemo(() => {
    const t = q.trim().toLowerCase()
    const xs = all.rows.filter((r) => (!kinds.length || kinds.includes(r.place.kind) || (kinds.includes('kids') && r.place.kids))
      && (!t || `${r.place.n} ${r.place.a} ${r.place.c} ${(r.price.bills || []).map((b) => b.from).join(' ')} ${(r.price.readers || []).map((x) => x.name).join(' ')}`
        .toLowerCase().includes(t)))
    const priced = xs.map((r) => r.price.total).filter((v) => v != null).sort((a, b) => a - b)
    const lo = priced[Math.floor(priced.length / 3)]
    const hi = priced[Math.floor((2 * priced.length) / 3)]
    xs.forEach((r) => {
      const v = r.price.total
      r.tier = v == null ? 'none' : priced.length < 3 ? 'mid' : v <= lo ? 'low' : v < hi ? 'mid' : 'high'
    })
    const key = (r) => (r.est ? r.est.patient : Infinity)
    const cmp = {
      cost: (a, b) => (kid ? (b.place.kids - a.place.kids) : 0) || !!a.price.partial - !!b.price.partial || key(a) - key(b) || (a.price.total ?? 1e12) - (b.price.total ?? 1e12),
      total: (a, b) => !!a.price.partial - !!b.price.partial || (a.price.total ?? 1e12) - (b.price.total ?? 1e12),
      distance: (a, b) => a.distance - b.distance,
    }[sort]
    return xs.sort(cmp)
  }, [all.rows, kinds, q, sort, kid])

  const stats = useMemo(() => {
    const ts = rows.filter((r) => r.price.total != null && !r.price.partial).map((r) => r.price.total).sort((a, b) => a - b)
    if (!ts.length) return null
    const ps = rows.filter((r) => r.est && !r.price.partial).map((r) => r.est.patient)
    return { min: ts[0], max: ts[ts.length - 1], median: ts[Math.floor((ts.length - 1) / 2)], pMin: Math.min(...ps), pMax: Math.max(...ps) }
  }, [rows])

  const counts = useMemo(() => all.rows.reduce((m, r) => {
    m[r.place.kind] = (m[r.place.kind] || 0) + 1
    if (r.place.kids) m.kids = (m.kids || 0) + 1
    return m
  }, {}), [all.rows])

  useEffect(() => {
    if (active && listRef.current) listRef.current.querySelector(`[data-id="${CSS.escape(active)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [active])

  if (!proc || !/^\d{5}$/.test(zip)) return <Navigate to="/" replace />
  if (origin === null) return <Navigate to="/" replace />
  const sel = rows.find((r) => r.id === active)

  return (
    <div className="flex h-[calc(100dvh-4rem)] flex-col">
      <div className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-[1600px] flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4 sm:px-6">
          <div className="min-w-0 flex-1">
            <div className="flex items-start gap-2">
              <span className="mt-1"><Tag p={proc} /></span>
              <h1 className="text-base font-bold leading-snug sm:text-xl">{proc.name}</h1>
            </div>
            <p className="mt-0.5 text-xs text-ink-mute">
              Code {proc.kind === 'visit' && proc.codes.length > 1 && patient === 'new' ? proc.codes[1] : proc.codes[0]}
              {proc.kind === 'visit' && proc.codes.length > 1 && ` · ${patient === 'new' ? 'new' : 'returning'} patient`}
              {' '}· {payerName}{planName ? ` · ${planName}` : ' · any plan'} · near {zip}{kid ? ' · for a child' : ''}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setPersonalize(true)} className={`btn-ghost ${personal ? '!border-mint-200 !text-mint-700' : ''}`}>
              <SlidersHorizontal className="h-4 w-4" /> {personal ? 'Personalized ✓' : 'Personalize'}
            </button>
            <button onClick={() => setEdit(true)} className="btn-ghost"><Pencil className="h-4 w-4" /> Edit<span className="hidden sm:inline"> search</span></button>
          </div>
        </div>
        <div className="mx-auto flex max-w-[1600px] items-center gap-2 overflow-x-auto px-4 pb-3 sm:flex-wrap sm:px-6 [&>*]:shrink-0">
          <label className="relative">
            <span className="sr-only">Sort</span>
            <ArrowDownUp className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-mute" />
            <select value={sort} onChange={(e) => setSort(e.target.value)} className="h-9 rounded-full border border-line bg-white pl-8 pr-8 text-sm font-medium">
              <option value="cost">Lowest cost to me</option>
              <option value="total">Lowest negotiated price</option>
              <option value="distance">Nearest</option>
            </select>
          </label>
          <label className="relative">
            <span className="sr-only">Distance</span>
            <MapPin className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-mute" />
            <select value={radius} onChange={(e) => setParam('r', e.target.value)} className="h-9 rounded-full border border-line bg-white pl-8 pr-8 text-sm font-medium">
              {[5, 10, 25, 50, 100].map((v) => <option value={v} key={v}>{v} miles</option>)}
            </select>
          </label>
          <label className="relative">
            <span className="sr-only">Search by name</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-mute" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Place, group or doctor"
              className="h-9 w-48 rounded-full border border-line bg-white pl-8 pr-3 text-sm" />
          </label>
          {[...KINDS, 'kids'].filter((k) => counts[k]).map((k) => {
            const on = kinds.includes(k)
            return (
              <button key={k} onClick={() => setKinds((xs) => (on ? xs.filter((x) => x !== k) : [...xs, k]))}
                className={`h-9 rounded-full border px-3 text-sm font-medium transition ${on ? 'border-brand-600 bg-brand-600 text-white' : 'border-line bg-white text-ink-soft hover:border-brand-200'}`}>
                {k === 'kids' ? 'Children’s' : placeKindLabel(k)} <span className={on ? 'text-white/70' : 'text-ink-mute'}>{counts[k]}</span>
              </button>
            )
          })}
          <button onClick={() => setParam('hidden', showHidden ? null : '1')}
            className={`flex h-9 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition ${showHidden ? 'border-red-300 bg-red-50 text-red-700' : 'border-line bg-white text-ink-soft hover:border-brand-200'}`}>
            {showHidden ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />} {showHidden ? 'Showing hidden prices' : 'Show hidden prices'}
            <InfoTip k="hidden" />
          </button>
          <div className="order-first ml-auto inline-flex rounded-full border border-line bg-white p-0.5 sm:order-none lg:hidden">
            {[['list', List, 'List'], ['map', MapIcon, 'Map']].map(([k, Icon, l]) => (
              <button key={k} onClick={() => setView(k)} className={`flex items-center gap-1 rounded-full px-3 py-1.5 text-sm font-semibold ${view === k ? 'bg-brand-600 text-white' : 'text-ink-soft'}`}>
                <Icon className="h-4 w-4" />{l}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mx-auto flex min-h-0 w-full max-w-[1600px] flex-1">
        <div ref={listRef} className={`${view === 'list' ? 'block' : 'hidden'} w-full overflow-y-auto lg:block lg:w-[46%] xl:w-[42%]`}>
          <div className="p-4 sm:p-5">
            {(loading || origin === undefined) ? (
              <div className="card flex items-center justify-center gap-2 p-10 text-ink-mute"><Loader2 className="h-5 w-5 animate-spin" /> Finding prices near {zip}…</div>
            ) : stats ? (
              <div className="mb-4 rounded-2xl bg-brand-800 p-4 text-white">
                <p className="text-sm text-brand-100"><b className="text-white">{rows.length}</b> place{rows.length > 1 ? 's' : ''} within {radius} mi with a published {payerName} price</p>
                <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                  <Stat label="Lowest price" v={moneyRound(stats.min)} tone="text-mint-200" />
                  <Stat label="Median" v={moneyRound(stats.median)} />
                  <Stat label="Highest" v={moneyRound(stats.max)} tone="text-sun-300" />
                </div>
                {stats.pMax - stats.pMin >= 5 && (
                  <p className="mt-3 rounded-xl bg-white/10 px-3 py-2 text-sm">💡 Choosing the lowest-cost option could save you <b className="text-mint-200">{moneyRound(stats.pMax - stats.pMin)}</b> compared with the most expensive one nearby.</p>
                )}
                {!personal && (
                  <button onClick={() => setPersonalize(true)} className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl bg-white px-3 py-2 text-sm font-semibold text-brand-800 hover:bg-brand-50">
                    <SlidersHorizontal className="h-4 w-4" /> Showing full price. Add plan details for your real cost
                  </button>
                )}
              </div>
            ) : (
              <Empty radius={radius} hidden={all.hiddenCount} onWiden={() => setParam('r', radius < 50 ? 50 : 100)} onShowHidden={() => setParam('hidden', '1')}
                payerName={payerName} planName={planName} onAnyPlan={() => setParam('prod', null)} />
            )}
            {!loading && all.hiddenCount > 0 && !showHidden && rows.length > 0 && (
              <button onClick={() => setParam('hidden', '1')} className="mb-4 flex w-full items-start gap-2 rounded-xl border border-line bg-white p-3 text-left text-xs leading-relaxed text-ink-soft hover:border-brand-200">
                <EyeOff className="mt-0.5 h-4 w-4 shrink-0 text-ink-mute" />
                <span><b className="text-ink">{all.hiddenCount} more place{all.hiddenCount > 1 ? 's' : ''}</b> only have prices that look wrong (far from what Medicare pays). Tap to show them with a warning.</span>
              </button>
            )}
            {kid && proc.kind === 'imaging' && (
              <p className="mb-4 flex gap-2 rounded-xl border border-pink-100 bg-pink-50 p-3 text-xs leading-relaxed text-pink-900">
                <Baby className="mt-0.5 h-4 w-4 shrink-0" />
                Children’s hospitals are listed first. Their scans are often read by pediatric radiologists who may be listed under a pediatrics group, and use lower radiation doses for kids — ask about this when you book.
              </p>
            )}
            <ul className="space-y-3">
              {rows.map((r, i) => (
                <li data-id={r.id} key={r.id}>
                  <Row r={r} proc={proc} rank={i + 1} median={stats?.median} sort={sort} active={r.id === active || r.id === hover}
                    onClick={() => setActive(r.id)} onHover={(on) => setHover(on ? r.id : null)} />
                </li>
              ))}
            </ul>
            {rows.length > 0 && (
              <p className="mt-6 text-center text-xs text-ink-mute">Estimates only. Confirm with the provider and your insurer. <Link to="/about" className="underline">How we get these prices</Link></p>
            )}
          </div>
        </div>
        <div className={`${view === 'map' ? 'block' : 'hidden'} relative w-full lg:block lg:flex-1`}>
          <Suspense fallback={<div className="flex h-full items-center justify-center bg-canvas text-ink-mute">Loading map…</div>}>
            {origin && <ResultsMap rows={rows} origin={origin} radius={radius} activeId={active} hoverId={hover} onSelect={setActive} onHover={setHover} flyTarget={null} />}
          </Suspense>
          <div className="pointer-events-none absolute bottom-8 left-3 z-[500] rounded-xl bg-white/95 px-3 py-2 text-[10.5px] shadow-card sm:bottom-6 sm:left-4 sm:text-[11px]">
            <div className="mb-1 font-semibold text-ink">Negotiated price</div>
            <div className="flex items-center gap-3 text-ink-soft">
              <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-mint-600" />Lower third</span>
              <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-brand-500" />Middle</span>
              <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-amber-700" />Upper third</span>
            </div>
            <div className="mt-1 text-ink-mute">Pins show your estimated cost</div>
          </div>
        </div>
      </div>

      {sel && <Drawer row={sel} proc={proc} payerName={payerName} planName={planName} median={stats?.median} kid={kid}
        patient={patient} onClose={() => setActive(null)} onPersonalize={() => setPersonalize(true)} />}
      {edit && (
        <Modal title="Edit your search" onClose={() => setEdit(false)}>
          <SearchForm initial={{ payer, prod: prodRaw ?? '', proc: procId, zip, r: String(radius), pt: patient, kid }} onDone={() => setEdit(false)} />
        </Modal>
      )}
      {personalize && (
        <Modal title="Personalize your estimate" onClose={() => setPersonalize(false)}
          footer={<button onClick={() => setPersonalize(false)} className="btn-cta w-full">Update my results</button>}>
          <p className="mb-3 text-sm text-ink-mute">Results update as you type. Leave anything blank that you don’t know.</p>
          <CostProfileForm compact />
        </Modal>
      )}
    </div>
  )
}

const Stat = ({ label, v, tone = 'text-white' }) => (
  <div className="rounded-xl bg-white/5 px-2 py-2">
    <div className="text-[11px] text-brand-100">{label}</div>
    <div className={`font-display text-lg font-extrabold ${tone}`}>{v}</div>
  </div>
)

function Empty({ radius, hidden, onWiden, onShowHidden, payerName, planName, onAnyPlan }) {
  return (
    <div className="card mb-4 p-6 text-center">
      <MapPin className="mx-auto h-8 w-8 text-brand-300" />
      <h2 className="mt-2 text-lg font-bold">No published {payerName} prices within {radius} miles</h2>
      <p className="mt-1 text-sm text-ink-mute">
        That doesn’t mean nobody nearby takes your plan — only that we found no usable price in the insurer’s files.
        {hidden > 0 && ` ${hidden} place${hidden > 1 ? 's have' : ' has'} prices we hid because they look wrong.`}
      </p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        {radius < 100 && <button onClick={onWiden} className="btn-primary">Widen search</button>}
        {planName && <button onClick={onAnyPlan} className="btn-ghost">Try any {payerName} plan</button>}
        {hidden > 0 && <button onClick={onShowHidden} className="btn-ghost"><Eye className="h-4 w-4" /> Show hidden prices</button>}
      </div>
    </div>
  )
}

function Row({ r, rank, median, active, onClick, onHover, sort, proc }) {
  const { place, price, est, distance } = r
  const diff = median && price.total != null && !price.partial ? median - price.total : 0
  return (
    <button onClick={onClick} onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)}
      className={`card group w-full p-4 text-left transition hover:border-brand-300 hover:shadow-pop ${active ? 'border-brand-400 ring-4 ring-brand-100' : ''}`}>
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${rank === 1 && sort !== 'distance' ? 'bg-mint-600 text-white' : 'bg-canvas text-ink-soft'}`}>{rank}</span>
        <div className="min-w-0 flex-1">
          <h3 className="font-sans text-[15px] font-semibold leading-snug text-ink group-hover:text-brand-700">{place.name}</h3>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-mute">
            <span className="flex items-center gap-1"><Building2 className="h-3.5 w-3.5" />{placeKindLabel(place.kind)}</span>
            <span>· {place.city}</span>
            <span>· {distance.toFixed(1)} mi</span>
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge b={price.badge} />
            {place.kids && <span className="chip bg-pink-50 text-pink-700"><Baby className="h-3.5 w-3.5" /> Children’s</span>}
            {price.kind === 'split' && <span className="chip bg-canvas text-ink-soft">2 bills</span>}
            {price.kind === 'flat' && <span className="chip bg-brand-50 text-brand-700">Flat per visit</span>}
            {(price.kind === 'pct' || price.kind === 'pctonly') && <span className="chip bg-slate-100 text-slate-700">Facility fee not published</span>}
            {price.partial && price.kind === 'split' && <span className="chip bg-sun-100 text-amber-800">Reading fee missing</span>}
            {diff >= 25 && <span className="chip bg-mint-50 text-mint-700">{moneyRound(diff)} below median</span>}
            {diff <= -25 && <span className="chip bg-amber-50 text-amber-800">{moneyRound(-diff)} above median</span>}
          </div>
          {price.bills?.[0]?.from && price.bills[0].from.toLowerCase() !== place.n.toLowerCase() && (
            <p className="mt-1.5 truncate text-xs text-ink-mute">Billed through {titleCase(price.bills[0].from)}</p>
          )}
        </div>
        <div className="shrink-0 text-right">
          {est ? (
            <>
              <div className="text-[11px] font-medium text-ink-mute">{price.partial ? (proc.kind === 'imaging' ? 'Reading fee only' : 'Partial') : est.personalized ? 'You pay' : 'Up to'}</div>
              <div className="font-display text-2xl font-extrabold leading-none text-ink">{moneyRound(est.patient)}</div>
              <div className="mt-1 text-[11px] text-ink-mute">{price.partial ? '+ facility fee' : `of ${moneyRound(price.total)}`}</div>
            </>
          ) : (
            <>
              <div className="text-[11px] font-medium text-ink-mute">Price</div>
              <div className="font-display text-lg font-extrabold leading-tight text-ink">Call</div>
              <div className="mt-1 text-[11px] text-ink-mute">% of charges</div>
            </>
          )}
        </div>
      </div>
    </button>
  )
}

function BillCard({ color, Icon, title, tip, allowed, you, from }) {
  return (
    <div className="rounded-2xl border border-line p-4">
      <div className="flex items-center gap-2 text-sm font-semibold"><span className={`h-2.5 w-2.5 rounded-full ${color}`} /><Icon className="h-4 w-4 text-ink-mute" />{title}{tip && <InfoTip k={tip} />}</div>
      <div className="mt-3 flex items-end justify-between">
        <div><div className="text-xs text-ink-mute">Negotiated</div><div className="font-semibold">{money(allowed)}</div></div>
        <div className="text-right"><div className="text-xs text-ink-mute">You pay</div><div className="font-display text-xl font-extrabold text-ink">{money(you)}</div></div>
      </div>
      {from && <div className="mt-2 text-xs text-ink-mute">{from}</div>}
    </div>
  )
}

const BILL_STYLE = {
  complete: ['bg-brand-500', Building2, 'Scan and reading (one bill)', 'negotiated'],
  facility: ['bg-brand-500', Building2, 'Facility fee', 'facility'],
  professional: ['bg-mint-500', Stethoscope, 'Radiologist fee', 'professional'],
  flat: ['bg-brand-500', Building2, 'Flat per-visit amount', 'flat'],
  base: ['bg-brand-500', Stethoscope, null, 'negotiated'],
}

function Drawer({ row, proc, payerName, planName, median, kid, patient, onClose, onPersonalize }) {
  useEffect(() => {
    const esc = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])
  const { place, price, est, distance } = row
  const diff = median && price.total != null && !price.partial ? price.total - median : null
  const code = proc.kind === 'visit' && proc.codes.length > 1 && patient === 'new' ? proc.codes[1] : proc.codes[0]
  const plan = planName ? `${payerName} ${planName}` : `${payerName} plan`
  const billers = [...new Set((price.bills || []).map((b) => b.from).filter(Boolean))]
  const sumAllowed = (price.bills || []).reduce((s, b) => s + b.allowed, 0)
  return (
    <div className="fixed inset-0 z-[2500] flex justify-end bg-ink/40" onClick={onClose} role="dialog" aria-modal="true" aria-label={place.name}>
      <aside className="flex h-full w-full max-w-xl flex-col overflow-hidden bg-white shadow-pop" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <button onClick={onClose} className="flex items-center gap-1 text-sm font-medium text-ink-soft hover:text-ink"><ArrowLeft className="h-4 w-4" /> Back to results</button>
          <button onClick={onClose} className="rounded-full p-2 hover:bg-canvas" aria-label="Close"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto">
          <div className="border-b border-line bg-gradient-to-b from-brand-50 to-white px-5 pb-5 pt-5 sm:px-7">
            <div className="flex flex-wrap gap-1.5">
              <span className="chip bg-white text-brand-700 ring-1 ring-brand-100"><Building2 className="h-3.5 w-3.5" /> {placeKindLabel(place.kind)}</span>
              <Badge b={price.badge} tip />
              {place.kids && <span className="chip bg-pink-50 text-pink-700"><Baby className="h-3.5 w-3.5" /> Children’s</span>}
              {place.er && <span className="chip bg-red-50 text-red-700">Emergency room</span>}
            </div>
            <h2 className="mt-3 text-2xl font-bold leading-tight">{place.name}</h2>
            <p className="mt-1 flex items-center gap-1.5 text-sm text-ink-mute"><MapPin className="h-4 w-4 shrink-0" /> {titleCase(place.a)}, {place.city}, {place.s} {place.z} · {distance.toFixed(1)} mi away</p>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <div className="rounded-2xl bg-ink p-4 text-white">
                <div className="text-xs font-medium text-white/70">{est ? (est.personalized ? 'Your estimated cost' : 'You pay (deductible not met)') : 'Your cost'}</div>
                <div className="mt-1 font-display text-3xl font-extrabold">{est ? moneyRound(est.patient) : 'Ask'}</div>
                {est && !est.personalized && <button onClick={onPersonalize} className="mt-1 text-xs font-semibold text-mint-200 underline underline-offset-2">Personalize →</button>}
              </div>
              <div className="rounded-2xl border border-line bg-white p-4">
                <div className="text-xs font-medium text-ink-mute">Negotiated price<InfoTip k="negotiated" /></div>
                <div className="mt-1 font-display text-3xl font-extrabold text-ink">{price.total != null ? moneyRound(price.total) : '—'}</div>
                {diff != null && <div className={`mt-1 text-xs font-semibold ${diff <= 0 ? 'text-mint-700' : 'text-amber-700'}`}>{Math.abs(diff) < 1 ? 'Same as area median' : `${moneyRound(Math.abs(diff))} ${diff < 0 ? 'below' : 'above'} area median`}</div>}
                {price.lo != null && price.hi != null && price.hi - price.lo >= 1 && <div className="mt-1 text-[11px] text-ink-mute">Contracts here range {moneyRound(price.lo)}–{moneyRound(price.hi)}</div>}
              </div>
            </div>
            {price.badge === 'h' && (
              <p className="mt-4 flex gap-2 rounded-xl bg-red-50 p-3 text-xs leading-relaxed text-red-800">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> This price is far from what Medicare pays for the same service in your state, so it may be a placeholder or a data error. Confirm it with the provider before relying on it.
              </p>
            )}
            {price.badge === 'l' && (
              <p className="mt-4 flex gap-2 rounded-xl bg-sun-100/60 p-3 text-xs leading-relaxed text-amber-900">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> Likely, not confirmed: clinicians here have the right specialty and this contract, but we found no Medicare record of them billing this service. Ask the office whether they do it.
              </p>
            )}
          </div>

          {price.bills?.length > 0 && (
            <section className="px-5 py-6 sm:px-7">
              <h3 className="text-lg font-bold">{price.bills.length > 1 ? 'Expect two bills' : price.kind === 'complete' ? 'One bill covers scan and reading' : 'What you’ll be billed'}</h3>
              <p className="mt-1 text-sm text-ink-mute">
                {price.kind === 'split' && `For your ${proc.short.toLowerCase()} (code ${code}), the cost is split between the facility and the radiologist.`}
                {price.kind === 'complete' && `This place bills the scan and the radiologist’s reading together (code ${code}, “global” price).`}
                {price.kind === 'pct' && `The radiologist’s reading fee is published; the hospital’s facility fee is a percentage of its own charges.`}
                {price.kind === 'flat' && `${payerName} pays this clinic one flat amount per visit instead of a price per code.`}
                {price.kind === 'single' && `Code ${code}${proc.kind === 'visit' && proc.codes.length > 1 ? ` (${patient === 'new' ? 'new' : 'returning'} patient visit)` : ''}.`}
              </p>
              {price.bills.length > 1 && (
                <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-canvas">
                  {price.bills.map((b, i) => <div key={b.key} className={i ? 'bg-mint-500' : 'bg-brand-500'} style={{ width: `${(b.allowed / sumAllowed) * 100}%` }} />)}
                </div>
              )}
              <div className={`mt-4 grid gap-3 ${price.bills.length > 1 ? 'sm:grid-cols-2' : ''}`}>
                {price.bills.map((b, i) => {
                  const [color, Icon, title, tip] = BILL_STYLE[b.key] || BILL_STYLE.base
                  return <BillCard key={b.key} color={color} Icon={Icon} title={title || b.label} tip={tip} allowed={b.allowed}
                    you={est?.bills?.[i]?.patient ?? b.allowed} from={b.from ? `From ${titleCase(b.from)}` : null} />
                })}
              </div>
              {price.notes?.map((n) => <p key={n} className="mt-3 rounded-xl bg-canvas p-3 text-xs leading-relaxed text-ink-soft">{n}</p>)}
              {price.kind === 'flat' && price.base && (
                <p className="mt-3 text-xs text-ink-mute">The same group also lists a per-code price of {moneyRound(price.base.rate)} for code {code}; for this clinic the flat amount is what {payerName} pays.</p>
              )}
            </section>
          )}
          {price.kind === 'pctonly' && (
            <section className="px-5 py-6 sm:px-7">
              <h3 className="text-lg font-bold">No dollar price published</h3>
              {price.notes.map((n) => <p key={n} className="mt-2 text-sm text-ink-soft">{n}</p>)}
            </section>
          )}

          {price.readers?.length > 0 && (
            <section className="border-t border-line px-5 py-6 sm:px-7">
              <h3 className="flex items-center gap-1 text-lg font-bold"><Users className="h-5 w-5 text-mint-600" /> Who reads scans here<InfoTip k="readers" /></h3>
              <p className="mt-1 text-sm text-ink-mute">Radiology groups whose radiologists work at this hospital, with their {payerName} reading fee. Your radiologist bill will come from one of them.</p>
              <table className="mt-3 w-full text-sm">
                <thead><tr className="text-left text-xs text-ink-mute"><th className="pb-2 font-medium">Group</th><th className="pb-2 text-right font-medium">Radiologists</th><th className="pb-2 text-right font-medium">Reading fee</th></tr></thead>
                <tbody>
                  {price.readers.slice(0, 8).map((x) => (
                    <tr className="border-t border-line" key={x.tin}>
                      <td className="py-2 pr-3">{titleCase(x.name)}</td>
                      <td className="py-2 text-right text-ink-soft">{x.nrad}</td>
                      <td className="py-2 text-right font-semibold">{money(x.rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {kid && <p className="mt-3 text-xs text-ink-mute">At children’s hospitals the reading group is often a pediatrics practice (for example a university pediatric group), so it may not look like a radiology group by name.</p>}
            </section>
          )}

          {est && (
            <section className="border-t border-line px-5 py-6 sm:px-7">
              <h3 className="text-lg font-bold">How we calculated this</h3>
              <ol className="mt-3 space-y-2.5">
                {est.steps.map((s, i) => (
                  <li className="flex gap-3 text-sm leading-relaxed text-ink-soft" key={i}>
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-100 text-[11px] font-bold text-brand-700">{i + 1}</span><span>{s}</span>
                  </li>
                ))}
              </ol>
              {!est.personalized && <button onClick={onPersonalize} className="btn-primary mt-4">Add my deductible & coinsurance</button>}
            </section>
          )}

          {billers.length > 0 && (
            <section className="border-t border-line px-5 py-6 sm:px-7">
              <h3 className="text-lg font-bold">Billed through</h3>
              <p className="mt-1 text-sm text-ink-mute">
                The price comes from the contract of the group the clinicians here bill under. That can be a different company from the name on the door
                — for example when doctors at a small clinic bill through a larger practice.
              </p>
              <ul className="mt-3 space-y-2 text-sm">
                {billers.map((b) => <li key={b} className="flex items-center gap-2 rounded-xl bg-canvas px-3 py-2"><Users className="h-4 w-4 text-ink-mute" />{titleCase(b)}</li>)}
              </ul>
            </section>
          )}

          <section className="border-t border-line px-5 py-6 sm:px-7">
            <h3 className="text-lg font-bold">Location details</h3>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <a href={directions(place)} target="_blank" rel="noreferrer" className="btn-primary"><Navigation className="h-4 w-4" /> Directions</a>
              <a href={`https://www.google.com/search?q=${encodeURIComponent(`${place.name} ${place.city} ${place.s}`)}`} target="_blank" rel="noreferrer" className="btn-ghost"><Globe className="h-4 w-4" /> Search the web <ExternalLink className="h-3.5 w-3.5" /></a>
              {place.ph && <a href={`tel:${place.ph}`} className="btn-ghost sm:col-span-2"><Phone className="h-4 w-4" /> {phoneFmt(place.ph)}</a>}
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-xl bg-canvas p-3"><dt className="text-xs text-ink-mute">Plan</dt><dd className="mt-0.5 font-medium">{plan}</dd></div>
              {proc.time && <div className="rounded-xl bg-canvas p-3"><dt className="text-xs text-ink-mute">Typical time</dt><dd className="mt-0.5 flex items-center gap-1 font-medium"><Clock className="h-3.5 w-3.5" /> {proc.time}</dd></div>}
              {price.nq > 0 && <div className="rounded-xl bg-canvas p-3"><dt className="text-xs text-ink-mute">Qualified clinicians on this contract here</dt><dd className="mt-0.5 font-medium">{price.nq}</dd></div>}
              {price.nev > 0 && <div className="rounded-xl bg-canvas p-3"><dt className="text-xs text-ink-mute">Of those, billed this to Medicare</dt><dd className="mt-0.5 font-medium">{price.nev}</dd></div>}
            </dl>
          </section>

          <section className="border-t border-line px-5 py-6 sm:px-7">
            <h3 className="text-lg font-bold">Before you book, ask:</h3>
            <ul className="mt-3 space-y-2.5 text-sm text-ink-soft">
              {[
                `“Do you do code ${code} (${proc.short.toLowerCase()}) here, and are you in-network with my ${plan}?”`,
                billers.length ? `“Will I be billed by ${titleCase(billers[0])}?” If not, ask who will bill you so you can check their price.` : null,
                proc.kind === 'imaging' ? '“Will the radiologist who reads my images also be in-network?” (At an in-network facility, the No Surprises Act protects you from out-of-network balance bills.)' : null,
                '“Can you give me a written cost estimate?” Your insurer’s member portal can also estimate your share.',
                proc.kind === 'imaging' ? 'Ask your doctor’s office if prior authorization is needed — without it, the plan may not pay.' : null,
              ].filter(Boolean).map((t) => <li className="flex gap-2" key={t}><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-mint-600" />{t}</li>)}
            </ul>
            <p className="mt-5 flex gap-2 rounded-xl bg-sun-100/60 p-3 text-xs leading-relaxed text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              Prices are contracted rates {payerName} published for the groups billing at this address. A missing price means none was published, not that the provider is out of network. Hospital outpatient departments can add separate facility charges, and your actual cost depends on your plan and how the claim is processed. Treat this as an estimate.
            </p>
          </section>
        </div>
      </aside>
    </div>
  )
}
