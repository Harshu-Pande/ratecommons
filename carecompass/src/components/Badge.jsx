import { AlertTriangle, BadgeCheck, CircleHelp, Percent } from 'lucide-react'
import InfoTip from './InfoTip'

const B = {
  c: { label: 'Confirmed', cls: 'bg-mint-50 text-mint-700', Icon: BadgeCheck, tip: 'confirmed' },
  l: { label: 'Likely', cls: 'bg-sun-100 text-amber-800', Icon: CircleHelp, tip: 'likely' },
  h: { label: 'Check this price', cls: 'bg-red-50 text-red-700', Icon: AlertTriangle, tip: 'hidden' },
  x: { label: '% of charges', cls: 'bg-slate-100 text-slate-700', Icon: Percent, tip: 'percentage' },
}

export default function Badge({ b, tip = false, className = '' }) {
  const x = B[b] || B.l
  return (
    <span className={`chip ${x.cls} ${className}`}>
      <x.Icon className="h-3.5 w-3.5" /> {x.label}{tip && <InfoTip k={x.tip} />}
    </span>
  )
}
