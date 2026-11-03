export default function Logo({ className = 'h-8 w-8', light = false }) {
  return (
    <svg viewBox="0 0 30 30" className={className} aria-hidden="true">
      <rect x="1" y="1" width="28" height="28" rx="8" fill={light ? '#8fd3bc' : '#0f6b52'} />
      <path d="M8 20V10h6.5a3.5 3.5 0 0 1 0 7H8m6.5 0L21 20" fill="none" stroke={light ? '#0e1b2b' : '#ffffff'}
        strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function Wordmark({ light = false, size = 'text-[22px]' }) {
  return (
    <span className="flex items-center gap-2.5">
      <Logo className="h-[30px] w-[30px]" light={light} />
      <span className={`font-display ${size} font-bold tracking-tight ${light ? 'text-white' : 'text-ink'}`}>RateCommons</span>
    </span>
  )
}
