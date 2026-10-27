import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import { ProfileProvider } from './lib/store'

const Results = lazy(() => import('./pages/Results'))
const PlanGuide = lazy(() => import('./pages/PlanGuide'))
const Rights = lazy(() => import('./pages/Rights'))
const Resources = lazy(() => import('./pages/Resources'))
const About = lazy(() => import('./pages/About'))
const NotFound = lazy(() => import('./pages/NotFound'))
const Loading = () => <div className="flex min-h-[50vh] items-center justify-center text-ink-mute">Loading…</div>

export default function App() {
  return (
    <ProfileProvider>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="results" element={<Results />} />
            <Route path="choose-a-plan" element={<PlanGuide />} />
            <Route path="your-rights" element={<Rights />} />
            <Route path="resources" element={<Resources />} />
            <Route path="about" element={<About />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </ProfileProvider>
  )
}
