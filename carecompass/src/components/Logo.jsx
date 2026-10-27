export default function Logo({ className = 'h-8 w-8' }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <rect width="64" height="64" rx="16" fill="#143a73" />
      <circle cx="32" cy="32" r="19" fill="none" stroke="#fff" strokeWidth="4" />
      <path d="M32 15l6.5 17L32 49l-6.5-17z" fill="#10b981" />
      <path d="M25.5 32h13L32 49z" fill="#ffffff" />
      <circle cx="32" cy="32" r="2.6" fill="#143a73" />
    </svg>
  )
}
