import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Baby, ChevronDown, MapPin, SlidersHorizontal } from 'lucide-react'
import ProcedurePicker from './ProcedurePicker'
import CostProfileForm from './CostProfileForm'
import InfoTip from './InfoTip'
import { useProfile } from '../lib/store'
import { PROC_BY_ID, loadProducts, zipToPoint } from '../lib/data'
import { PAYER_NAMES } from '../lib/format'

export const PAYERS = ['aetna', 'cigna', 'uhc']

export function searchUrl(s) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(s)) if (v !== '' && v != null && v !== false) q.set(k, v === true ? '1' : v)
  return `/results?${q}`
}

export function usePlans(payer) {
  const [all, setAll] = useState(null)
  useEffect(() => { loadProducts().then((p) => setAll(p || {})) }, [])
  return all ? (all[payer] || []) : null
}

export default function SearchForm({ initial = {}, onDone }) {
  const nav = useNavigate()
  const { profile } = useProfile()
  const [payer, setPayer] = useState(initial.payer || 'aetna')
  const [prod, setProd] = useState(initial.prod ?? '')
  const [proc, setProc] = useState(initial.proc || '')
  const [zip, setZip] = useState(initial.zip || '')
  const [r, setR] = useState(initial.r || '25')
  const [pt, setPt] = useState(initial.pt || 'returning')
  const [kid, setKid] = useState(!!initial.kid)
  const [open, setOpen] = useState(!!profile.personalized)
  const [err, setErr] = useState({})
  const [busy, setBusy] = useState(false)
  const plans = usePlans(payer)
  const p = PROC_BY_ID[proc]
  const twoVisitTypes = p && p.kind === 'visit' && p.codes.length > 1
  useEffect(() => { if (initial.payer !== payer) setProd('') }, [payer]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e) => {
    e.preventDefault()
    const x = {}
    if (!proc) x.proc = 'Choose the care you need.'
    if (!/^\d{5}$/.test(zip)) x.zip = 'Enter a 5-digit ZIP code.'
    else {
      setBusy(true)
      const pt0 = await zipToPoint(zip)
      setBusy(false)
      if (!pt0) x.zip = 'We don’t recognize that ZIP code.'
    }
    setErr(x)
    if (Object.keys(x).length) return
    nav(searchUrl({ payer, prod, proc, zip, r, pt: twoVisitTypes ? pt : '', kid }))
    onDone?.()
  }

  return (
    <form onSubmit={submit} className="card p-5 sm:p-6" noValidate>
      <div className="grid gap-4 md:grid-cols-12">
        <label className="block md:col-span-3" htmlFor="payer">
          <span className="text-sm font-medium text-ink">Insurance company</span>
          <select id="payer" value={payer} onChange={(e) => setPayer(e.target.value)} className="field mt-1.5 w-full">
            {PAYERS.map((k) => <option value={k} key={k}>{PAYER_NAMES[k]}</option>)}
          </select>
        </label>
        <label className="block md:col-span-4" htmlFor="prod">
          <span className="text-sm font-medium text-ink">Plan or network<InfoTip k="network" /></span>
          <select id="prod" value={prod} onChange={(e) => setProd(e.target.value)} className="field mt-1.5 w-full" disabled={!plans}>
            <option value="">Not sure / any {PAYER_NAMES[payer]} plan</option>
            {(plans || []).map((n, i) => <option value={i} key={n}>{n}</option>)}
          </select>
        </label>
        <div className="md:col-span-5">
          <label htmlFor="proc" className="text-sm font-medium text-ink">Care you need<InfoTip k="cpt" /></label>
          <div className="mt-1.5"><ProcedurePicker id="proc" value={proc} onChange={setProc} /></div>
          {err.proc && <p className="mt-1 text-xs font-medium text-red-600">{err.proc}</p>}
        </div>
        <label className="block md:col-span-3" htmlFor="zip">
          <span className="text-sm font-medium text-ink">Your ZIP code</span>
          <div className="relative mt-1.5">
            <MapPin className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-mute" />
            <input id="zip" inputMode="numeric" autoComplete="postal-code" maxLength={5} value={zip}
              onChange={(e) => setZip(e.target.value.replace(/\D/g, ''))} placeholder="e.g. 38103" className="field w-full pl-9" />
          </div>
          {err.zip && <p className="mt-1 text-xs font-medium text-red-600">{err.zip}</p>}
        </label>
        <label className="block md:col-span-2" htmlFor="radius">
          <span className="text-sm font-medium text-ink">Distance</span>
          <select id="radius" value={r} onChange={(e) => setR(e.target.value)} className="field mt-1.5 w-full">
            {['5', '10', '25', '50', '100'].map((v) => <option value={v} key={v}>Within {v} mi</option>)}
          </select>
        </label>
        <div className="flex flex-col justify-end gap-2 md:col-span-3">
          {twoVisitTypes ? (
            <div className="inline-flex rounded-xl bg-canvas p-1" role="radiogroup" aria-label="Patient type">
              {[['returning', 'Returning patient'], ['new', 'New patient']].map(([k, l]) => (
                <button type="button" key={k} role="radio" aria-checked={pt === k} onClick={() => setPt(k)}
                  className={`flex-1 rounded-lg px-2 py-2 text-xs font-semibold transition ${pt === k ? 'bg-white text-brand-700 shadow-card' : 'text-ink-mute'}`}>{l}</button>
              ))}
            </div>
          ) : (
            <label className="flex h-12 cursor-pointer items-center gap-2 rounded-xl border border-line bg-white px-3 text-sm">
              <input type="checkbox" checked={kid} onChange={(e) => setKid(e.target.checked)} className="h-4 w-4 accent-brand-600" />
              <Baby className="h-4 w-4 text-brand-600" /> This is for a child
            </label>
          )}
        </div>
        <div className="flex items-end md:col-span-4">
          <button type="submit" className="btn-cta w-full" disabled={busy}>Compare prices <ArrowRight className="h-5 w-5" /></button>
        </div>
      </div>
      <div className="mt-5 rounded-2xl border border-line bg-canvas/60">
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left">
          <span className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white text-brand-600 shadow-sm"><SlidersHorizontal className="h-4 w-4" /></span>
            <span>
              <span className="block text-sm font-semibold text-ink">Personalize my out-of-pocket estimate <span className="font-normal text-ink-mute">(optional)</span></span>
              <span className="block text-xs text-ink-mute">Add your deductible, coinsurance & what you’ve spent — or scan your insurance card.</span>
            </span>
          </span>
          <ChevronDown className={`h-5 w-5 text-ink-mute transition ${open ? 'rotate-180' : ''}`} />
        </button>
        {open && <div className="border-t border-line bg-white px-4 pb-4 pt-1 sm:px-5 sm:pb-5"><CostProfileForm /></div>}
      </div>
    </form>
  )
}
