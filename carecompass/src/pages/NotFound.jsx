import { Link } from 'react-router-dom'
import { usePageTitle } from '../site/ui'

export default function NotFound() {
  usePageTitle('Page not found')
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center px-4 py-16 text-center">
      <p className="font-display text-6xl font-bold text-brand-200">404</p>
      <h1 className="mt-2 font-display text-3xl font-bold text-ink">We couldn't find that page</h1>
      <p className="mt-3 text-ink-soft">The link may be old, or the page may have moved.</p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <Link to="/" className="btn-go">Go to the home page</Link>
        <Link to="/care" className="btn-line">Check a price</Link>
      </div>
    </div>
  )
}
