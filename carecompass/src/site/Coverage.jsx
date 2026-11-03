import { Link } from 'react-router-dom'
import { CheckCircle2, CircleDashed, Info, Loader2 } from 'lucide-react'
import { PAYER_LABEL, PAYER_ORDER, PageHero, statusSummary, useDataStatus, usePageTitle } from './ui'
import { CONTACT } from './SiteLayout'

const fmtDate = (s) => (s ? new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }) : '')

const NOT_YET = [
  ['More insurers', 'Humana, Kaiser Permanente, Centene (Ambetter), Molina and many regional plans publish files too. We add insurers as the pipeline can process them.'],
  ['All services for every insurer', 'For some insurers we load a set of common services first (shown above), then the full code list.'],
  ['Hospital price lists', 'Hospitals publish their own standard-charge files under a separate rule. They are not in RateCommons yet.'],
  ['Prescription drugs', 'Drug prices are published separately and are not included.'],
  ['Medicare and Medicaid plans', "The rule covers employer and individual-market plans, not Medicare Advantage or Medicaid. We show traditional Medicare's fee schedule as a yardstick."],
]

export default function Coverage() {
  usePageTitle('Coverage')
  const st = useDataStatus()
  const sum = statusSummary(st)
  return (
    <>
      <PageHero kicker="Coverage" title="What's in the data today."
        lead="Insurers publish new files every month. This page reads the live data service, so it is always current." />

      <section className="wrap py-16">
        {sum && (
          <div className="mb-8 grid gap-4 sm:grid-cols-3">
            {[[sum.insurers, 'insurers'], [sum.networks.toLocaleString('en-US'), 'networks (distinct rate files)'], [sum.month, 'latest build']].map(([v, l]) => (
              <div key={l} className="card p-5"><p className="font-display text-3xl font-bold text-ink">{v}</p><p className="mt-1 text-sm text-ink-soft">{l}</p></div>
            ))}
          </div>
        )}
        <div className="overflow-x-auto rounded-2xl border border-line bg-white">
          <table className="w-full min-w-[640px] text-left text-[15px]">
            <thead className="bg-[#f7f9f8] text-[13px] font-semibold text-ink-soft">
              <tr>
                <th scope="col" className="px-5 py-3">Insurer</th>
                <th scope="col" className="px-5 py-3 text-right">Networks</th>
                <th scope="col" className="px-5 py-3 text-right">Billing codes</th>
                <th scope="col" className="px-5 py-3">Services loaded</th>
                <th scope="col" className="px-5 py-3">Built</th>
              </tr>
            </thead>
            <tbody>
              {st === undefined && (
                <tr><td colSpan={5} className="px-5 py-8 text-center text-ink-mute"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Reading the live data service…</td></tr>
              )}
              {st === null && (
                <tr><td colSpan={5} className="px-5 py-8 text-center text-clay-600">The data service did not answer. Please refresh in a moment.</td></tr>
              )}
              {st?.payers && PAYER_ORDER.filter((p) => st.payers[p]).map((p) => {
                const v = st.payers[p]
                return (
                  <tr key={p} className="border-t border-line align-top">
                    <td className="px-5 py-4 font-semibold text-ink">{PAYER_LABEL[p]}</td>
                    <td className="num px-5 py-4 text-right">{v.networks.toLocaleString('en-US')}</td>
                    <td className="num px-5 py-4 text-right">{v.codes.toLocaleString('en-US')}</td>
                    <td className="px-5 py-4 text-ink-soft">
                      {v.coverage
                        ? <span className="flex gap-1.5"><CircleDashed className="mt-0.5 h-4 w-4 shrink-0 text-clay-600" aria-hidden="true" />Common services first: {v.coverage.replace(/^common services only:\s*/, '')}</span>
                        : <span className="flex gap-1.5"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" aria-hidden="true" />Every published service</span>}
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-ink-soft">{fmtDate(v.built)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 flex gap-2 text-sm text-ink-mute">
          <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          A network here is one distinct rate file. Insurers often publish one file per product or region, and many plans can share a file.
          The billing-code count includes every code with a rate in any of the insurer's files.
        </p>
      </section>

      <section className="border-t border-line bg-white">
        <div className="wrap grid gap-10 py-16 lg:grid-cols-[1fr_1.4fr]">
          <div>
            <p className="kicker">Not covered yet</p>
            <h2 className="h-section mt-2">What's missing, said plainly</h2>
            <p className="lead mt-4">If an insurer or service you need is missing, tell us. It helps us decide what to add next.</p>
            <a href={CONTACT} target="_blank" rel="noreferrer" className="btn-line mt-6">Request an insurer</a>
          </div>
          <ul className="grid gap-4">
            {NOT_YET.map(([t, d]) => (
              <li key={t} className="rounded-2xl bg-canvas p-5">
                <p className="font-bold text-ink">{t}</p>
                <p className="mt-1 text-[15px] leading-relaxed text-ink-soft">{d}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="wrap py-14 text-center">
        <p className="text-[15px] text-ink-soft">How we read and clean each file is on the <Link to="/methodology" className="font-semibold text-brand-700 underline decoration-brand-200 underline-offset-2">methodology</Link> page.</p>
      </section>
    </>
  )
}
