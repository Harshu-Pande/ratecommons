import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'
import { PROCS, PROC_BY_ID } from '../lib/data'

const TAG = {
  MRI: 'bg-brand-100 text-brand-700', CT: 'bg-sun-100 text-amber-800', Ultrasound: 'bg-mint-100 text-mint-700',
  'X-ray': 'bg-slate-100 text-slate-700', Mammogram: 'bg-pink-100 text-pink-700', PET: 'bg-violet-100 text-violet-700',
  Visits: 'bg-brand-50 text-brand-700', 'Mental health': 'bg-violet-50 text-violet-700', Lab: 'bg-rose-50 text-rose-700',
  Therapy: 'bg-mint-50 text-mint-700', Heart: 'bg-red-50 text-red-700', Procedures: 'bg-amber-50 text-amber-800',
  Other: 'bg-slate-100 text-slate-700',
}
export const Tag = ({ p }) => {
  const t = p.modality || p.cat
  return <span className={`rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${TAG[t] || 'bg-slate-100'}`}>{t}</span>
}

export default function ProcedurePicker({ value, onChange, id }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [hi, setHi] = useState(0)
  const box = useRef(null)
  const input = useRef(null)
  const cur = PROC_BY_ID[value]
  const list = useMemo(() => {
    const t = q.trim().toLowerCase()
    if (!t) return PROCS
    const words = t.split(/\s+/)
    return PROCS.filter((p) => {
      const hay = `${p.name} ${p.short} ${p.codes.join(' ')} ${p.keywords} ${p.modality || ''} ${p.cat}`.toLowerCase()
      return words.every((w) => hay.includes(w))
    })
  }, [q])
  useEffect(() => {
    const out = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    document.addEventListener('pointerdown', out)
    return () => document.removeEventListener('pointerdown', out)
  }, [])
  useEffect(() => { if (open) { setQ(''); setHi(0); setTimeout(() => input.current?.focus(), 0) } }, [open])
  const choose = (p) => { onChange(p.id); setOpen(false) }
  let lastCat = null
  return (
    <div className="relative" ref={box}>
      <button type="button" id={id} onClick={() => setOpen((v) => !v)} aria-haspopup="listbox" aria-expanded={open}
        className="field flex w-full items-center justify-between gap-2 text-left">
        {cur ? (
          <span className="min-w-0">
            <span className="block truncate font-medium text-ink">{cur.name}</span>
            <span className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-mute"><Tag p={cur} /> Code {cur.codes[0]}</span>
          </span>
        ) : <span className="text-ink-mute">Search scans, visits, labs, therapy…</span>}
        <ChevronDown className="h-5 w-5 shrink-0 text-ink-mute" />
      </button>
      {open && (
        <div className="absolute left-0 right-0 z-[1100] mt-2 overflow-hidden rounded-2xl border border-line bg-white shadow-pop">
          <div className="flex items-center gap-2 border-b border-line px-3">
            <Search className="h-4 w-4 text-ink-mute" />
            <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setHi(0) }}
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown') { e.preventDefault(); setHi((i) => Math.min(i + 1, list.length - 1)) }
                else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((i) => Math.max(i - 1, 0)) }
                else if (e.key === 'Enter') { e.preventDefault(); if (list[hi]) choose(list[hi]) }
                else if (e.key === 'Escape') setOpen(false)
              }}
              placeholder="Type a test, body part, visit or code (e.g. knee MRI, urgent care, 70450)"
              className="h-12 w-full bg-transparent text-sm outline-none" aria-label="Search procedures" />
          </div>
          <ul role="listbox" className="max-h-96 overflow-auto py-1">
            {list.length === 0 && <li className="px-4 py-6 text-center text-sm text-ink-mute">No match. Try “MRI”, “visit”, “therapy” or a code.</li>}
            {list.map((p, i) => {
              const head = p.cat !== lastCat && !q ? p.cat : null
              lastCat = p.cat
              return [
                head && <li key={`h-${head}`} className="px-4 pb-1 pt-3 text-[11px] font-bold uppercase tracking-wider text-ink-mute">{head}</li>,
                <li key={p.id} role="option" aria-selected={p.id === value} onMouseEnter={() => setHi(i)} onClick={() => choose(p)}
                  className={`flex cursor-pointer items-start gap-3 px-4 py-2.5 ${i === hi ? 'bg-brand-50' : ''}`}>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-ink">{p.name}</div>
                    <div className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-mute"><Tag p={p} /> Code {p.codes[0]}</div>
                  </div>
                  {p.id === value && <Check className="mt-1 h-4 w-4 text-brand-600" />}
                </li>,
              ]
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
