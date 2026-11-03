import { Link } from 'react-router-dom'
import { ArrowRight, Bot, Database, EyeOff, FileSearch, Lock, ShieldCheck, UserX } from 'lucide-react'
import QuickSearch from './QuickSearch'
import { MCP_URL, CopyBox, PrivacyNote, statusSummary, useDataStatus, usePageTitle } from './ui'
import MRI from './mri-example.json'

const fmt = (v) => `$${v.toLocaleString('en-US')}`

function MriDots() {
  const lo = Math.log(150), hi = Math.log(2600)
  const X = (v) => 24 + ((Math.log(v) - lo) / (hi - lo)) * 952
  const ticks = [200, 300, 500, 1000, 2000]
  const tier = (v) => (v <= MRI.p25 ? '#0f6b52' : v < MRI.p75 ? '#2d5f88' : '#a4462b')
  const seen = {}
  const dots = MRI.prices.map((v, i) => {
    const b = Math.round(X(v) / 9)
    const k = (seen[b] = (seen[b] || 0) + 1) - 1
    const y = 92 - (k % 2 ? -1 : 1) * Math.ceil(k / 2) * 9
    return <circle key={i} cx={X(v)} cy={y} r="4.2" fill={tier(v)} fillOpacity="0.85" />
  })
  return (
    <svg viewBox="0 0 1000 170" className="h-auto w-full" role="img"
      aria-label={`${MRI.n} places, from ${fmt(MRI.min)} to ${fmt(MRI.max)}, median ${fmt(MRI.median)}`}>
      <line x1={X(MRI.median)} x2={X(MRI.median)} y1="22" y2="140" stroke="#0e1b2b" strokeWidth="1.5" strokeDasharray="4 4" />
      <text x={X(MRI.median) + 8} y="30" fontSize="15" fontWeight="600" fill="#0e1b2b">Median {fmt(MRI.median)}</text>
      {dots}
      <line x1="24" x2="976" y1="146" y2="146" stroke="#c9d3cf" />
      {ticks.map((t) => (
        <g key={t}>
          <line x1={X(t)} x2={X(t)} y1="146" y2="152" stroke="#9aaab5" />
          <text x={X(t)} y="166" fontSize="14" textAnchor="middle" fill="#5a6b7b">{fmt(t)}</text>
        </g>
      ))}
    </svg>
  )
}

function Stats() {
  const st = useDataStatus()
  const s = statusSummary(st)
  const cells = [
    { v: s ? s.insurers : '5', l: 'insurer families: Aetna, Anthem, Blue Cross Blue Shield, Cigna, UnitedHealthcare' },
    { v: s ? s.networks.toLocaleString('en-US') : '…', l: 'insurer networks loaded and searchable' },
    { v: s?.month || '…', l: 'latest data build, refreshed as insurers post new files' },
    { v: '$0', l: <>for everyone, with no account. <Link to="/coverage" className="font-medium text-brand-700 underline decoration-brand-200 underline-offset-2">See exactly what’s covered</Link></>, accent: true },
  ]
  return (
    <section aria-label="The data today" className="border-y border-[#e3e9e6] bg-white">
      <div className="wrap grid grid-cols-2 lg:grid-cols-4">
        {cells.map((c, i) => (
          <div key={i} className={`py-7 ${i % 2 ? 'border-l border-[#e3e9e6] pl-5 sm:pl-6' : 'pr-5 sm:pr-6'} ${i > 1 ? 'border-t border-[#e3e9e6] lg:border-t-0' : ''} ${i === 2 ? 'lg:border-l lg:pl-6' : ''}`}>
            <p className={`num font-display text-[34px] font-bold leading-none sm:text-[40px] ${c.accent ? 'text-brand-600' : 'text-ink'}`}>{c.v}</p>
            <p className="mt-2 text-[15px] leading-snug text-[#4a5a68]">{c.l}</p>
          </div>
        ))}
      </div>
    </section>
  )
}

