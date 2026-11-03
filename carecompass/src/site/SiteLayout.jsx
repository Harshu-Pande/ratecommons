import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { ChevronDown, Menu, X } from 'lucide-react'
import { Wordmark } from '../components/Logo'

export const GITHUB = 'https://github.com/Harshu-Pande/ratecommons'
export const HF = 'https://huggingface.co/ratecommons'
export const CONTACT = 'https://github.com/Harshu-Pande/ratecommons/issues/new/choose'

const AUDIENCES = [
  { to: '/care', label: 'Patients and caregivers', sub: 'Check a price before you book' },
  { to: '/for/providers', label: 'Practices and hospitals', sub: 'Benchmark your contracted rates' },
  { to: '/for/employers', label: 'Employers and benefits teams', sub: 'Compare networks for your people' },
  { to: '/for/researchers', label: 'Researchers and journalists', sub: 'Download, query and cite' },
  { to: '/for/developers', label: 'Developers', sub: 'API, SQL and the AI connector' },
]

const NAV = [
  { to: '/care', label: 'Check a price' },
  { to: '/explore', label: 'Explore the data' },
  { to: '/ai', label: 'Use with your AI' },
  { to: '/data', label: 'Download' },
]

const linkCls = ({ isActive }) =>
  `rounded-lg px-2.5 py-2 text-[15px] font-medium transition ${isActive ? 'text-brand-700' : 'text-[#22313f] hover:text-brand-700'}`

function WhoMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  useEffect(() => {
    if (!open) return undefined
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="true"
        className="flex items-center gap-1 rounded-lg px-2.5 py-2 text-[15px] font-medium text-[#22313f] hover:text-brand-700">
        Who it's for <ChevronDown className={`h-4 w-4 transition ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 rounded-2xl border border-line bg-white p-2 shadow-pop">
          {AUDIENCES.map((a) => (
            <Link key={a.to} to={a.to} className="block rounded-xl px-3.5 py-3 hover:bg-canvas">
              <span className="block text-[15px] font-semibold text-ink">{a.label}</span>
              <span className="block text-sm text-ink-mute">{a.sub}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

export function SiteHeader() {
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  return (
    <header className="sticky top-0 z-[1000] border-b border-[#e3e9e6] bg-white">
      <div className="wrap flex h-16 items-center justify-between gap-4">
        <Link to="/" aria-label="RateCommons home"><Wordmark /></Link>
        <nav className="hidden items-center gap-1 lg:flex" aria-label="Main">
          {NAV.map((n) => <NavLink key={n.to} to={n.to} className={linkCls}>{n.label}</NavLink>)}
          <WhoMenu />
          <NavLink to="/about" className={linkCls}>About</NavLink>
        </nav>
        <button className="rounded-lg p-2 text-ink-soft hover:bg-canvas lg:hidden" onClick={() => setOpen((v) => !v)}
          aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open}>
          {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
        </button>
      </div>
      {open && (
        <nav className="max-h-[calc(100dvh-4rem)] overflow-y-auto border-t border-line bg-white px-4 pb-6 pt-2 lg:hidden" aria-label="Mobile">
          {[...NAV, { to: '/about', label: 'About' }].map((n) => (
            <NavLink key={n.to} to={n.to} className="block rounded-lg px-3 py-3 text-base font-semibold text-ink">{n.label}</NavLink>
          ))}
          <p className="mt-3 px-3 text-xs font-bold uppercase tracking-[0.06em] text-ink-mute">Who it's for</p>
          {AUDIENCES.map((a) => (
            <Link key={a.to} to={a.to} className="block rounded-lg px-3 py-2.5 text-[15px] text-ink-soft">{a.label}</Link>
          ))}
        </nav>
      )}
    </header>
  )
}

export function SiteFooter() {
  const col = 'grid content-start gap-2.5 text-[15px]'
  const a = 'text-night-text hover:text-white'
  return (
    <footer className="bg-night text-night-text">
      <div className="wrap py-14">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-[1.6fr_1fr_1fr_1fr]">
          <div>
            <Wordmark light />
            <p className="mt-4 max-w-sm text-[15px] leading-relaxed">
              Free and independent health price transparency. Open code, open data, built in St. Louis.
            </p>
          </div>
          <nav aria-label="Use" className={col}>
            <p className="mb-1 font-bold text-white">Use</p>
            <Link className={a} to="/care">Check a price</Link>
            <Link className={a} to="/explore">Explore the data</Link>
            <Link className={a} to="/ai">Use with your AI</Link>
            <Link className={a} to="/data">Download the data</Link>
          </nav>
          <nav aria-label="Who it's for" className={col}>
            <p className="mb-1 font-bold text-white">Who it's for</p>
            {AUDIENCES.map((x) => <Link key={x.to} className={a} to={x.to}>{x.label}</Link>)}
          </nav>
          <nav aria-label="Trust" className={col}>
            <p className="mb-1 font-bold text-white">Trust</p>
            <Link className={a} to="/coverage">Coverage</Link>
            <Link className={a} to="/methodology">Methodology</Link>
            <Link className={a} to="/privacy">Privacy</Link>
            <Link className={a} to="/about">About and contact</Link>
            <a className={a} href={GITHUB} target="_blank" rel="noreferrer">Code on GitHub</a>
            <a className={a} href={HF} target="_blank" rel="noreferrer">Data on Hugging Face</a>
          </nav>
        </div>
        <p className="mt-12 border-t border-night-line pt-6 text-[13px] leading-relaxed text-[#9aabb8]">
          RateCommons is not a health plan or a provider. Prices are estimates from insurers' published negotiated rates and are
          not a quote or a bill; confirm costs with your insurer and provider. A missing price means no published rate, not that
          a provider is out of network. Nothing here is medical, legal or financial advice. Code numbers only: procedure
          descriptions are written in our own words.
        </p>
      </div>
    </footer>
  )
}

export default function SiteLayout() {
  const loc = useLocation()
  useEffect(() => {
    if (loc.hash) {
      const el = document.getElementById(decodeURIComponent(loc.hash.slice(1)))
      if (el) { setTimeout(() => el.scrollIntoView({ block: 'start' }), 30); return }
    }
    if (!loc.pathname.startsWith('/care/results')) window.scrollTo(0, 0)
  }, [loc.pathname, loc.hash])
  return (
    <div className="flex min-h-screen flex-col bg-white text-ink">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[2000] focus:rounded-lg focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <SiteHeader />
      <main id="main" className="flex-1"><Outlet /></main>
      <SiteFooter />
    </div>
  )
}
