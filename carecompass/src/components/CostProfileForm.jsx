import { useRef, useState } from 'react'
import { Camera, FileText, Keyboard, Loader2, Receipt, ShieldCheck, Trash2, Upload, X } from 'lucide-react'
import InfoTip from './InfoTip'
import CardIllustration, { CARD_STEPS } from './CardIllustration'
import { useProfile } from '../lib/store'
import { readImage, parseCard, parseBill } from '../lib/ocr'
import { money } from '../lib/format'

function NumField({ label, tip, prefix, suffix, value, onChange, placeholder, id, hint }) {
  return (
    <label className="block" htmlFor={id}>
      <span className="text-sm font-medium text-ink">{label}{tip && <InfoTip k={tip} />}</span>
      <div className="relative mt-1.5">
        {prefix && <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-mute">{prefix}</span>}
        <input id={id} inputMode="decimal" value={value ?? ''} placeholder={placeholder}
          onChange={(e) => onChange(e.target.value.replace(/[^\d.]/g, ''))}
          className={`field w-full ${prefix ? 'pl-7' : ''} ${suffix ? 'pr-8' : ''}`} />
        {suffix && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-ink-mute">{suffix}</span>}
      </div>
      {hint && <span className="mt-1 block text-xs text-ink-mute">{hint}</span>}
    </label>
  )
}

function WhereToFind({ onClose }) {
  return (
    <div className="fixed inset-0 z-[3000] flex items-end justify-center bg-ink/50 p-0 sm:items-center sm:p-6" onClick={onClose}
      role="dialog" aria-modal="true" aria-label="Where to find your numbers">
      <div className="max-h-[92vh] w-full max-w-4xl overflow-auto rounded-t-3xl bg-white p-5 shadow-pop sm:rounded-3xl sm:p-8" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-2xl font-bold">Where to find these numbers</h2>
            <p className="mt-1 text-sm text-ink-mute">Every insurer’s card looks different. Here’s where the numbers usually are, on a made-up example card.</p>
          </div>
          <button onClick={onClose} className="rounded-full p-2 hover:bg-canvas" aria-label="Close"><X className="h-5 w-5" /></button>
        </div>
        <div className="mt-6 grid gap-6 md:grid-cols-[1.25fr_1fr]">
          <CardIllustration className="w-full" />
          <ol className="space-y-3">
            {CARD_STEPS.map((s) => (
              <li className="flex gap-3" key={s.n}>
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sun-500 text-xs font-extrabold text-white">{s.n}</span>
                <span className="text-sm"><b className="text-ink">{s.title}.</b> <span className="text-ink-soft">{s.text}</span></span>
              </li>
            ))}
          </ol>
        </div>
        <div className="mt-6 rounded-2xl bg-brand-50 p-4 text-sm text-brand-800">
          <b>Tip:</b> Many cards don’t print the deductible or what you’ve already spent. Your insurer’s app or website
          (e.g., “Benefits” or “Claims” tab) and your most recent Explanation of Benefits show both.
        </div>
      </div>
    </div>
  )
}

const Found = ({ k, v }) => (
  <div><dt className="text-xs text-ink-mute">{k}</dt><dd className={`font-semibold ${v ? 'text-ink' : 'text-ink-mute'}`}>{v || 'not found'}</dd></div>
)

function CardScan({ onApplied }) {
  const { update } = useProfile()
  const [st, setSt] = useState({ status: 'idle', progress: 0 })
  const [img, setImg] = useState(null)
  const input = useRef(null)
  const go = async (f) => {
    if (!f) return
    setImg(URL.createObjectURL(f))
    setSt({ status: 'reading', progress: 0 })
    try {
      const text = await readImage(f, (p) => setSt((s) => ({ ...s, progress: p })))
      setSt({ status: 'done', parsed: parseCard(text), text })
    } catch (e) {
      console.error(e)
      setSt({ status: 'error' })
    }
  }
  const p = st.parsed
  return (
    <div className="mt-5 rounded-2xl border-2 border-dashed border-brand-200 bg-brand-50/40 p-5">
      <div className="flex flex-col items-center gap-4 sm:flex-row">
        {img ? <img src={img} alt="Your insurance card" className="h-28 w-44 rounded-xl object-cover shadow-card" />
          : <div className="flex h-28 w-44 items-center justify-center rounded-xl bg-white shadow-card"><FileText className="h-10 w-10 text-brand-300" /></div>}
        <div className="flex-1 text-center sm:text-left">
          <p className="font-medium text-ink">Snap or upload the front of your card</p>
          <p className="mt-1 text-sm text-ink-mute">We look only for deductible, coinsurance, copays and out-of-pocket max. Names and member IDs are ignored.</p>
          <div className="mt-3 flex flex-wrap justify-center gap-2 sm:justify-start">
            <button type="button" onClick={() => input.current?.click()} className="btn-primary"><Camera className="h-4 w-4" /> Take / choose photo</button>
            <input ref={input} type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => go(e.target.files?.[0])} />
          </div>
        </div>
      </div>
      {st.status === 'reading' && (
        <div className="mt-4">
          <div className="flex items-center gap-2 text-sm text-ink-soft"><Loader2 className="h-4 w-4 animate-spin" /> Reading your card on this device… {Math.round((st.progress || 0) * 100)}%</div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white"><div className="h-full bg-brand-500 transition-all" style={{ width: `${Math.round((st.progress || 0) * 100)}%` }} /></div>
          <p className="mt-2 text-xs text-ink-mute">First scan downloads the text-recognition engine (~5 MB).</p>
        </div>
      )}
      {st.status === 'error' && <p className="mt-4 text-sm text-red-700">Sorry — we couldn’t read that image. Try a brighter, flatter photo, or enter the numbers manually.</p>}
      {st.status === 'done' && (
        <div className="mt-4 rounded-xl bg-white p-4 shadow-card">
          {p.found ? (
            <>
              <p className="text-sm font-semibold text-ink">Here’s what we found — please double-check:</p>
              <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                <Found k="Deductible" v={p.deductible == null ? null : money(p.deductible)} />
                <Found k="Coinsurance" v={p.coinsurance == null ? null : `${p.coinsurance}%`} />
                <Found k="Out-of-pocket max" v={p.oopMax == null ? null : money(p.oopMax)} />
                {Object.entries(p.copays || {}).map(([k, v]) => <Found k={`${k} copay`} v={money(v)} key={k} />)}
              </dl>
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" className="btn-primary" onClick={() => {
                  const u = { personalized: true }
                  if (p.deductible != null) u.deductible = String(p.deductible)
                  if (p.oopMax != null) u.oopMax = String(p.oopMax)
                  if (p.coinsurance != null) u.coinsurance = String(p.coinsurance)
                  if (p.copay != null) { u.copay = String(p.copay); u.copayMode = 'instead' }
                  update(u); onApplied?.()
                }}>Use these numbers</button>
                <button type="button" className="btn-ghost" onClick={() => input.current?.click()}>Try another photo</button>
              </div>
              {!p.deductible && <p className="mt-3 text-xs text-ink-mute">Your card didn’t show a deductible — that’s common. Check your insurer’s app and enter it manually below.</p>}
            </>
          ) : (
            <p className="text-sm text-ink-soft">We couldn’t find cost-sharing numbers on this card (many cards only show copays or none at all). Please enter them manually — tap “Where do I find these numbers?” for help.</p>
          )}
        </div>
      )}
    </div>
  )
}

