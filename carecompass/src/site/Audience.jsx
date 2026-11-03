import { Link, Navigate, useParams } from 'react-router-dom'
import { ArrowRight, BarChart3, Bot, Building2, Code2, Database, FileSearch, Gauge, Landmark, Network, Scale, Search, Stethoscope, Table2, Users } from 'lucide-react'
import { CodeBlock, MCP_URL, PageHero, usePageTitle } from './ui'
import { GITHUB, HF } from './SiteLayout'

const ex = (tool, args) => `/explore?${new URLSearchParams({ tool, ...args, run: '1' })}`

/** 99214 (established patient visit, moderate) office rates in Missouri, from market_distribution on 2026-11-02. */
const SNAPSHOT = {
  title: 'Office visit (99214) in Missouri: what each insurer pays',
  medicare: 130.03,
  rows: [
    ['Aetna', 79.22, 102.53, 175.98, 70862],
    ['Anthem', 79.0, 112.05, 221.5, 28643],
    ['Blue Cross Blue Shield', 81.91, 122.09, 213.2, 28311],
    ['Cigna', 92.93, 125.27, 226.21, 18968],
    ['UnitedHealthcare', 82.82, 110.43, 214.24, 8710],
  ],
}

function Snapshot() {
  const top = 240
  const X = (v) => `${(v / top) * 100}%`
  return (
    <figure className="card p-6 sm:p-7">
      <figcaption>
        <p className="font-display text-xl font-bold text-ink">{SNAPSHOT.title}</p>
        <p className="mt-1 text-sm text-ink-mute">Median negotiated rate, and the middle 80% of provider groups. Dashed line: Medicare, ${SNAPSHOT.medicare}.</p>
      </figcaption>
      <div className="mt-6 grid gap-4">
        {SNAPSHOT.rows.map(([name, p10, med, p90, n]) => (
          <div key={name} className="grid grid-cols-[minmax(96px,170px)_1fr_64px] items-center gap-3 text-[15px]">
            <span className="leading-tight"><b className="block font-semibold text-ink">{name}</b><span className="text-xs text-ink-mute">{n.toLocaleString('en-US')} groups</span></span>
            <span className="relative h-7">
              <span className="absolute inset-y-[-8px] border-l-2 border-dashed border-clay-600" style={{ left: X(SNAPSHOT.medicare) }} aria-hidden="true" />
              <span className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-brand-200" style={{ left: X(p10), width: `calc(${X(p90)} - ${X(p10)})` }} />
              <span className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-brand-600" style={{ left: X(med) }} />
            </span>
            <span className="num text-right font-semibold">${med.toFixed(0)}</span>
          </div>
        ))}
      </div>
      <Link to={ex('market_distribution', { code: '99214', state: 'MO', group_by: 'payer', place: 'office' })}
        className="mt-6 inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:text-brand-800">
        Run this live, or change the code and state <ArrowRight className="h-4 w-4" />
      </Link>
    </figure>
  )
}

