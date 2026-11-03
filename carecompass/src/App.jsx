import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import SiteLayout from './site/SiteLayout'
import Home from './site/Home'
import CareLayout from './components/Layout'
import CareHome from './pages/Home'
import { ProfileProvider } from './lib/store'

const Results = lazy(() => import('./pages/Results'))
const PlanGuide = lazy(() => import('./pages/PlanGuide'))
const Rights = lazy(() => import('./pages/Rights'))
const Resources = lazy(() => import('./pages/Resources'))
const HowPrices = lazy(() => import('./pages/About'))
const Explore = lazy(() => import('./site/Explore'))
const Audience = lazy(() => import('./site/Audience'))
const AI = lazy(() => import('./site/AI'))
const Data = lazy(() => import('./site/Data'))
const Coverage = lazy(() => import('./site/Coverage'))
const Methodology = lazy(() => import('./site/Methodology'))
const Privacy = lazy(() => import('./site/Privacy'))
const About = lazy(() => import('./site/About'))
const NotFound = lazy(() => import('./pages/NotFound'))

const Loading = () => <div className="flex min-h-[50vh] items-center justify-center text-ink-mute">Loading…</div>

/** Links from the old patient app (care.ratecommons.org/results?…) land on the same page under /care. */
function Legacy({ to }) {
  const loc = useLocation()
  return <Navigate to={`${to}${loc.search}${loc.hash}`} replace />
}

export default function App() {
  return (
    <ProfileProvider>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route element={<SiteLayout />}>
            <Route index element={<Home />} />
            <Route path="care" element={<CareLayout />}>
              <Route index element={<CareHome />} />
              <Route path="results" element={<Results />} />
              <Route path="choose-a-plan" element={<PlanGuide />} />
              <Route path="your-rights" element={<Rights />} />
              <Route path="resources" element={<Resources />} />
              <Route path="how-prices-work" element={<HowPrices />} />
            </Route>
            <Route path="explore" element={<Explore />} />
            <Route path="for/:who" element={<Audience />} />
            <Route path="ai" element={<AI />} />
            <Route path="data" element={<Data />} />
            <Route path="coverage" element={<Coverage />} />
            <Route path="methodology" element={<Methodology />} />
            <Route path="privacy" element={<Privacy />} />
            <Route path="about" element={<About />} />
            <Route path="results" element={<Legacy to="/care/results" />} />
            <Route path="choose-a-plan" element={<Legacy to="/care/choose-a-plan" />} />
            <Route path="your-rights" element={<Legacy to="/care/your-rights" />} />
            <Route path="resources" element={<Legacy to="/care/resources" />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </ProfileProvider>
  )
}
