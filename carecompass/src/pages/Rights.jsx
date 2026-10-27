import { Fragment } from 'react'
import { ArrowRight, BadgeDollarSign, ExternalLink, FileSearch, FileText, Gavel, Phone, ShieldCheck, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router-dom'

var Cg = ({
    id: e,
    icon: Ct,
    eyebrow: n,
    title: r,
    children: i
  }) => <section id={e} className="scroll-mt-20 border-b border-line py-12 last:border-0">
      <div className="flex items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-white">
          <Ct className="h-5 w-5" />
        </span>
        <p className="eyebrow">{n}</p>
      </div>
      <h2 className="mt-3 text-3xl font-bold">{r}</h2>
      <div className="prose-cc mt-2 max-w-3xl">{i}</div>
    </section>,
  CU = ({
    tone: e = `brand`,
    title: t,
    children: n
  }) => {
    let r = {
      brand: `bg-brand-50 text-brand-900 border-brand-100`,
      mint: `bg-mint-50 text-mint-700 border-mint-100`,
      sun: `bg-sun-100/60 text-amber-900 border-sun-100`
    }[e];
    return <div className={`mt-5 rounded-2xl border p-5 text-sm leading-relaxed ${r}`}>
        <b className="block text-base">{t}</b>
        <div className="mt-1">{n}</div>
      </div>;
  };
function v() {
  return <Fragment>
      <section className="bg-gradient-to-b from-brand-800 to-brand-700 pb-14 pt-12 text-white">
        <div className="mx-auto max-w-5xl px-4 sm:px-6">
          <p className="text-xs font-bold uppercase tracking-[0.14em] text-mint-200">Know your rights</p>
          <h1 className="mt-2 text-4xl font-extrabold sm:text-5xl">Federal protections every patient should know</h1>
          <p className="mt-4 max-w-2xl text-lg text-brand-100">
            Laws passed since 2021 give you the right to see prices in advance, protect you from many surprise bills,
            and let you challenge bills that come in far above an estimate.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            {[[`#nsa`, `No Surprises Act`], [`#transparency`, `Price transparency`], [`#gfe`, `Good Faith Estimates`], [`#bills`, `Fighting a bill`]].map(([e, t]) => <a href={e} className="rounded-full bg-white/10 px-4 py-2 text-sm font-medium ring-1 ring-white/20 hover:bg-white/20" key={e}>
                {t}
              </a>)}
          </div>
        </div>
      </section>
      <div className="mx-auto max-w-5xl px-4 sm:px-6">
        <Cg id="nsa" icon={ShieldCheck} eyebrow="In effect since Jan 1, 2022" title="The No Surprises Act">
          <p>
            A “surprise bill” happens when you get care from an out-of-network provider you didn’t choose — often in an
            emergency, or from a doctor working inside an in-network hospital. The No Surprises Act bans most of these
            “balance bills” for people with private or job-based insurance.
          </p>
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            {[[`Emergency care`, `Emergency services must be billed at in-network cost-sharing, even at an out-of-network hospital, and without prior authorization.`], [`In-network facilities`, `At an in-network hospital or surgery center, out-of-network radiologists, anesthesiologists, pathologists and similar doctors can’t balance-bill you.`], [`Air ambulances`, `Out-of-network air ambulance bills are limited to in-network cost-sharing. (Ground ambulances aren’t covered by the federal law.)`]].map(([e, t]) => <div className="rounded-2xl border border-line bg-white p-4" key={e}>
                <div className="font-semibold text-ink">{e}</div>
                <p className="!mt-1 text-sm">{t}</p>
              </div>)}
          </div>
          <CU tone="mint" title="Why this matters for imaging">
            If your MRI is done at an in-network hospital, the radiologist who reads it can’t send you an out-of-network
            bill — even if that radiologist’s group isn’t in your plan. What you owe should be based on your in-network
            deductible, copay and coinsurance, and it counts toward your in-network out-of-pocket maximum.
          </CU>
          <p>
            Be careful with forms: for certain non-emergency care, an out-of-network provider can ask you to{" "}
            <b>sign a notice waiving</b> these protections. You never have to sign it, and some providers (like
            radiologists and anesthesiologists at in-network facilities) can’t ask at all.
          </p>
        </Cg>
        <Cg id="transparency" icon={FileSearch} eyebrow="Hospital Price Transparency (2021) \xB7 Transparency in Coverage (2022\u20132024)" title="Price transparency rules">
          <p>Two federal rules make the data behind CareCompass public:</p>
          <ul>
            <li>
              <b>Hospital Price Transparency</b> (effective January 1, 2021) requires every hospital to post a
              machine-readable file of its standard charges — including payer-specific negotiated rates and cash prices
              — and a consumer-friendly list of at least 300 “shoppable” services (70 chosen by CMS, including the
              imaging tests on this site) or an online price estimator.
            </li>
            <li>
              <b>Transparency in Coverage</b> requires most private health plans to publish their in-network negotiated
              rates in monthly machine-readable files (since July 2022) and to give members an online price-comparison
              tool for all covered services (since January 2024).
            </li>
          </ul>
          <CU title="How CareCompass uses this">
            We took UnitedHealthcare’s published negotiated rates for 10 CMS shoppable imaging services in Missouri,
            matched each billing group to a real location, and turned the numbers into a map-based estimate you can
            personalize. <Link to="/about">Read the methodology →</Link>
          </CU>
          <p>
            Your own insurer’s member portal must also offer a cost estimator based on your plan — use it to
            double-check any estimate you see here.
          </p>
        </Cg>
        <Cg id="gfe" icon={FileText} eyebrow="Uninsured or paying cash" title="Good Faith Estimates">
          <p>
            If you don’t have insurance — or you choose not to use it — providers must give you a{" "}
            <b>Good Faith Estimate</b> of expected charges when you schedule care at least 3 business days ahead, or any
            time you ask.
          </p>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            {[[`3–9 business days ahead`, `Estimate due within 1 business day of scheduling`], [`10+ business days ahead`, `Estimate due within 3 business days of scheduling`], [`Just asking?`, `Estimate due within 3 business days of your request`]].map(([e, t]) => <div className="rounded-2xl bg-white p-4 shadow-card" key={e}>
                <div className="font-display text-lg font-bold text-brand-700">{e}</div>
                <p className="!mt-1 text-sm">{t}</p>
              </div>)}
          </div>
          <CU tone="sun" title="If your bill is $400+ more than the estimate">
            You can dispute it through the federal <b>patient-provider dispute resolution</b> process. You generally
            must start within <b>120 calendar days</b> of receiving the bill, and there’s a small administrative fee
            ($25). Keep a copy of your Good Faith Estimate.
          </CU>
          <p>
            Insured patients: a separate “Advanced Explanation of Benefits” requirement is in the law, but federal
            agencies have delayed enforcing it — so for now, ask your insurer and the facility for a written estimate.
          </p>
        </Cg>
        <Cg id="bills" icon={Gavel} eyebrow="Practical steps" title="If a medical bill looks wrong">
          <ol className="mt-4 space-y-3">
            {[[`Don’t pay yet — compare the bill to your EOB.`, `Your insurer’s Explanation of Benefits shows the allowed amount and what you owe. The provider’s bill should match.`], [`Ask for an itemized bill.`, `Check for duplicate charges, services you didn’t receive, or the wrong CPT code.`], [`Call your insurer.`, `Ask them to reprocess denied or incorrectly processed claims. File a written appeal if needed.`], [`Ask about financial assistance.`, `Nonprofit hospitals must have a written financial-assistance (charity care) policy. Many offer discounts well above the poverty level.`], [`Report possible violations.`, `Call the No Surprises Help Desk at 1-800-985-3059 or submit a complaint online.`]].map(([e, t], n) => <li className="flex gap-4 rounded-2xl border border-line bg-white p-4" key={e}>
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-mint-600 text-sm font-bold text-white">
                  {n + 1}
                </span>
                <span>
                  <b className="text-ink">{e}</b>
                  <span className="mt-0.5 block text-sm text-ink-soft">{t}</span>
                </span>
              </li>)}
          </ol>
          <div className="mt-6 flex flex-wrap gap-3">
            <a className="btn-primary" href="tel:18009853059">
              <Phone className="h-4 w-4" /> No Surprises Help Desk: 1-800-985-3059
            </a>
            <a className="btn-ghost" href="https://www.cms.gov/medical-bill-rights" target="_blank" rel="noreferrer">
              CMS: Medical bill rights <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        </Cg>
        <div className="my-12 flex flex-col items-start justify-between gap-4 rounded-3xl bg-brand-800 p-7 text-white sm:flex-row sm:items-center">
          <div>
            <div className="flex items-center gap-2 text-mint-200">
              <BadgeDollarSign className="h-5 w-5" />
              <span className="text-xs font-bold uppercase tracking-[0.14em]">Put it into practice</span>
            </div>
            <h2 className="mt-1 text-2xl font-bold">Compare imaging prices before you book</h2>
          </div>
          <Link to="/" className="btn-cta shrink-0">
            Start comparing <ArrowRight className="h-5 w-5" />
          </Link>
        </div>
        <p className="mb-12 flex gap-2 text-xs text-ink-mute">
          <TriangleAlert className="h-4 w-4 shrink-0" />
          This page summarizes federal rules for education and is not legal advice. Rules can change — check CMS.gov for
          the latest. State laws may add protections.
        </p>
      </div>
    </Fragment>;
}
export default v
