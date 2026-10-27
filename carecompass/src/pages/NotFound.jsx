import { Link } from 'react-router-dom'

function r() {
  return <div className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center px-4 text-center">
      <p className="font-display text-6xl font-extrabold text-brand-200">404</p>
      <h1 className="mt-2 text-2xl font-bold">We couldn’t find that page</h1>
      <Link to="/" className="btn-primary mt-6">
        Back to price comparison
      </Link>
    </div>;
}
export default r
