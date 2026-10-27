import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import Logo from './Logo'

const NAV = [
  { to: '/', label: 'Compare prices', end: true },
  { to: '/choose-a-plan', label: 'Choose a plan' },
  { to: '/your-rights', label: 'Your rights' },
  { to: '/resources', label: 'Savings resources' },
  { to: '/about', label: 'About the data' },
]

export default function Layout() {
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => {
    setOpen(false)
    if (!loc.pathname.startsWith('/results')) window.scrollTo(0, 0)
  }, [loc.pathname])
  return (
    <div className="flex min-h-screen flex-col bg-canvas text-ink">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[2000] focus:rounded-lg focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-[1000] border-b border-line bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <Logo className="h-9 w-9" />
            <span className="font-display text-xl font-extrabold tracking-tight text-brand-800">
              Care<span className="text-mint-600">Compass</span>
            </span>
          </Link>
          <nav className="hidden items-center gap-1 lg:flex" aria-label="Main">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}
                className={({ isActive }) => `rounded-lg px-3 py-2 text-sm font-medium transition ${isActive ? 'bg-brand-50 text-brand-700' : 'text-ink-soft hover:bg-canvas hover:text-ink'}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <button className="rounded-lg p-2 text-ink-soft hover:bg-canvas lg:hidden" onClick={() => setOpen((v) => !v)}
            aria-label="Menu" aria-expanded={open}>
            {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </button>
        </div>
        {open && (
          <nav className="border-t border-line bg-white px-4 pb-4 pt-2 lg:hidden" aria-label="Mobile">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}
                className={({ isActive }) => `block rounded-lg px-3 py-3 text-base font-medium ${isActive ? 'bg-brand-50 text-brand-700' : 'text-ink-soft'}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <main id="main" className="flex-1"><Outlet /></main>
      <Footer />
    </div>
  )
}

function Footer() {
  return (
    <footer className="border-t border-line bg-white">
      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-10 sm:px-6 md:grid-cols-4">
        <div className="md:col-span-2">
          <div className="flex items-center gap-2">
            <Logo className="h-7 w-7" />
            <span className="font-display text-lg font-extrabold text-brand-800">Care<span className="text-mint-600">Compass</span></span>
          </div>
          <p className="mt-3 max-w-md text-sm leading-relaxed text-ink-mute">
            A patient-advocacy project that turns insurer-published price data into plain-English cost estimates, so
            patients and clinicians can factor affordability into where care happens.
          </p>
          <p className="mt-4 max-w-md text-xs leading-relaxed text-ink-mute">
            Estimates only — not a guarantee of cost or coverage, and not medical, legal or financial advice. Always
            confirm network status, price and your benefits with your insurer and the provider before scheduling.
          </p>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-ink">Tools</h3>
          <ul className="mt-3 space-y-2 text-sm text-ink-mute">
            <li><Link className="hover:text-brand-700" to="/">Compare care prices</Link></li>
            <li><Link className="hover:text-brand-700" to="/choose-a-plan#calculator">Plan fit calculator</Link></li>
            <li><Link className="hover:text-brand-700" to="/choose-a-plan">Plan types explained</Link></li>
          </ul>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-ink">Learn</h3>
          <ul className="mt-3 space-y-2 text-sm text-ink-mute">
            <li><Link className="hover:text-brand-700" to="/your-rights">No Surprises Act</Link></li>
            <li><Link className="hover:text-brand-700" to="/your-rights#gfe">Good Faith Estimates</Link></li>
            <li><Link className="hover:text-brand-700" to="/resources">Prescription savings</Link></li>
            <li><Link className="hover:text-brand-700" to="/about">Methodology & data</Link></li>
          </ul>
        </div>
      </div>
      <div className="border-t border-line py-4 text-center text-xs text-ink-mute">
        © {new Date().getFullYear()} CareCompass · Built for a Medicine & Society advocacy project · Prices from insurers'
        Transparency in Coverage files via RateCommons · Map tiles © Esri · © OpenStreetMap contributors
      </div>
    </footer>
  )
}
