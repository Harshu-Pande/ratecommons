import { BadgeCheck, Calculator, CircleHelp, Database, EyeOff, MapPinned, ShieldCheck, TriangleAlert, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PROCS, loadProducts } from '../lib/data'
import { PAYER_NAMES } from '../lib/format'

const listOf = (xs) => xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`

export default function About() {
  // insurers whose prices are published right now (the data's products list), in display order
  const [payers, setPayers] = useState(['aetna', 'cigna', 'uhc'])
  useEffect(() => {
    loadProducts().then((p) => {
      const have = Object.keys(PAYER_NAMES).filter((k) => p && p[k])
      if (have.length) setPayers(have.sort((a, b) => PAYER_NAMES[a].localeCompare(PAYER_NAMES[b])))
    }).catch(() => {})
  }, [])
  const names = listOf(payers.map((k) => PAYER_NAMES[k]))
  return (
    <>
      <section className="bg-gradient-to-b from-brand-800 to-brand-700 pb-14 pt-12 text-white">
        <div className="mx-auto max-w-4xl px-4 sm:px-6">
          <p className="text-xs font-bold uppercase tracking-[0.14em] text-mint-200">About the data</p>
          <h1 className="mt-2 text-4xl font-extrabold sm:text-5xl">How CareCompass works</h1>
          <p className="mt-4 max-w-2xl text-lg text-brand-100">
            An advocacy project: making the prices insurers are now required to publish actually usable at the moment care is ordered.
          </p>
        </div>
      </section>
      <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6">
        <div className="grid gap-4 sm:grid-cols-4">
          {[[String(payers.length), `insurers: ${names}`], ['50 + DC', 'states covered'], [String(PROCS.length), 'common scans, visits, tests and therapies'], ['$0', 'cost, no accounts, no ads']].map(([v, l]) => (
            <div className="card p-4 text-center" key={l}>
              <div className="font-display text-3xl font-extrabold text-brand-700">{v}</div>
              <div className="mt-1 text-xs text-ink-mute">{l}</div>
            </div>
          ))}
        </div>
        <div className="prose-cc mt-10 space-y-10">
          <section>
            <h2 className="flex items-center gap-2 text-2xl font-bold text-ink"><Database className="h-6 w-6 text-brand-600" /> 1. Source data</h2>
            <p>
              Prices come from the in-network negotiated-rate files that {names} publish every month under
              the federal Transparency in Coverage rule. The open <a href="https://huggingface.co/ratecommons" target="_blank" rel="noreferrer">RateCommons</a> project
              downloads, de-duplicates and publishes them free. CareCompass uses a cleaned extract for the services in its list.
            </p>
            <p>Imaging prices are listed three ways, and CareCompass uses all three:</p>
            <ul>
              <li><b>Modifier 26 — professional component:</b> the radiologist’s reading fee.</li>
              <li><b>Modifier TC — technical component:</b> the facility fee (equipment, staff, supplies).</li>
              <li><b>No modifier — global:</b> scan and reading billed together by one group.</li>
            </ul>
            <p>
              Some clinics are not paid per code at all: an urgent care can have one flat amount per visit. When an insurer publishes
              such a contract we show it instead of the per-code price, because it is what the clinic is actually paid.
            </p>
          </section>
          <section>
            <h2 className="flex items-center gap-2 text-2xl font-bold text-ink"><MapPinned className="h-6 w-6 text-brand-600" /> 2. From contracts to real places</h2>
            <p>
              Insurer files list contracts by <b>tax ID and a list of clinicians’ NPI numbers</b>, with no addresses. Names in the files,
              like a legal business name, are not reliable, so we don’t use them to decide who is who. Instead:
            </p>
            <ul>
              <li>Each clinician’s practice address comes from the national NPI Registry (NPPES) and Medicare’s clinician directory. Addresses are grouped into places (same street address and ZIP, ignoring suite numbers).</li>
              <li>A contract shows up at a place when one of its clinicians practices there. That is how a small clinic whose doctors bill through a larger practice still gets a price — the details say “Billed through” that practice.</li>
              <li>Hospitals are matched to Medicare’s hospital list. For scans at a hospital, we list the radiology groups whose radiologists Medicare records as working at that hospital, with their reading fee.</li>
            </ul>
          </section>
          <section>
            <h2 className="flex items-center gap-2 text-2xl font-bold text-ink"><EyeOff className="h-6 w-6 text-brand-600" /> 3. Cleaning out “ghost” prices</h2>
            <p>
              Insurers often load one fee schedule for every clinician in a group. A nurse practitioner or a counselor can then show a
              price for a CT scan they will never read. Left in, these prices make a place look cheap or expensive for the wrong reason. So:
            </p>
            <ul>
              <li>We only use a price for clinicians whose specialty does that kind of care (radiologists for scan readings, therapists and psychiatrists for therapy, and so on).</li>
              <li><span className="inline-flex items-center gap-1 font-semibold text-mint-700"><BadgeCheck className="h-4 w-4" /> Confirmed</span> means one of those clinicians also billed this service (or a closely related one) to Medicare in the latest public data.</li>
              <li><span className="inline-flex items-center gap-1 font-semibold text-amber-800"><CircleHelp className="h-4 w-4" /> Likely</span> means the specialty fits but we found no Medicare record — common for children’s and women’s health.</li>
              <li>Prices far below or above what Medicare pays in your state (less than 0.15× or more than 15×) are hidden. Turn on “Show hidden prices” to see them with a warning.</li>
            </ul>
          </section>
          <section>
            <h2 className="flex items-center gap-2 text-2xl font-bold text-ink"><Users className="h-6 w-6 text-brand-600" /> 4. Plans and networks</h2>
            <p>
              Each insurer publishes prices per network. Pick your plan or network if you know it; otherwise we show the typical price
              across that insurer’s networks. A missing price means none was published — not that a provider is out of network.
            </p>
          </section>
          <section>
            <h2 className="flex items-center gap-2 text-2xl font-bold text-ink"><Calculator className="h-6 w-6 text-brand-600" /> 5. Your out-of-pocket estimate</h2>
            <p>For each place we take the negotiated price and split it into the bills you will get. Then, bill by bill:</p>
            <ul>
              <li>whatever is left of your <b>deductible</b> is applied first;</li>
              <li>your <b>coinsurance</b> percentage applies to the rest — or your flat <b>copay</b>, if your plan uses one for this kind of care;</li>
              <li>the total is capped at what’s left of your <b>out-of-pocket maximum</b>.</li>
            </ul>
            <p>Without your plan details we show the full negotiated price — what you’d owe if you haven’t met your deductible.</p>
          </section>
          <section>
            <h2 className="flex items-center gap-2 text-2xl font-bold text-ink"><ShieldCheck className="h-6 w-6 text-brand-600" /> 6. Privacy</h2>
            <p>
              There are no accounts or trackers, and there’s no server-side storage. Insurance-card and bill photos are processed in your
              browser with on-device text recognition (Tesseract.js) and never uploaded. Only cost numbers are extracted, and they’re kept
              in this browser tab’s session storage until you close it or tap “Clear my details.”
            </p>
          </section>
          <section className="rounded-2xl border border-sun-100 bg-sun-100/50 p-6">
            <h2 className="flex items-center gap-2 text-xl font-bold text-ink"><TriangleAlert className="h-5 w-5 text-amber-600" /> Limitations</h2>
            <ul>
              <li>Contract rates change monthly, and your specific plan may use a narrower network. Always confirm network status and price.</li>
              <li>Hospital facility fees are often a percentage of the hospital’s own charges; then no dollar amount is published and we say so.</li>
              <li>Contrast, extra views, sedation, add-on services or a follow-up can add charges.</li>
              <li>A listed place may not do every service. Call ahead.</li>
              <li>The estimate doesn’t account for prior authorization, plan exclusions or claims-processing order.</li>
            </ul>
          </section>
          <p className="text-sm">
            Questions or corrections? This is a student advocacy project for a Medicine &amp; Society course. <Link to="/">Back to price comparison →</Link>
          </p>
        </div>
      </div>
    </>
  )
}