function BillsReader() {
  const { profile, update } = useProfile()
  const [rows, setRows] = useState([])
  const [open, setOpen] = useState(false)
  const input = useRef(null)
  const add = async (files) => {
    for (const f of Array.from(files || [])) {
      const id = Math.random().toString(36).slice(2)
      setRows((r) => [...r, { id, name: f.name, status: 'reading', owed: '', ded: '' }])
      try {
        const b = parseBill(await readImage(f))
        setRows((r) => r.map((x) => x.id === id ? { ...x, status: 'done', owed: b.owed ?? '', ded: b.toDeductible ?? b.owed ?? '' } : x))
      } catch {
        setRows((r) => r.map((x) => x.id === id ? { ...x, status: 'error' } : x))
      }
    }
  }
  const owed = rows.reduce((s, r) => s + (parseFloat(r.owed) || 0), 0)
  const ded = rows.reduce((s, r) => s + (parseFloat(r.ded) || 0), 0)
  return (
    <div className="mt-5 rounded-2xl border border-line bg-white">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left">
        <span className="flex items-center gap-2 text-sm font-medium text-ink"><Receipt className="h-4 w-4 text-brand-600" /> Don’t know what you’ve spent? Add photos of this year’s medical bills or EOBs</span>
        <span className="text-xs font-semibold text-brand-600">{open ? 'Hide' : 'Add bills'}</span>
      </button>
      {open && (
        <div className="border-t border-line p-4">
          <button type="button" onClick={() => input.current?.click()} className="btn-ghost"><Upload className="h-4 w-4" /> Upload bill / EOB photos</button>
          <input ref={input} type="file" accept="image/*" multiple className="hidden" onChange={(e) => add(e.target.files)} />
          <p className="mt-2 text-xs text-ink-mute">We look for lines like “Amount you owe”, “Patient responsibility”, and “Applied to deductible”. Edit anything we get wrong.</p>
          {rows.length > 0 && (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[420px] text-sm">
                <thead><tr className="text-left text-xs text-ink-mute"><th className="pb-2 font-medium">Bill</th><th className="pb-2 font-medium">You owed</th><th className="pb-2 font-medium">Went to deductible</th><th /></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr className="border-t border-line" key={r.id}>
                      <td className="max-w-[160px] truncate py-2 pr-2 text-ink-soft">
                        {r.status === 'reading' ? <span className="flex items-center gap-1"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Reading…</span> : r.name}
                      </td>
                      {['owed', 'ded'].map((k) => (
                        <td className="py-2 pr-2" key={k}>
                          <input value={r[k]} inputMode="decimal" aria-label={k === 'owed' ? 'You owed' : 'Applied to deductible'}
                            onChange={(e) => setRows((xs) => xs.map((x) => x.id === r.id ? { ...x, [k]: e.target.value.replace(/[^\d.]/g, '') } : x))}
                            className="field h-9 w-28 py-1 text-sm" placeholder="$" />
                        </td>
                      ))}
                      <td><button type="button" aria-label="Remove bill" onClick={() => setRows((xs) => xs.filter((x) => x.id !== r.id))} className="rounded p-1 text-ink-mute hover:text-red-600"><Trash2 className="h-4 w-4" /></button></td>
                    </tr>
                  ))}
                </tbody>
                <tfoot><tr className="border-t border-line font-semibold"><td className="py-2">Total</td><td>{money(owed)}</td><td>{money(ded)}</td><td /></tr></tfoot>
              </table>
              <button type="button" className="btn-primary mt-3" onClick={() => {
                const cap = parseFloat(profile.deductible) || Infinity
                update({ personalized: true, oopSpent: String(+owed.toFixed(2)), deductibleMet: String(+Math.min(ded, cap).toFixed(2)) })
                setOpen(false)
              }}>Use these totals</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function CostProfileForm({ compact = false }) {
  const { profile, update, reset } = useProfile()
  const [tab, setTab] = useState('manual')
  const [help, setHelp] = useState(false)
  const set = (k) => (v) => update({ [k]: v, personalized: true })
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-xl bg-canvas p-1" role="tablist">
          {[['manual', 'Enter manually', Keyboard], ['card', 'Scan insurance card', Camera]].map(([k, label, Icon]) => (
            <button type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)} key={k}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition ${tab === k ? 'bg-white text-brand-700 shadow-card' : 'text-ink-mute hover:text-ink'}`}>
              <Icon className="h-4 w-4" />{label}
            </button>
          ))}
        </div>
        <button type="button" onClick={() => setHelp(true)} className="text-sm font-medium text-brand-600 underline decoration-brand-200 underline-offset-4 hover:text-brand-800">Where do I find these numbers?</button>
      </div>
      {tab === 'card' && <CardScan onApplied={() => setTab('manual')} />}
      <div className={`mt-5 grid gap-4 ${compact ? 'sm:grid-cols-2' : 'sm:grid-cols-2 lg:grid-cols-3'}`}>
        <NumField id="ded" label="Annual deductible" tip="deductible" prefix="$" placeholder="e.g. 2000" value={profile.deductible} onChange={set('deductible')} />
        <NumField id="dedmet" label="Deductible met so far" tip="deductibleMet" prefix="$" placeholder="e.g. 350" value={profile.deductibleMet} onChange={set('deductibleMet')} />
        <NumField id="coins" label="Coinsurance (your share)" tip="coinsurance" suffix="%" placeholder="e.g. 20" value={profile.coinsurance} onChange={set('coinsurance')} />
        <NumField id="oop" label="Out-of-pocket maximum" tip="oopMax" prefix="$" placeholder="e.g. 6000" value={profile.oopMax} onChange={set('oopMax')} />
        <NumField id="oopspent" label="Spent so far this year" tip="oopSpent" prefix="$" placeholder="e.g. 350" value={profile.oopSpent} onChange={set('oopSpent')}
          hint="Include deductible, copays and coinsurance you’ve paid." />
        <div>
          <span className="text-sm font-medium text-ink">Copay for this care<InfoTip k="copay" /></span>
          <div className="mt-1.5 flex gap-2">
            <div className="relative w-28 shrink-0">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-mute">$</span>
              <input inputMode="decimal" aria-label="Copay amount" value={profile.copay ?? ''} placeholder="0"
                onChange={(e) => update({ copay: e.target.value.replace(/[^\d.]/g, ''), personalized: true,
                  copayMode: profile.copayMode === 'none' && e.target.value ? 'instead' : profile.copayMode })}
                className="field w-full pl-7" />
            </div>
            <select aria-label="How the copay works" value={profile.copayMode} onChange={(e) => update({ copayMode: e.target.value, personalized: true })} className="field w-full min-w-0 text-sm">
              <option value="none">No copay</option>
              <option value="instead">Flat copay (no deductible)</option>
              <option value="after">Copay after deductible</option>
            </select>
          </div>
          <span className="mt-1 block text-xs text-ink-mute">Office visits often have a flat copay; scans usually don’t.<InfoTip k="copayMode" /></span>
        </div>
      </div>
      <BillsReader />
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-ink-mute">
        <span className="flex items-center gap-1.5"><ShieldCheck className="h-4 w-4 text-mint-600" /> Stays on this device. Photos are read in your browser and never uploaded.</span>
        <button type="button" onClick={reset} className="font-medium text-ink-mute underline underline-offset-2 hover:text-ink">Clear my details</button>
      </div>
      {help && <WhereToFind onClose={() => setHelp(false)} />}
    </div>
  )
}