const PAGES = {
  providers: {
    title: 'For providers and hospitals',
    kicker: 'Providers, practices and hospitals',
    h1: 'Know what every insurer pays you, and everyone near you.',
    lead: 'Walk into contract talks with the same numbers the insurer has. Benchmark your rates against your market and Medicare, code by code, at no cost.',
    jobs: [
      [Gauge, 'Benchmark a practice', 'Where your rates sit against the local median and Medicare for the codes you bill most.', ex('benchmark_provider', { provider: 'Saint Louis University', codes: '99213,99214,99215', state: 'MO' })],
      [Scale, 'Compare with competitors', 'Line up nearby groups side by side for the same services and insurers.', ex('compare_providers', { codes: '99213,99214', state: 'MO', providers: 'Washington University, Saint Louis University' })],
      [BarChart3, 'See the market spread', 'Low, typical and high rates for any code in your state, by insurer or product.', ex('market_distribution', { code: '99214', state: 'MO', group_by: 'payer', place: 'office' })],
      [Network, 'Check your networks', 'Which insurer networks list your group, and under which tax ID.', ex('provider_networks', { provider: 'Saint Louis University', state: 'MO' })],
    ],
    points: [
      'Rates for professional (26) and technical (TC) parts kept apart, so imaging and pathology compare fairly.',
      "Placeholder rates ($0.01, $99,999) are flagged, not averaged in.",
      'Every rate links back to the insurer, network and month it came from.',
    ],
    paid: 'Contract-benchmarking tools usually cost tens of thousands of dollars a year per organization.',
  },
  employers: {
    title: 'For employers and benefits teams',
    kicker: 'Employers, brokers and benefits advisors',
    h1: 'See what your health plan actually pays.',
    lead: 'Self-funded employers have a legal duty to manage what the plan spends. RateCommons shows the rates behind your network, so you can steer people to fair-priced care and hold vendors to account.',
    jobs: [
      [FileSearch, "Find your plan's network", 'Search your company or plan name to find which insurer network files apply.', ex('find_plans', { query: 'Washington University' })],
      [BarChart3, 'Compare insurers for the same care', 'Medians and ranges for common services across every insurer in a state.', ex('market_distribution', { code: '99214', state: 'MO', group_by: 'payer', place: 'office' })],
      [Building2, 'Rank high-value providers', 'Rank groups by price across a basket of services, to design steerage or a narrow network.', ex('rank_providers', { codes: '70450,71250,74177,72148', state: 'MO', specialty: 'Radiology' })],
      [Users, 'Check network breadth', 'How many cardiologists, radiologists or therapists each network includes nearby.', ex('network_breadth', { state: 'MO', specialty: 'Cardiovascular Disease' })],
    ],
    points: [
      'Share the patient price checker with employees: no sign-up, nothing tracked.',
      'Medicare is shown beside every rate, the usual yardstick for reference-based pricing.',
      'Export any table to CSV for your broker, consultant or board.',
    ],
    paid: 'Plan-analytics platforms usually charge per member, per month, or a large annual license.',
  },
  researchers: {
    title: 'For researchers and journalists',
    kicker: 'Researchers, policy analysts and journalists',
    h1: 'Billions of published rates, cleaned and ready for analysis.',
    lead: 'Download the full, deduplicated data as Parquet, or query it in your browser. Every row keeps its raw value and source file, so your methods are reproducible and citable.',
    jobs: [
      [Database, 'Download the full data', 'Open Parquet datasets on Hugging Face, one per insurer, with a data card for each.', '/data'],
      [Table2, 'Query with SQL', 'Read-only DuckDB SQL over the full data, from a web form or the API.', '/explore?tool=run_sql'],
      [BarChart3, 'Describe a market', 'Percentiles and Medicare ratios for any code, state, city or specialty.', ex('market_distribution', { code: '99214', state: 'MO', group_by: 'product', place: 'office' })],
      [Landmark, 'Medicare baseline', 'The 2026 physician fee schedule by state for any set of codes.', ex('medicare_rate', { codes: '99213,99214,70553', state: 'MO' })],
    ],
    points: [
      'Duplicate files across networks are merged by content hash, so each rate fact is counted once.',
      'Provider groups are defined by tax ID plus NPI list, never by names insurers type in.',
      'Methods and every known limitation are written down on the methodology page.',
    ],
    paid: 'Research access to cleaned price-transparency data is usually sold as a license or data-room seat.',
  },
  developers: {
    title: 'For developers',
    kicker: 'Developers and data teams',
    h1: 'A free API and AI connector for health prices.',
    lead: 'Fifteen tools over the same data the site uses, through plain JSON over HTTPS or the Model Context Protocol. No key, no sign-up.',
    jobs: [
      [Code2, 'JSON API', 'POST arguments to /api/tool/{name} and get rows back. The schemas are at /api/tools.', '/explore'],
      [Bot, 'MCP for AI agents', 'Point any MCP client at the endpoint and your agent can price care in plain English.', '/ai'],
      [Database, 'Bulk data', 'Parquet on Hugging Face for anything heavier than an API call.', '/data'],
      [Search, 'Provider registry', 'Search the federal provider registry (NPPES) joined to network data.', ex('search_providers', { state: 'MO', city: 'Saint Louis', specialty: 'Radiology' })],
    ],
    points: [
      'Open source: the parsers, the pipeline and this site are on GitHub.',
      'Rate limits are generous; please cache, and use the bulk data for large pulls.',
      'Amounts are dollars with up to four decimal places, exactly as published.',
    ],
    paid: 'Commercial price-transparency APIs usually require a contract and charge per call or per seat.',
    code: `curl -X POST https://ratecommons.org/api/tool/market_distribution \\
  -H 'content-type: application/json' \\
  -d '{"code":"99214","state":"MO","group_by":"payer"}'`,
  },
}

