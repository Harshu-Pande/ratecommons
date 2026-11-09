import { useEffect, useState } from 'react'
import { Check, Copy, Lock } from 'lucide-react'

export const PAYER_LABEL = { aetna: 'Aetna', anthem: 'Anthem', bcbs: 'Blue Cross Blue Shield', cigna: 'Cigna', uhc: 'UnitedHealthcare' }
export const PAYER_ORDER = ['aetna', 'anthem', 'bcbs', 'cigna', 'uhc']
export const MCP_URL = 'https://ratecommons.org/mcp'

export function PageHero({ kicker, title, lead, children, tone = 'canvas' }) {
  return (
    <section className={tone === 'night' ? 'bg-night text-white' : 'bg-canvas'}>
      <div className="wrap py-14 sm:py-[72px]">
        {kicker && <p className={`kicker ${tone === 'night' ? '!text-sea' : ''}`}>{kicker}</p>}
        <h1 className={`mt-2.5 max-w-4xl font-display text-[40px] font-bold leading-[1.08] tracking-[-0.02em] sm:text-[52px] ${tone === 'night' ? 'text-white' : 'text-ink'}`}>{title}</h1>
        {lead && <p className={`mt-5 max-w-3xl text-lg leading-relaxed sm:text-xl ${tone === 'night' ? 'text-night-text' : 'text-ink-soft'}`}>{lead}</p>}
        {children}
      </div>
    </section>
  )
}

export function CopyBox({ text, label = 'Copy', mono = true, className = '' }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1800) } catch { /* no clipboard */ }
  }
  return (
    <div className={`flex flex-wrap items-center gap-3 ${className}`}>
      <code className={`min-w-0 max-w-full break-all rounded-[10px] border border-line bg-canvas px-4 py-3 text-[15px] text-ink ${mono ? 'font-mono' : ''}`}>{text}</code>
      <button type="button" onClick={copy} className="btn-line btn-sm" aria-live="polite">
        {done ? <><Check className="h-4 w-4" /> Copied</> : <><Copy className="h-4 w-4" /> {label}</>}
      </button>
    </div>
  )
}

export function CodeBlock({ code, label }) {
  const [done, setDone] = useState(false)
  return (
    <div className="relative">
      <pre className="codeblock pr-24"><code>{code}</code></pre>
      <button type="button" className="btn-line btn-sm absolute right-2 top-2 !min-h-[34px] bg-white"
        onClick={async () => { try { await navigator.clipboard.writeText(code); setDone(true); setTimeout(() => setDone(false), 1800) } catch { /* */ } }}
        aria-label={label ? `Copy ${label}` : 'Copy code'}>
        {done ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}{done ? 'Copied' : 'Copy'}
      </button>
    </div>
  )
}

export function PrivacyNote({ className = '', light = false }) {
  return (
    <p className={`flex items-center gap-2 text-sm ${light ? 'text-white' : 'text-ink-soft'} ${className}`}>
      <Lock className={`h-4 w-4 shrink-0 ${light ? 'text-white' : 'text-brand-600'}`} aria-hidden="true" />
      What you type stays on this device.
    </p>
  )
}

let statusPromise = null
export function fetchStatus() {
  // GET /api/status is cacheable by the CDN; the POST tool call is the fallback for an older API server
  const post = () => fetch('/api/tool/data_status', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' })
  statusPromise ||= fetch('/api/status').then((r) => (r.ok ? r : post()))
    .then((r) => r.json()).then((d) => (d && d.ok ? d : null)).catch(() => null)
  return statusPromise
}

export function useDataStatus() {
  const [st, setSt] = useState(undefined)
  useEffect(() => { let live = true; fetchStatus().then((d) => live && setSt(d)); return () => { live = false } }, [])
  return st
}

export function statusSummary(st) {
  if (!st?.payers) return null
  const ps = Object.entries(st.payers)
  const networks = ps.reduce((s, [, v]) => s + (v.networks || 0), 0)
  const latest = ps.map(([, v]) => v.built).filter(Boolean).sort().at(-1)
  const month = latest ? new Date(latest).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' }) : null
  return { insurers: ps.length, networks, latest, month }
}

export async function callTool(name, args, { signal } = {}) {
  const r = await fetch(`/api/tool/${name}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(args || {}), signal })
  let d
  try { d = await r.json() } catch { throw new Error(`The server answered ${r.status}. Please try again.`) }
  if (!d.ok) throw new Error(d.error || 'The query failed.')
  return d
}

export function usePageTitle(title) {
  useEffect(() => { document.title = title ? `${title} | RateCommons` : 'RateCommons: what health insurers actually pay' }, [title])
}
