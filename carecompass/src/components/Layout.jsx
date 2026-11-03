import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Lock } from 'lucide-react'

const NAV = [
  { to: '/care', label: 'Check a price', end: true },
  { to: '/care/choose-a-plan', label: 'Choose a plan' },
  { to: '/care/your-rights', label: 'Your rights' },
  { to: '/care/resources', label: 'Help paying' },
  { to: '/care/how-prices-work', label: 'How prices work' },
]

/** The patient side of RateCommons: its own short menu and the privacy promise, under the site header. */
export default function CareLayout() {
  const loc = useLocation()
  const results = loc.pathname.startsWith('/care/results')
  return (
    <div className="bg-canvas">
      <div className="border-b border-line bg-white">
        <div className={`${results ? 'mx-auto max-w-[1600px] px-4 sm:px-6' : 'wrap'} flex h-12 items-center justify-between gap-4`}>
          <nav aria-label="Patients" className="-mx-2 flex min-w-0 items-center gap-0.5 overflow-x-auto">
            <span className="mr-2 hidden shrink-0 rounded-full bg-[#e6f2ed] px-2.5 py-1 text-xs font-bold text-brand-700 sm:inline">For patients</span>
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}
                className={({ isActive }) => `shrink-0 rounded-lg px-2.5 py-1.5 text-sm font-medium ${isActive || (n.end && results) ? 'bg-brand-50 text-brand-700' : 'text-ink-soft hover:text-ink'}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <p className="hidden shrink-0 items-center gap-1.5 text-[13px] text-ink-soft xl:flex">
            <Lock className="h-3.5 w-3.5 text-brand-600" aria-hidden="true" /> Private: no account, no tracking, nothing you type leaves this device
          </p>
        </div>
      </div>
      <Outlet />
    </div>
  )
}