export default function Audience() {
  const { who } = useParams()
  const p = PAGES[who]
  usePageTitle(p ? p.title : 'Not found')
  if (!p) return <Navigate to="/" replace />
  return (
    <>
      <PageHero kicker={p.kicker} title={p.h1} lead={p.lead}>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link to={p.jobs[0][3]} className="btn-go">{p.jobs[0][1]} <ArrowRight className="h-4 w-4" /></Link>
          <Link to="/ai" className="btn-line">Ask with your AI assistant</Link>
        </div>
      </PageHero>

      <section className="wrap py-16">
        <p className="kicker">What you can do</p>
        <h2 className="h-section mt-2">Start with a real question</h2>
        <div className="mt-8 grid gap-5 sm:grid-cols-2">
          {p.jobs.map(([Icon, t, d, to]) => (
            <Link key={t} to={to} className="group card flex gap-4 p-6 transition hover:border-brand-300">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"><Icon className="h-5 w-5" /></span>
              <span>
                <span className="block text-lg font-bold text-ink group-hover:text-brand-700">{t}</span>
                <span className="mt-1 block text-[15px] leading-relaxed text-ink-soft">{d}</span>
                <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-brand-700">Open <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" /></span>
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section className="border-y border-line bg-white">
        <div className="wrap grid gap-10 py-16 lg:grid-cols-[1fr_1.1fr] lg:items-center">
          <div>
            <p className="kicker">An example</p>
            <h2 className="h-section mt-2">Same visit, same state, very different prices</h2>
            <p className="lead mt-4">
              The typical Missouri office visit of this kind pays between about $103 and $125 depending on the insurer, and the
              highest-paid groups get more than twice what the lowest-paid get. Every number on the right came from the same tool you can run.
            </p>
            <ul className="mt-6 grid gap-3">
              {p.points.map((t) => (
                <li key={t} className="flex gap-3 text-[15px] leading-relaxed text-ink-soft">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-600" aria-hidden="true" />{t}
                </li>
              ))}
            </ul>
          </div>
          {p.code ? (
            <div className="grid gap-4">
              <CodeBlock code={p.code} label="API call" />
              <p className="text-sm text-ink-mute">Or add <code className="font-mono text-ink">{MCP_URL}</code> to an MCP client.</p>
              <Snapshot />
            </div>
          ) : <Snapshot />}
        </div>
      </section>

      <section className="wrap py-16">
        <div className="grid gap-6 rounded-3xl bg-night p-8 text-white sm:p-10 lg:grid-cols-[1.4fr_1fr] lg:items-center">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.08em] text-sea">Free, for everyone</p>
            <h2 className="mt-2 font-display text-3xl font-bold">No contract, no seat license, no sales call.</h2>
            <p className="mt-3 max-w-2xl leading-relaxed text-night-text">{p.paid} RateCommons is free and independent, and the code is open for anyone to check.</p>
          </div>
          <div className="flex flex-wrap gap-3 lg:justify-end">
            <Link to="/coverage" className="btn-sea">See what's covered</Link>
            <a href={who === 'researchers' ? HF : GITHUB} className="btn-dark-line" target="_blank" rel="noreferrer">{who === 'researchers' ? 'Hugging Face' : 'GitHub'}</a>
          </div>
        </div>
        <p className="mt-8 text-center text-[15px] text-ink-soft">
          <Stethoscope className="mr-1.5 inline h-4 w-4 text-brand-600" aria-hidden="true" />
          Looking for your own cost as a patient? <Link to="/care" className="font-semibold text-brand-700 underline decoration-brand-200 underline-offset-2">Check a price for your care</Link>
        </p>
      </section>
    </>
  )
}
