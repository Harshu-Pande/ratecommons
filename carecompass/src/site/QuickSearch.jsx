import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import ProcedurePicker from '../components/ProcedurePicker'
import { PAYERS, searchUrl } from '../components/SearchForm'
import { zipToPoint } from '../lib/data'
import { PAYER_NAMES } from '../lib/format'

/** The one-card patient search: care, ZIP, insurer, one button. */
export default function QuickSearch({ idPrefix = 'qs' }) {
  const nav = useNavigate()
  const [proc, setProc] = useState('')
  const [zip, setZip] = useState('')
  const [payer, setPayer] = useState('uhc')
  const [err, setErr] = useState({})
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    const x = {}
    if (!proc) x.proc = 'Choose the care you need.'
    if (!/^\d{5}$/.test(zip)) x.zip = 'Enter a 5-digit ZIP code.'
    else {
      setBusy(true)
      const pt = await zipToPoint(zip)
      setBusy(false)
      if (!pt) x.zip = 'We don’t recognize that ZIP code.'
    }
    setErr(x)
    if (!Object.keys(x).length) nav(searchUrl({ payer, proc, zip, r: '25' }))
  }
  return (
    <form onSubmit={submit} noValidate className="grid gap-3 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <label htmlFor={`${idPrefix}-proc`} className="mb-1.5 block text-[13px] font-semibold text-[#2e3e4c]">What care do you need?</label>
        <ProcedurePicker id={`${idPrefix}-proc`} value={proc} onChange={setProc} />
        {err.proc && <p className="mt-1 text-sm font-medium text-clay-600">{err.proc}</p>}
      </div>
      <label className="block" htmlFor={`${idPrefix}-zip`}>
        <span className="mb-1.5 block text-[13px] font-semibold text-[#2e3e4c]">ZIP code</span>
        <input id={`${idPrefix}-zip`} inputMode="numeric" autoComplete="postal-code" maxLength={5} value={zip}
          onChange={(e) => setZip(e.target.value.replace(/\D/g, ''))} placeholder="e.g. 63110" className="field w-full" />
        {err.zip && <p className="mt-1 text-sm font-medium text-clay-600">{err.zip}</p>}
      </label>
      <label className="block" htmlFor={`${idPrefix}-payer`}>
        <span className="mb-1.5 block text-[13px] font-semibold text-[#2e3e4c]">Insurance</span>
        <select id={`${idPrefix}-payer`} value={payer} onChange={(e) => setPayer(e.target.value)} className="field w-full">
          {PAYERS.map((k) => <option value={k} key={k}>{PAYER_NAMES[k]}</option>)}
        </select>
      </label>
      <button type="submit" disabled={busy} className="btn-go sm:col-span-2">Compare prices <ArrowRight className="h-5 w-5" /></button>
    </form>
  )
}
