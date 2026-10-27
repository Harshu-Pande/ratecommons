import { useEffect, useId, useRef, useState } from 'react'
import { GLOSSARY } from '../data/glossary'

export default function InfoTip({ k, text, term, className = '' }) {
  const item = k ? GLOSSARY[k] : { term, text }
  const [open, setOpen] = useState(false)
  const [side, setSide] = useState('center')
  const id = useId()
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const out = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const esc = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', out)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('pointerdown', out); document.removeEventListener('keydown', esc) }
  }, [open])
  useEffect(() => {
    if (!open || !ref.current) return
    const r = ref.current.getBoundingClientRect()
    setSide(r.left < 150 ? 'left' : window.innerWidth - r.right < 150 ? 'right' : 'center')
  }, [open])
  if (!item) return null
  const pos = side === 'left' ? 'left-0' : side === 'right' ? 'right-0' : 'left-1/2 -translate-x-1/2'
  return (
    <span ref={ref} className={`relative inline-block align-super ${className}`} onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}>
      <button type="button" aria-label={`What is ${item.term}?`} aria-describedby={open ? id : undefined}
        onClick={(e) => { e.preventDefault(); setOpen((v) => !v) }} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        className="ml-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-brand-100 text-[10px] font-bold leading-none text-brand-700 transition hover:bg-brand-600 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400">
        ?
      </button>
      {open && (
        <span role="tooltip" id={id}
          className={`absolute ${pos} top-6 z-[1200] w-72 max-w-[82vw] rounded-xl border border-line bg-white p-3 text-left text-[13px] font-normal normal-case leading-snug tracking-normal text-ink-soft shadow-pop`}>
          <span className="mb-1 block text-[13px] font-semibold text-ink">{item.term}</span>
          {item.text}
        </span>
      )}
    </span>
  )
}
