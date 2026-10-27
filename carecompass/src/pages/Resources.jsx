import { Fragment } from 'react'
import { ExternalLink, HandCoins, HeartHandshake, Landmark, Lightbulb, Pill, Scale } from 'lucide-react'

var m = [{
    icon: Pill,
    title: `Save on prescriptions`,
    items: [[`Mark Cuban Cost Plus Drug Company`, `https://www.costplusdrugs.com/`, `Transparent pricing: manufacturer cost + 15% markup + pharmacy fee. Mail-order and partner pharmacies.`], [`GoodRx`, `https://www.goodrx.com/`, `Free discount coupons at most U.S. pharmacies. Compare cash prices — sometimes lower than your copay.`], [`SingleCare`, `https://www.singlecare.com/`, `Another free prescription discount card to compare against GoodRx.`], [`NeedyMeds`, `https://www.needymeds.org/`, `Nonprofit database of patient-assistance programs, copay cards and free/low-cost clinics.`], [`Medicine Assistance Tool`, `https://medicineassistancetool.org/`, `Search manufacturer assistance programs for brand-name medicines.`], [`RxAssist`, `https://www.rxassist.org/`, `Directory of pharmaceutical company patient-assistance programs.`]]
  }, {
    icon: Scale,
    title: `Compare & understand prices`,
    items: [[`FAIR Health Consumer`, `https://www.fairhealthconsumer.org/`, `Free, independent estimates of typical costs for medical and dental procedures in your area.`], [`Your insurer’s cost estimator`, `https://www.uhc.com/`, `Plans must offer a member price-comparison tool. Log in to see estimates based on your own benefits.`], [`CMS: Medical bill rights`, `https://www.cms.gov/medical-bill-rights`, `Official information on the No Surprises Act, Good Faith Estimates and how to file a complaint.`]]
  }, {
    icon: Landmark,
    title: `Get covered`,
    items: [[`HealthCare.gov`, `https://www.healthcare.gov/`, `The federal Marketplace used by Missouri residents. Check if you qualify for lower premiums.`], [`MO HealthNet (Missouri Medicaid)`, `https://mydss.mo.gov/healthcare`, `Apply online, by phone, or in person for Missouri Medicaid and CHIP.`], [`Medicare Plan Finder`, `https://www.medicare.gov/plan-compare/`, `Compare Medicare Advantage and Part D drug plans by your medications and pharmacies.`], [`Missouri SHIP · 1-800-390-3330`, `https://www.missouriship.org/`, `Free, unbiased one-on-one Medicare counseling for Missourians.`], [`Find a Health Center (HRSA)`, `https://findahealthcenter.hrsa.gov/`, `Community health centers charge on a sliding scale based on income — insured or not.`]]
  }, {
    icon: HeartHandshake,
    title: `Help with medical bills & debt`,
    items: [[`Dollar For`, `https://dollarfor.org/`, `Nonprofit that helps patients apply for hospital charity care and get bills reduced or forgiven.`], [`Patient Advocate Foundation`, `https://www.patientadvocate.org/`, `Free case management for insurance denials, medical debt and access-to-care problems.`], [`Undue Medical Debt`, `https://unduemedicaldebt.org/`, `Buys and forgives medical debt for people with low incomes.`], [`CFPB: Medical debt`, `https://www.consumerfinance.gov/consumer-tools/medical-debt/`, `Your rights with debt collectors and credit reports.`]]
  }],
  h = [`Ask for generics or a lower-tier alternative — your doctor can often switch to an equally effective, cheaper option.`, `Compare a discount-card cash price with your insurance copay. If you pay cash, it may not count toward your deductible — ask.`, `Use 90-day supplies and mail order for maintenance drugs.`, `Schedule non-urgent imaging at a freestanding imaging center: they’re often cheaper than hospital outpatient departments.`, `Check if a test is preventive (free) or diagnostic (subject to deductible) before your visit.`, `Always request an itemized bill and compare it with your EOB.`];
function g() {
  return <Fragment>
      <section className="bg-gradient-to-b from-brand-800 to-brand-700 pb-14 pt-12 text-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <p className="text-xs font-bold uppercase tracking-[0.14em] text-mint-200">Savings resources</p>
          <h1 className="mt-2 text-4xl font-extrabold sm:text-5xl">Tools that lower what you pay</h1>
          <p className="mt-4 max-w-2xl text-lg text-brand-100">
            Trusted places to save on prescriptions, check fair prices, find coverage and get help with medical bills.
          </p>
        </div>
      </section>
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <div className="space-y-12">
          {m.map(({
          icon: Ce,
          title: t,
          items: r
        }) => <section key={t}>
              <h2 className="flex items-center gap-3 text-2xl font-bold">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                  <Ce className="h-5 w-5" />
                </span>
                {t}
              </h2>
              <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {r.map(([e, t, r]) => <a href={t} target="_blank" rel="noreferrer" className="card group flex flex-col p-5 transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-pop" key={e}>
                    <span className="flex items-start justify-between gap-2 font-semibold text-ink group-hover:text-brand-700">
                      {e}
                      <ExternalLink className="mt-1 h-4 w-4 shrink-0 text-ink-mute" />
                    </span>
                    <span className="mt-2 text-sm leading-relaxed text-ink-soft">{r}</span>
                    <span className="mt-3 text-xs text-ink-mute">{new URL(t).hostname.replace(`www.`, ``)}</span>
                  </a>)}
              </div>
            </section>)}
          <section className="rounded-3xl bg-white p-7 shadow-card">
            <h2 className="flex items-center gap-3 text-2xl font-bold">
              <Lightbulb className="h-6 w-6 text-sun-500" /> Quick money-saving tips
            </h2>
            <ul className="mt-5 grid gap-3 md:grid-cols-2">
              {h.map(e => <li className="flex gap-3 rounded-xl bg-canvas p-4 text-sm text-ink-soft" key={e}>
                  <HandCoins className="mt-0.5 h-5 w-5 shrink-0 text-mint-600" />
                  {e}
                </li>)}
            </ul>
          </section>
        </div>
        <p className="mt-10 text-xs text-ink-mute">
          CareCompass is independent and has no financial relationship with any organization listed. Links are provided
          for education.
        </p>
      </div>
    </Fragment>;
}
export default g