const AUDIENCE = [
  { to: '/care', t: 'Patients and caregivers', d: 'Know what a scan, visit or test costs before you book, and where it’s cheaper on your plan.', cta: 'Check a price' },
  { to: '/for/providers', t: 'Practices and physician groups', d: 'See whether you’re paid below your peers, by insurer and code, before your next contract talk.', cta: 'Benchmark your rates' },
  { to: '/for/providers#hospitals', t: 'Hospitals and health systems', d: 'Compare your rates across insurers and against nearby systems, service line by service line.', cta: 'Compare providers' },
  { to: '/for/employers', t: 'Employers and benefits teams', d: 'Find your plan’s networks and see which one pays less for the care your people use.', cta: 'Find your plan' },
  { to: '/for/researchers', t: 'Researchers and journalists', d: 'Download the cleaned national dataset, read the methods, and cite a fixed monthly release.', cta: 'Get the data' },
  { to: '/for/developers', t: 'Developers and AI users', d: 'Connect Claude or ChatGPT in one step, call the API, or run SQL directly on the data.', cta: 'Start building' },
]

const COMPARE = [
  ['Negotiated rate lookup and benchmarks', 'Annual licence, demo first', 'Free, no account'],
  ['AI assistant over the data', 'Inside the paid platform', 'Works with your own Claude or ChatGPT'],
  ['API and SQL access', 'Enterprise tier', 'Open, no key'],
  ['Bulk data', 'Licensed data feeds', 'Free download in Parquet'],
  ['Patient price comparison', 'Rare, or only through an employer', 'Built in, private by design'],
]

