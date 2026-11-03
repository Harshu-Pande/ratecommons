import { Link } from 'react-router-dom'
import { ArrowRight, Baby, BrainCircuit, Building2, ClipboardList, Lock, MapPinned, Receipt, SlidersHorizontal, Stethoscope } from 'lucide-react'
import SearchForm, { searchUrl } from '../components/SearchForm'
import InfoTip from '../components/InfoTip'
import { usePageTitle } from '../site/ui'

const EXAMPLES = [
  { icon: Baby, title: 'A child’s head CT in Memphis', sub: 'Aetna · children’s hospitals first · who reads the scan',
    to: searchUrl({ payer: 'aetna', proc: 'ct-head', zip: '38105', r: '25', kid: true }) },
  { icon: Stethoscope, title: 'Urgent care visit in St. Louis', sub: 'UnitedHealthcare · flat per-visit contracts',
    to: searchUrl({ payer: 'uhc', proc: 'urgent-care', zip: '63110', r: '25' }) },
  { icon: BrainCircuit, title: 'TMS therapy near O’Fallon, IL', sub: 'Cigna · doctors who bill through another practice',
    to: searchUrl({ payer: 'cigna', proc: 'tms', zip: '62269', r: '25' }) },
  { icon: MapPinned, title: 'Knee MRI in Dallas', sub: 'Aetna · compare imaging centers and hospitals',
    to: searchUrl({ payer: 'aetna', proc: 'mri-knee', zip: '75201', r: '25' }) },
]

function Part({ Icon, title, sub, amt, tone, tip }) {
  return (
    <div className={`rounded-2xl p-3 sm:p-4 ${{ brand: 'bg-brand-50 text-brand-800', mint: 'bg-mint-50 text-mint-800', ink: 'bg-night text-white' }[tone]}`}>
      <Icon className="mx-auto h-5 w-5 opacity-80" />
      <div className="mt-1.5 text-[13px] font-semibold leading-tight">{title}<InfoTip k={tip} /></div>
      <div className="text-[11px] opacity-75">{sub}</div>
      <div className="mt-1 font-display text-lg font-bold">{amt}</div>
    </div>
  )
}

export default function Home() {
  usePageTitle('Check a price for your care')
  return (
    <>
      <section className="pb-12 pt-10 sm:pt-14">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <p className="kicker">For patients</p>
          <h1 className="mt-2.5 max-w-3xl font-display text-[38px] font-bold leading-[1.08] tracking-[-0.02em] text-ink sm:text-5xl">
            Know what you’ll pay before you go.
          </h1>
          <p className="mt-4 max-w-2xl text-lg leading-relaxed text-ink-soft">
            Two in-network places can charge the same plan very different prices for the same scan or visit. Compare the prices your insurer
            actually negotiated, cleaned of placeholder rates, and see your own out-of-pocket cost.
          </p>
          <div className="mt-8"><SearchForm /></div>
          <p className="mt-3 flex items-center justify-center gap-1.5 text-center text-[13px] text-ink-mute">
            <Lock className="h-3.5 w-3.5 text-brand-600" aria-hidden="true" />
            Private by design: no account, no cookies, no tracking. Your plan details and card stay on this device.
          </p>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 pb-14 sm:px-6">
        <p className="eyebrow">Try an example</p>
        <h2 className="mt-2 text-3xl font-bold">Real situations, real prices</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {EXAMPLES.map(({ icon: Icon, title, sub, to }) => (
            <Link key={title} to={to} className="group rounded-2xl border border-line bg-white p-5 transition hover:border-brand-300">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600"><Icon className="h-5 w-5" /></span>
              <h3 className="mt-3 font-sans font-bold tracking-normal text-ink group-hover:text-brand-700">{title}</h3>
              <p className="mt-1 text-sm text-ink-mute">{sub}</p>
              <span className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-brand-700">See prices <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" /></span>
            </Link>
          ))}
        </div>
      </section>

      <section className="border-y border-line bg-white">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
          <p className="eyebrow text-center">How it works</p>
          <h2 className="mt-2 text-center text-3xl font-bold">Three steps to a fair price</h2>
          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {[
              [ClipboardList, 'Tell us what you need', 'Pick the scan, visit, lab or therapy in plain English. We match it to the billing code.'],
              [SlidersHorizontal, 'Add your plan details', 'Optional: enter your deductible and coinsurance, or scan your card. Everything stays on your device.'],
              [MapPinned, 'Compare and choose', 'See nearby places with your estimated cost, who bills you, and how sure we are of each price.'],
            ].map(([Icon, t, d], i) => (
              <div className="rounded-2xl bg-canvas p-6" key={t}>
                <div className="flex items-center gap-3">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-white"><Icon className="h-5 w-5" /></span>
                  <span className="text-sm font-bold text-brand-700">Step {i + 1}</span>
                </div>
                <h3 className="mt-4 font-sans text-lg font-bold tracking-normal">{t}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">{d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-2 lg:items-center">
          <div>
            <p className="eyebrow">Avoid bill surprises</p>
            <h2 className="mt-2 text-3xl font-bold">Why one scan often means two bills</h2>
            <p className="mt-4 leading-relaxed text-ink-soft">
              Imaging has two parts. The <b>facility</b> takes the pictures, and a <b>radiologist</b>, often from a separate physician
              group, reads them. At a hospital, RateCommons shows which groups read scans there and what each charges your plan.
            </p>
            <Link to="/care/your-rights" className="mt-5 inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:text-brand-800">
              Learn your rights under the No Surprises Act <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          <div className="card p-6">
            <div className="grid grid-cols-[1fr_auto_1fr_auto_1fr] items-center gap-2 text-center">
              <Part Icon={Building2} title="Facility fee" sub="equipment, technologist" amt="$700" tone="brand" tip="facility" />
              <span className="text-2xl font-light text-ink-mute">+</span>
              <Part Icon={Stethoscope} title="Radiologist fee" sub="reading and report" amt="$300" tone="mint" tip="professional" />
              <span className="text-2xl font-light text-ink-mute">=</span>
              <Part Icon={Receipt} title="Total price" sub="what we compare" amt="$1,000" tone="ink" tip="negotiated" />
            </div>
            <div className="mt-6 flex h-4 overflow-hidden rounded-full"><div className="bg-brand-600" style={{ width: '70%' }} /><div className="bg-mint-500" style={{ width: '30%' }} /></div>
            <p className="mt-3 text-xs text-ink-mute">Illustration only. Your deductible and coinsurance apply to each bill.</p>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 pb-20 sm:px-6">
        <div className="grid gap-6 md:grid-cols-3">
          <div className="rounded-3xl bg-night p-7 text-white md:col-span-2">
            <p className="text-xs font-bold uppercase tracking-[0.08em] text-sea">For clinicians and referral coordinators</p>
            <h2 className="mt-2 text-2xl font-bold">Make cost part of the referral conversation</h2>
            <p className="mt-3 max-w-2xl leading-relaxed text-night-text">
              When quality and access are comparable, sending a patient to the lower-priced in-network site can save them hundreds of
              dollars, especially early in the plan year, before the deductible is met. Share this tool at the point of ordering.
            </p>
          </div>
          <Link to="/care/choose-a-plan" className="group rounded-3xl border border-line bg-white p-7 transition hover:border-brand-300">
            <p className="eyebrow">Open enrollment?</p>
            <h2 className="mt-2 text-2xl font-bold">Find the plan that fits how you use care</h2>
            <span className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-brand-700">Try the plan-fit calculator <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" /></span>
          </Link>
        </div>
      </section>
    </>
  )
}