export default function Home() {
  usePageTitle(null)
  return (
    <>
      <section className="bg-canvas">
        <div className="wrap pb-16 pt-14 sm:pt-[72px]">
          <p className="inline-flex rounded-full bg-[#e6f2ed] px-3.5 py-1.5 text-sm font-semibold text-brand-600">Free and independent price transparency</p>
          <h1 className="mt-5 max-w-[900px] font-display text-[42px] font-bold leading-[1.05] tracking-[-0.02em] text-ink sm:text-6xl">
            What health insurers actually pay, open to everyone.
          </h1>
          <p className="mt-6 max-w-[760px] text-lg leading-relaxed text-[#3a4a58] sm:text-xl">
            Insurers must publish their negotiated prices by law. RateCommons turns those files into answers anyone can use, whether
            you are checking a scan before you book it, negotiating a contract or studying the market. No account, no fee, nothing collected.
          </p>

          <div className="mt-11 grid gap-6 lg:grid-cols-2">
            <div className="card flex flex-col gap-5 p-6 sm:p-7">
              <div>
                <p className="kicker">For patients</p>
                <h2 className="mt-1.5 text-[28px] font-bold text-ink">Check a price for my care</h2>
                <p className="mt-1.5 text-base text-[#4a5a68]">Compare what your plan pays at places near you, and see your share.</p>
              </div>
              <QuickSearch idPrefix="home" />
              <PrivacyNote />
            </div>

            <div className="flex flex-col gap-5 rounded-2xl bg-night p-6 text-[#e8eef2] sm:p-7">
              <div>
                <p className="kicker !text-sea">For professionals</p>
                <h2 className="mt-1.5 text-[28px] font-bold text-white">Explore the data</h2>
                <p className="mt-1.5 text-base text-night-text">The rate intelligence that usually comes with an annual contract and a sales call.</p>
              </div>
              <ul className="grid gap-3 text-base">
                {['Look up negotiated rates by code, insurer and place', 'Benchmark a practice against its market and Medicare',
                  'Compare networks, plans and providers', 'Ask your own AI, call the API or download it all'].map((t, i) => (
                  <li key={t} className="flex gap-3"><span className="num font-bold text-sea">0{i + 1}</span>{t}</li>
                ))}
              </ul>
              <div className="mt-auto flex flex-wrap gap-3 pt-2">
                <Link to="/explore" className="btn-sea">Open the Explorer</Link>
                <Link to="/ai" className="btn-dark-line">Connect your AI</Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      <Stats />

      <section className="py-20 sm:py-[88px]">
        <div className="wrap grid items-center gap-12 lg:grid-cols-[1fr_1.15fr]">
          <div>
            <p className="kicker">Why it matters</p>
            <h2 className="h-section">The same brain MRI, the same insurer, the same city: {fmt(MRI.min)} or {fmt(MRI.max)}.</h2>
            <p className="mt-5 text-lg leading-relaxed text-[#3a4a58]">
              UnitedHealthcare’s published prices for a brain MRI without contrast, at the {MRI.n} places with a complete price (scan and reading) within {MRI.radius} miles of
              downtown St. Louis, differ more than tenfold. Until now, finding that out took a data team. Now it takes a ZIP code.
            </p>
            <Link to={`/care/results?payer=uhc&proc=mri-brain&zip=63110&r=25`} className="btn-line mt-7">See every place and price <ArrowRight className="h-4 w-4" /></Link>
          </div>
          <figure className="card m-0 p-6 sm:p-7">
            <figcaption className="text-[15px] font-semibold text-ink">Brain MRI without contrast · UnitedHealthcare · within 25 miles of 63110</figcaption>
            <p className="mt-1 text-[13px] text-ink-mute">Each dot is one place’s total published price. {MRI.n} places with a complete price, November 2026 data.</p>
            <div className="mt-4"><MriDots /></div>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-[13px] text-ink-soft">
              <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-brand-600" />Lowest quarter, up to {fmt(MRI.p25)}</span>
              <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-mint-600" />Middle half</span>
              <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-clay-600" />Highest quarter, {fmt(MRI.p75)} and up</span>
            </div>
            <p className="mt-4 text-[13px] text-ink-mute">Insurer-published negotiated rates; what you pay depends on your deductible and coinsurance.</p>
          </figure>
        </div>
      </section>

      <section className="bg-canvas py-20 sm:py-[88px]">
        <div className="wrap">
          <p className="kicker">How it works</p>
          <h2 className="h-section">From terabytes of insurer files to a plain answer</h2>
          <ol className="mt-10 grid gap-6 md:grid-cols-3">
            {[
              ['Insurers publish', 'Federal Transparency in Coverage rules make every major insurer post its negotiated rates each month, in machine-readable files that can run to hundreds of gigabytes each.'],
              ['We clean and connect', 'We collect every file, remove duplicates, flag placeholder rates, and link each price to real providers and places using public federal registries.'],
              ['You get answers', 'Search by procedure and ZIP, compare providers, download the full dataset, or ask your own AI assistant to do the analysis for you.'],
            ].map(([t, d], i) => (
              <li key={t} className="card p-7">
                <span className="num font-display text-[32px] font-bold text-brand-600">{i + 1}</span>
                <h3 className="mt-2.5 font-sans text-xl font-bold tracking-normal text-ink">{t}</h3>
                <p className="mt-2 text-base leading-relaxed text-[#3a4a58]">{d}</p>
              </li>
            ))}
          </ol>
          <Link to="/methodology" className="mt-8 inline-flex items-center gap-1 font-semibold text-brand-700 hover:text-brand-800">Read the full methodology <ArrowRight className="h-4 w-4" /></Link>
        </div>
      </section>

      <section id="audiences" className="py-20 sm:py-[88px]">
        <div className="wrap">
          <p className="kicker">Who it’s for</p>
          <h2 className="h-section">One source of truth, six ways in</h2>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {AUDIENCE.map((a) => (
              <Link key={a.t} to={a.to} className="card group block p-6 transition hover:border-brand-300">
                <h3 className="font-sans text-[19px] font-bold tracking-normal text-ink">{a.t}</h3>
                <p className="mt-1.5 text-[15px] leading-relaxed text-[#4a5a68]">{a.d}</p>
                <span className="mt-4 inline-flex items-center gap-1 font-semibold text-brand-700">{a.cta} <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" /></span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-night py-20 text-[#e8eef2] sm:py-[88px]">
        <div className="wrap">
          <p className="kicker !text-sea">Free means free</p>
          <h2 className="h-section !text-white">Everything the paid platforms sell, open to all</h2>
          <p className="mt-4 max-w-3xl text-lg leading-relaxed text-night-text">
            Commercial price-transparency platforms sell this as annual enterprise licences, priced on request. We think public prices should stay public.
          </p>
          <div className="mt-9 overflow-x-auto rounded-2xl border border-night-line">
            <table className="w-full min-w-[680px] border-collapse text-left text-base">
              <thead>
                <tr className="bg-night-2">
                  <th scope="col" className="px-5 py-4 font-semibold text-night-text">What you get</th>
                  <th scope="col" className="px-5 py-4 font-semibold text-night-text">Typical paid platform</th>
                  <th scope="col" className="px-5 py-4 font-bold text-sea">RateCommons</th>
                </tr>
              </thead>
              <tbody>
                {COMPARE.map(([a, b, c]) => (
                  <tr key={a} className="border-t border-night-line">
                    <td className="px-5 py-4">{a}</td><td className="px-5 py-4 text-night-text">{b}</td><td className="px-5 py-4 font-semibold text-white">{c}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section id="ai" className="py-20 sm:py-[88px]">
        <div className="wrap grid items-center gap-12 lg:grid-cols-2">
          <div>
            <p className="kicker">Use with your AI</p>
            <h2 className="h-section">Your AI becomes a pricing analyst in one step</h2>
            <p className="mt-5 text-lg leading-relaxed text-[#3a4a58]">
              Add RateCommons as a connector in Claude or ChatGPT and ask in plain English. Your assistant queries the live data, runs
              the numbers and shows its work. No login, no key.
            </p>
            <CopyBox text={MCP_URL} className="mt-6" />
            <Link to="/ai" className="mt-4 inline-flex items-center gap-1 font-semibold text-brand-700 hover:text-brand-800">Step-by-step setup guide <ArrowRight className="h-4 w-4" /></Link>
          </div>
          <div className="card bg-[#f9fbfa] p-6">
            <p className="text-[13px] font-bold uppercase tracking-[0.06em] text-ink-mute">Try asking</p>
            <ul className="mt-3 grid gap-2.5 text-base text-ink">
              {['What do Aetna, Anthem, Blue Cross, Cigna and UnitedHealthcare pay for a returning-patient office visit (99214) in Missouri, and how does that compare with Medicare?',
                'Which imaging centers near 63110 have the lowest UnitedHealthcare price for a brain MRI?',
                'Rank the radiology groups in Missouri by their median Cigna rate for a head CT (70450).'].map((q) => (
                <li key={q} className="flex gap-3 rounded-xl border border-line bg-white p-4"><Bot className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" aria-hidden="true" />{q}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="bg-[#e6f2ed] py-14">
        <div className="wrap grid gap-8 md:grid-cols-4">
          <div>
            <h2 className="text-[30px] font-bold text-ink">Private by design</h2>
            <p className="mt-2 text-base leading-relaxed text-[#2e3e4c]">We never receive your health information, so there is nothing to protect, leak or sell.</p>
            <Link to="/privacy" className="mt-3 inline-flex items-center gap-1 font-semibold text-brand-700">Our privacy promise <ArrowRight className="h-4 w-4" /></Link>
          </div>
          {[[UserX, 'No account', 'Nothing to sign up for, ever.'],
            [EyeOff, 'No cookies, no tracking', 'No analytics, no ads, no third-party scripts.'],
            [Lock, 'Stays on your device', 'Your deductible, plan details and insurance card are read in your browser and never uploaded.']].map(([Icon, t, d]) => (
            <div key={t}>
              <Icon className="h-6 w-6 text-brand-600" aria-hidden="true" />
              <h3 className="mt-2 font-sans text-[17px] font-bold tracking-normal text-ink">{t}</h3>
              <p className="mt-1 text-[15px] leading-relaxed text-[#2e3e4c]">{d}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="data" className="py-20 sm:py-[88px]">
        <div className="wrap grid gap-6 md:grid-cols-3">
          {[[Database, 'Download the data', 'The cleaned, deduplicated dataset in Parquet, one release a month, ready for DuckDB, pandas or R.', '/data', 'Browse datasets'],
            [ShieldCheck, 'See what’s covered', 'Every insurer and network we hold, when it was refreshed, and what is still missing. Updated with every release.', '/coverage', 'View coverage'],
            [FileSearch, 'Read the methods', 'How files are collected and cleaned, what a missing rate means, and the data traps we correct for.', '/methodology', 'Methodology']].map(([Icon, t, d, to, cta]) => (
            <div key={t} className="card p-7">
              <Icon className="h-7 w-7 text-brand-600" aria-hidden="true" />
              <h3 className="mt-3 text-[26px] font-bold text-ink">{t}</h3>
              <p className="mt-2 text-base leading-relaxed text-[#3a4a58]">{d}</p>
              <Link to={to} className="btn-line mt-5">{cta}</Link>
            </div>
          ))}
        </div>
      </section>
    </>
  )
}
