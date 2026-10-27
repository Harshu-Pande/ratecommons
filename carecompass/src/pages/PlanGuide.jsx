import { Fragment, useMemo, useState } from 'react'
import { ArrowRight, Award, Briefcase, Building, CircleCheck, ExternalLink, HeartPulse, Info, Landmark, ShieldPlus, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import InfoTip from '../components/InfoTip'
import { moneyRound } from '../lib/format'

var T = e => 15960 + 5680 * Math.max(0, e - 1),
  E = [{
    key: `pcp`,
    label: `Primary care visits`,
    unit: `visits / yr`,
    price: 135,
    copay: `pcp`,
    max: 24
  }, {
    key: `spec`,
    label: `Specialist visits`,
    unit: `visits / yr`,
    price: 230,
    copay: `spec`,
    max: 40
  }, {
    key: `uc`,
    label: `Urgent care visits`,
    unit: `visits / yr`,
    price: 180,
    copay: `uc`,
    max: 12
  }, {
    key: `er`,
    label: `Emergency room visits`,
    unit: `visits / yr`,
    price: 2400,
    copay: `er`,
    max: 6
  }, {
    key: `generic`,
    label: `Generic prescriptions`,
    unit: `fills / month`,
    price: 15,
    copay: `generic`,
    perMonth: !0,
    max: 10
  }, {
    key: `brand`,
    label: `Brand-name prescriptions`,
    unit: `fills / month`,
    price: 500,
    copay: `brand`,
    perMonth: !0,
    max: 6
  }, {
    key: `labs`,
    label: `Lab work (blood tests)`,
    unit: `times / yr`,
    price: 90,
    copay: null,
    max: 24
  }, {
    key: `imaging`,
    label: `MRI / CT scans`,
    unit: `scans / yr`,
    price: 900,
    copay: null,
    max: 8
  }, {
    key: `therapy`,
    label: `Therapy (PT or mental health)`,
    unit: `sessions / yr`,
    price: 140,
    copay: `spec`,
    max: 60
  }],
  D = [{
    key: `specialty`,
    label: `Specialty drug (e.g., biologic for arthritis/Crohn’s, MS)`,
    price: 6e4
  }, {
    key: `surgery`,
    label: `Planned outpatient surgery/procedure`,
    price: 9e3
  }, {
    key: `admit`,
    label: `Likely hospital stay`,
    price: 22e3
  }, {
    key: `baby`,
    label: `Having a baby this year`,
    price: 14e3
  }],
  O = {
    light: {
      label: `Rarely go to the doctor`,
      usage: {
        pcp: 1,
        spec: 0,
        uc: 1,
        er: 0,
        generic: 0,
        brand: 0,
        labs: 1,
        imaging: 0,
        therapy: 0
      },
      events: {}
    },
    chronic: {
      label: `Managing a chronic condition`,
      usage: {
        pcp: 4,
        spec: 6,
        uc: 1,
        er: 1,
        generic: 2,
        brand: 1,
        labs: 4,
        imaging: 1,
        therapy: 0
      },
      events: {}
    },
    baby: {
      label: `Planning a baby`,
      usage: {
        pcp: 2,
        spec: 12,
        uc: 0,
        er: 0,
        generic: 1,
        brand: 0,
        labs: 5,
        imaging: 0,
        therapy: 0
      },
      events: {
        baby: !0
      }
    },
    surgery: {
      label: `Surgery coming up`,
      usage: {
        pcp: 2,
        spec: 5,
        uc: 0,
        er: 0,
        generic: 1,
        brand: 0,
        labs: 3,
        imaging: 2,
        therapy: 12
      },
      events: {
        surgery: !0
      }
    }
  },
  k = {
    employer: [{
      id: `hmo`,
      name: `HMO / EPO`,
      tag: `Low deductible · in-network only`,
      premium: 125,
      deductible: 750,
      coins: 20,
      oopMax: 4e3,
      copays: {
        pcp: 25,
        spec: 50,
        uc: 50,
        er: 300,
        generic: 10,
        brand: 45
      },
      hsa: !1,
      hsaSeed: 0,
      oon: !1
    }, {
      id: `ppo`,
      name: `PPO`,
      tag: `Flexible network · out-of-network coverage`,
      premium: 190,
      deductible: 1500,
      coins: 20,
      oopMax: 5500,
      copays: {
        pcp: 30,
        spec: 60,
        uc: 60,
        er: 350,
        generic: 10,
        brand: 50
      },
      hsa: !1,
      hsaSeed: 0,
      oon: !0
    }, {
      id: `hdhp`,
      name: `HDHP + HSA`,
      tag: `Lowest premium · tax-free savings account`,
      premium: 70,
      deductible: 3e3,
      coins: 10,
      oopMax: 6e3,
      copays: {},
      hsa: !0,
      hsaSeed: 500,
      oon: !0
    }],
    marketplace: [{
      id: `bronze`,
      name: `Bronze (HSA-eligible)`,
      tag: `Lowest premium · highest deductible`,
      premium: 320,
      deductible: 7500,
      coins: 40,
      oopMax: 1e4,
      copays: {},
      hsa: !0,
      hsaSeed: 0,
      oon: !1
    }, {
      id: `silver`,
      name: `Silver`,
      tag: `Extra savings if income ≤ 250% FPL`,
      premium: 460,
      deductible: 5300,
      coins: 30,
      oopMax: 9200,
      copays: {
        pcp: 40,
        spec: 80,
        uc: 75,
        generic: 15,
        brand: 60
      },
      hsa: !1,
      hsaSeed: 0,
      oon: !1
    }, {
      id: `gold`,
      name: `Gold`,
      tag: `Higher premium · lower deductible`,
      premium: 560,
      deductible: 1500,
      coins: 20,
      oopMax: 7500,
      copays: {
        pcp: 25,
        spec: 50,
        uc: 50,
        er: 400,
        generic: 10,
        brand: 45
      },
      hsa: !1,
      hsaSeed: 0,
      oon: !1
    }]
  };
function A(e, t) {
  let n = 0,
    r = [];
  for (let t of E) {
    let i = (+e[t.key] || 0) * (t.perMonth ? 12 : 1);
    i && (r.push({
      ...t,
      units: i,
      cost: i * t.price
    }), n += i * t.price);
  }
  for (let e of D) t[e.key] && (r.push({
    ...e,
    units: 1,
    cost: e.price,
    event: !0
  }), n += e.price);
  return {
    total: n,
    items: r
  };
}
function j(e, t, n, r = 0.22) {
  let {
      items: i
    } = A(t, n),
    a = 0,
    o = 0;
  for (let t of i) {
    let n = !e.hsa && t.copay ? e.copays?.[t.copay] : void 0;
    n != null && n !== `` ? a += Math.min(+n, t.price) * t.units : o += t.cost;
  }
  let s = +e.deductible || 0,
    c = (+e.coins || 0) / 100,
    l = Math.min(o, s) + Math.max(0, o - s) * c,
    u = Math.min(a + l, +e.oopMax || 1 / 0),
    d = (+e.premium || 0) * 12,
    f = e.hsa && +e.hsaSeed || 0,
    p = e.hsa ? Math.min(Math.max(0, u - f), 4400 - f) * r : 0,
    m = d + u - Math.min(f, u) - p,
    h = d + (+e.oopMax || 0) - f;
  return {
    premium: d,
    oop: u,
    seed: Math.min(f, u),
    taxSavings: p,
    net: m,
    worst: h
  };
}
function M({
  age: e,
  household: t,
  income: n,
  employer: r,
  disability: i,
  pregnant: a
}) {
  let o = T(t || 1),
    s = n > 0 ? n / o * 100 : 0,
    c = {
      pct: Math.round(s),
      fpl: o,
      key: `marketplace`,
      notes: []
    };
  return e >= 65 || i ? (c.key = `medicare`, s <= 138 && c.notes.push(`Your income may also qualify you for help from MO HealthNet or a Medicare Savings Program (“dual eligible”). Ask Missouri SHIP.`), c) : s > 0 && s <= 138 ? (c.key = `medicaid`, c) : (a && s <= 200 && c.notes.push(`Pregnant Missourians can qualify for MO HealthNet at higher incomes than other adults — apply as soon as possible.`), r ? (c.key = `employer`, c) : (c.key = `marketplace`, s >= 100 && s <= 400 && c.notes.push(`At about ${Math.round(s)}% of the poverty level you should qualify for a premium tax credit that lowers your monthly premium.`), s > 400 && c.notes.push(`Above 400% of the poverty level you no longer qualify for premium tax credits in 2026 (the temporary enhanced credits expired after 2025), so compare full-price premiums carefully.`), s >= 100 && s <= 250 && c.notes.push(`Your income may qualify you for cost-sharing reductions — but only on SILVER plans. That can shrink a silver deductible dramatically.`), c));
}
var P = [{
    k: `employer`,
    icon: Briefcase,
    title: `Through a job`,
    text: `Employers usually pay a large share of the premium, so a job-based plan is often the best value. You typically choose between 2–4 plan designs once a year.`
  }, {
    k: `marketplace`,
    icon: Building,
    title: `HealthCare.gov Marketplace`,
    text: `For people without affordable job-based coverage. Premium tax credits are available at 100–400% of the federal poverty level. Open enrollment runs Nov 1 – Jan 15.`
  }, {
    k: `medicare`,
    icon: Landmark,
    title: `Medicare`,
    text: `For people 65+, or younger people with a qualifying disability, ALS or kidney failure. Choose Original Medicare (+ Medigap + Part D) or a Medicare Advantage plan.`
  }, {
    k: `medicaid`,
    icon: HeartPulse,
    title: `MO HealthNet (Medicaid)`,
    text: `Missouri covers adults 19–64 with income up to 138% of the poverty level, plus children, pregnant people and people with disabilities at other limits.`
  }, {
    k: `other`,
    icon: ShieldPlus,
    title: `Other options`,
    text: `VA health care and TRICARE for veterans/military families, COBRA to keep an old job’s plan, and staying on a parent’s plan until age 26.`
  }],
  F = [[`HMO`, `In-network only`, `Usually needed`, `None (except emergencies)`, `Lower`, `People who want low, predictable costs and are fine with a set network.`], [`EPO`, `In-network only`, `Usually not`, `None (except emergencies)`, `Low–moderate`, `People who want no referrals but can stay in-network.`], [`PPO`, `Large network`, `Not needed`, `Yes, at a higher cost`, `Higher`, `People who see many specialists or want to keep out-of-network doctors.`], [`POS`, `In-network + some out`, `Usually needed`, `Yes, at a higher cost`, `Moderate`, `A middle ground between HMO and PPO.`], [`HDHP + HSA`, `Any of the above`, `Depends`, `Depends`, `Lowest`, `Healthy people, or anyone who can save in a tax-free HSA to cover the higher deductible.`]];
function I() {
  return <Fragment>
      <section className="bg-gradient-to-b from-brand-800 to-brand-700 pb-16 pt-12 text-white">
        <div className="mx-auto max-w-5xl px-4 sm:px-6">
          <p className="text-xs font-bold uppercase tracking-[0.14em] text-mint-200">Education</p>
          <h1 className="mt-2 text-4xl font-extrabold sm:text-5xl">Choosing the right health plan</h1>
          <p className="mt-4 max-w-2xl text-lg text-brand-100">
            The “cheapest” plan isn’t the one with the lowest premium — it’s the one with the lowest{" "}
            <b className="text-white">total</b> cost for how you actually use care. Here’s how to figure that out.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            {[[`#sources`, `Where coverage comes from`], [`#types`, `Plan types`], [`#calculator`, `Plan-fit calculator`], [`#tips`, `Checklist`]].map(([e, t]) => <a href={e} className="rounded-full bg-white/10 px-4 py-2 text-sm font-medium ring-1 ring-white/20 hover:bg-white/20" key={e}>
                {t}
              </a>)}
          </div>
        </div>
      </section>
      <section id="sources" className="mx-auto max-w-5xl scroll-mt-20 px-4 py-14 sm:px-6">
        <p className="eyebrow">Step 1</p>
        <h2 className="mt-1 text-3xl font-bold">Where can you get coverage?</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {P.map(({
          k: e,
          icon: Ct,
          title: n,
          text: r
        }) => <div className="card p-5" key={e}>
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                <Ct className="h-5 w-5" />
              </span>
              <h3 className="mt-3 text-lg font-bold">{n}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">{r}</p>
            </div>)}
        </div>
      </section>
      <section id="types" className="scroll-mt-20 border-y border-line bg-white">
        <div className="mx-auto max-w-5xl px-4 py-14 sm:px-6">
          <p className="eyebrow">Step 2</p>
          <h2 className="mt-1 text-3xl font-bold">Plan types in plain English</h2>
          <div className="mt-6 overflow-x-auto rounded-2xl border border-line">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="bg-canvas text-left text-xs uppercase tracking-wide text-ink-mute">
                <tr>
                  {[`Type`, `Network`, `Referrals`, `Out-of-network`, `Premium`, `Often best for`].map(e => <th className="px-4 py-3 font-semibold" key={e}>
                      {e}
                    </th>)}
                </tr>
              </thead>
              <tbody>
                {F.map(e => <tr className="border-t border-line align-top" key={e[0]}>
                    {e.map((e, t) => <td className={`px-4 py-3 ${t === 0 ? `font-bold text-ink` : `text-ink-soft`}`} key={t}>
                        {e}
                      </td>)}
                  </tr>)}
              </tbody>
            </table>
          </div>
          <div className="mt-6 grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl bg-canvas p-5 text-sm leading-relaxed text-ink-soft">
              <h3 className="font-sans text-base font-bold text-ink">What’s an HSA?</h3>A Health Savings Account lets
              you set aside money <b>tax-free</b> for medical costs — and it’s yours to keep, even if you change jobs.
              For 2026 you can contribute up to <b>$4,400</b> (self) or <b>$8,750</b> (family), plus $1,000 if you’re
              55+. You need an HSA-eligible high-deductible plan (in 2026: deductible of at least $1,700 self / $3,400
              family). Starting in 2026, Marketplace <b>bronze and catastrophic</b> plans also qualify.
            </div>
            <div className="rounded-2xl bg-canvas p-5 text-sm leading-relaxed text-ink-soft">
              <h3 className="font-sans text-base font-bold text-ink">Medicare: two main paths</h3>
              <b>Original Medicare</b> (Parts A & B) lets you see any doctor who takes Medicare; add a <b>Medigap</b>{" "}
              policy and a <b>Part D</b> drug plan to limit costs. <b>Medicare Advantage</b> (Part C) bundles everything
              through a private plan with a network and a yearly out-of-pocket limit. In 2026, the Part B premium is{" "}
              <b>$202.90/month</b> and the Part B deductible is <b>$283</b>.
            </div>
          </div>
        </div>
      </section>
      <R />
      <section id="tips" className="mx-auto max-w-5xl scroll-mt-20 px-4 pb-20 sm:px-6">
        <h2 className="text-3xl font-bold">Your plan-shopping checklist</h2>
        <div className="mt-6 grid gap-3 md:grid-cols-2">
          {[`Check that your doctors, hospitals and pharmacy are in-network (use the insurer’s provider search, then call to confirm).`, `Look up each of your medications on the plan’s formulary — note the tier and any prior authorization.`, `Add up: 12 × premium + your likely out-of-pocket costs. Then look at the out-of-pocket max as your “bad year” number.`, `If you choose a high-deductible plan, open an HSA and set money aside every paycheck.`, `Preventive care (annual physical, screenings, most vaccines) is free on ACA-compliant plans — even before the deductible.`, `Life changes (new job, marriage, baby, moving, losing coverage) open a Special Enrollment Period — usually 60 days.`].map(e => <div className="flex gap-3 rounded-2xl border border-line bg-white p-4 text-sm text-ink-soft" key={e}>
              <CircleCheck className="mt-0.5 h-5 w-5 shrink-0 text-mint-600" />
              {e}
            </div>)}
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          <a className="btn-ghost" href="https://www.healthcare.gov/" target="_blank" rel="noreferrer">
            HealthCare.gov <ExternalLink className="h-3.5 w-3.5" />
          </a>
          <a className="btn-ghost" href="https://www.medicare.gov/plan-compare/" target="_blank" rel="noreferrer">
            Medicare Plan Finder <ExternalLink className="h-3.5 w-3.5" />
          </a>
          <a className="btn-ghost" href="https://mydss.mo.gov/healthcare" target="_blank" rel="noreferrer">
            MO HealthNet <ExternalLink className="h-3.5 w-3.5" />
          </a>
          <a className="btn-ghost" href="https://www.missouriship.org/" target="_blank" rel="noreferrer">
            Missouri SHIP (free Medicare help) <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
      </section>
    </Fragment>;
}
function L({
  value: e,
  onChange: t,
  max: n = 99,
  label: r
}) {
  return <div className="flex items-center gap-1">
      <button type="button" aria-label={`Decrease ${r}`} onClick={() => t(Math.max(0, (+e || 0) - 1))} className="h-9 w-9 rounded-lg border border-line bg-white text-lg font-semibold text-ink-soft hover:border-brand-300">
        −
      </button>
      <input aria-label={r} inputMode="numeric" value={e} onChange={e => t(Math.min(n, +e.target.value.replace(/\D/g, ``) || 0))} className="h-9 w-12 rounded-lg border border-line text-center text-sm font-semibold" />
      <button type="button" aria-label={`Increase ${r}`} onClick={() => t(Math.min(n, (+e || 0) + 1))} className="h-9 w-9 rounded-lg border border-line bg-white text-lg font-semibold text-ink-soft hover:border-brand-300">
        +
      </button>
    </div>;
}
function R() {
  let [e, t] = useState({
      age: 30,
      household: 1,
      income: 55e3,
      employer: !0,
      disability: !1,
      pregnant: !1
    }),
    [n, r] = useState(O.chronic.usage),
    [o, s] = useState({}),
    [c, u] = useState({
      oon: !1,
      predictable: !1,
      save: !0
    }),
    f = useMemo(() => M(e), [e]),
    m = f.key === `marketplace` ? `marketplace` : `employer`,
    [h, g] = useState(k),
    _ = h[m],
    v = useMemo(() => A(n, o), [n, o]),
    b = useMemo(() => _.map(e => ({
      plan: e,
      c: j(e, n, o)
    })), [_, n, o]),
    x = useMemo(() => {
      let e = [...b].sort((e, t) => e.c.net - t.c.net),
        t = e[0],
        n = [];
      if (c.oon) {
        let r = e.find(e => e.plan.oon && !e.plan.hsa) || e.find(e => e.plan.oon);
        r && r !== t && (n.push(`You want out-of-network flexibility, so we favor the ${r.plan.name} even though it costs about ${moneyRound(r.c.net - t.c.net)} more in a typical year.`), t = r);
      }
      if (c.predictable && !c.oon) {
        let e = [...b].sort((e, t) => e.c.worst - t.c.worst)[0];
        e !== t && e.c.net - t.c.net < 600 && (n.push(`You prefer predictability: the ${e.plan.name} caps your “bad year” at ${moneyRound(e.c.worst)} for only ~${moneyRound(e.c.net - t.c.net)} more on average.`), t = e);
      }
      return t.plan.hsa && !c.save && n.push(`Heads-up: this plan works best if you can put money into the HSA. If you can’t, a sudden bill before the deductible is met could be hard to cover.`), n.length || n.push(`Based on the care you expect, the ${t.plan.name} has the lowest total yearly cost (premiums + what you pay for care).`), v.total < 2e3 && t.plan.hsa && n.push(`You use relatively little care, so a lower premium usually beats a lower deductible.`), v.total > 15e3 && n.push(`You expect a lot of care this year, so you will likely hit the out-of-pocket maximum — compare plans by premium + out-of-pocket max.`), {
        best: t,
        why: n
      };
    }, [b, c, v.total]),
    S = Math.max(...b.map(e => e.c.worst), 1),
    P = (e, t, n) => g(r => ({
      ...r,
      [m]: r[m].map(r => r.id === e ? {
        ...r,
        [t]: n
      } : r)
    }));
  return <section id="calculator" className="scroll-mt-20 bg-canvas">
      <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <p className="eyebrow">Step 3 · Interactive</p>
        <h2 className="mt-1 text-3xl font-bold">Plan-fit calculator</h2>
        <p className="mt-2 max-w-3xl text-ink-soft">
          Tell us a little about yourself and how you use care. We’ll point you to the right coverage path and compare
          plan designs by <b>total yearly cost</b>. Nothing you enter leaves this page.
        </p>
        <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_1.15fr]">
          <div className="space-y-6">
            <div className="card p-5">
              <h3 className="flex items-center gap-2 font-sans text-base font-bold">
                <Users className="h-5 w-5 text-brand-600" /> About you
              </h3>
              <div className="mt-4 grid grid-cols-2 gap-4">
                <label className="text-sm font-medium">
                  Age
                  <input inputMode="numeric" value={e.age} onChange={n => t({
                  ...e,
                  age: +n.target.value.replace(/\D/g, ``) || 0
                })} className="field mt-1 w-full" />
                </label>
                <label className="text-sm font-medium">
                  People in household
                  <input inputMode="numeric" value={e.household} onChange={n => t({
                  ...e,
                  household: Math.max(1, +n.target.value.replace(/\D/g, ``) || 1)
                })} className="field mt-1 w-full" />
                </label>
                <label className="col-span-2 text-sm font-medium">
                  Yearly household income
                  <div className="relative mt-1">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-mute">$</span>
                    <input inputMode="numeric" value={e.income.toLocaleString()} onChange={n => t({
                    ...e,
                    income: +n.target.value.replace(/\D/g, ``) || 0
                  })} className="field w-full pl-7" />
                  </div>
                  <span className="mt-1 block text-xs font-normal text-ink-mute">
                    ≈ {f.pct}% of the 2026 federal poverty level ({moneyRound(T(e.household))} for {e.household})
                  </span>
                </label>
              </div>
              <div className="mt-4 space-y-2">
                {[[`employer`, `An employer (mine or a family member’s) offers me health insurance`], [`disability`, `I receive Social Security disability, or have kidney failure/ALS`], [`pregnant`, `I’m pregnant`]].map(([n, r]) => <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-white p-3 text-sm hover:border-brand-200" key={n}>
                    <input type="checkbox" checked={e[n]} onChange={r => t({
                  ...e,
                  [n]: r.target.checked
                })} className="mt-0.5 h-4 w-4 accent-brand-600" />
                    {r}
                  </label>)}
              </div>
            </div>
            <div className="card p-5">
              <h3 className="flex items-center gap-2 font-sans text-base font-bold">
                <HeartPulse className="h-5 w-5 text-brand-600" /> How you use care in a typical year
              </h3>
              <div className="mt-3 flex flex-wrap gap-2">
                {Object.entries(O).map(([e, t]) => <button type="button" onClick={() => {
                r(t.usage), s(t.events);
              }} className="rounded-full border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink-soft hover:border-brand-300 hover:text-brand-700" key={e}>
                    {t.label}
                  </button>)}
              </div>
              <div className="mt-4 divide-y divide-line">
                {E.map(e => <div className="flex items-center justify-between gap-3 py-2.5" key={e.key}>
                    <div>
                      <div className="text-sm font-medium">{e.label}</div>
                      <div className="text-xs text-ink-mute">
                        {e.unit} · ~{moneyRound(e.price)} each
                      </div>
                    </div>
                    <L label={e.label} value={n[e.key] || 0} max={e.max} onChange={t => r({
                  ...n,
                  [e.key]: t
                })} />
                  </div>)}
              </div>
              <div className="mt-3 space-y-2">
                {D.map(e => <label className="flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-line bg-white p-3 text-sm hover:border-brand-200" key={e.key}>
                    <span className="flex items-center gap-3">
                      <input type="checkbox" checked={!!o[e.key]} onChange={t => s({
                    ...o,
                    [e.key]: t.target.checked
                  })} className="h-4 w-4 accent-brand-600" />
                      {e.label}
                    </span>
                    <span className="text-xs text-ink-mute">~{moneyRound(e.price)}</span>
                  </label>)}
              </div>
            </div>
            <div className="card p-5">
              <h3 className="font-sans text-base font-bold">What matters to you?</h3>
              <div className="mt-3 space-y-2">
                {[[`oon`, `I need to keep a doctor who may be out-of-network`], [`predictable`, `I’d pay a bit more for predictable costs`], [`save`, `I can set aside money in a savings account (HSA)`]].map(([e, t]) => <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-white p-3 text-sm hover:border-brand-200" key={e}>
                    <input type="checkbox" checked={c[e]} onChange={t => u({
                  ...c,
                  [e]: t.target.checked
                })} className="mt-0.5 h-4 w-4 accent-brand-600" />
                    {t}
                  </label>)}
              </div>
            </div>
          </div>
          <div className="space-y-6 lg:sticky lg:top-20 lg:self-start">
            <Cz path={f} />
            {(f.key === `employer` || f.key === `marketplace`) && <div className="card overflow-hidden">
                <div className="bg-ink p-5 text-white">
                  <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.14em] text-mint-200">
                    <Award className="h-4 w-4" /> Best fit for you
                  </div>
                  <div className="mt-1 font-display text-2xl font-extrabold">{x.best.plan.name}</div>
                  <div className="mt-1 text-sm text-white/70">
                    Estimated total for the year: <b className="text-white">{moneyRound(x.best.c.net)}</b> · worst case{" "}
                    {moneyRound(x.best.c.worst)}
                  </div>
                  <ul className="mt-3 space-y-1.5 text-sm text-white/85">
                    {x.why.map(e => <li className="flex gap-2" key={e}>
                        <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-mint-200" />
                        {e}
                      </li>)}
                  </ul>
                </div>
                <div className="p-5">
                  <div className="flex items-baseline justify-between">
                    <h3 className="font-sans text-base font-bold">Total yearly cost by plan</h3>
                    <span className="text-xs text-ink-mute">Care you expect: ~{moneyRound(v.total)}</span>
                  </div>
                  <div className="mt-4 space-y-4">
                    {b.map(({
                  plan: e,
                  c: t
                }) => <div key={e.id}>
                        <div className="flex items-baseline justify-between text-sm">
                          <span className="font-semibold">
                            {e.name}
                            {e.id === x.best.plan.id && <span className="chip ml-2 bg-mint-50 text-mint-700">Best fit</span>}
                          </span>
                          <span className="font-display text-lg font-extrabold">{moneyRound(t.net)}</span>
                        </div>
                        <div className="relative mt-1.5 h-5 rounded-md bg-canvas">
                          <div className="absolute inset-0 flex overflow-hidden rounded-md">
                            <div className="bg-brand-600" style={{
                        width: `${t.premium / S * 100}%`
                      }} title={`Premiums ${moneyRound(t.premium)}`} />
                            <div className="bg-sun-400" style={{
                        width: `${Math.max(0, t.oop - t.seed - t.taxSavings) / S * 100}%`
                      }} title={`Out of pocket ${moneyRound(t.oop)}`} />
                          </div>
                          <div className="absolute -top-1 h-7 w-0.5 bg-ink" style={{
                      left: `${t.worst / S * 100}%`
                    }} title={`Worst case ${moneyRound(t.worst)}`} />
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-ink-mute">
                          <span>Premiums {moneyRound(t.premium)}</span>
                          <span>Out-of-pocket {moneyRound(t.oop)}</span>
                          {t.seed > 0 && <span className="text-mint-700">− employer HSA {moneyRound(t.seed)}</span>}
                          {t.taxSavings > 0 && <span className="text-mint-700">− HSA tax savings ~{moneyRound(t.taxSavings)}</span>}
                        </div>
                      </div>)}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-4 text-xs text-ink-mute">
                    <span className="flex items-center gap-1.5">
                      <span className="h-2.5 w-4 rounded-sm bg-brand-600" />
                      Premiums
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="h-2.5 w-4 rounded-sm bg-sun-400" />
                      Your out-of-pocket (after HSA help)
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="h-3 w-0.5 bg-ink" />
                      Worst case (hit out-of-pocket max)
                    </span>
                  </div>
                </div>
              </div>}
          </div>
        </div>
        {(f.key === `employer` || f.key === `marketplace`) && <div className="mt-8">
            <h3 className="text-xl font-bold">
              Compare your real options{" "}
              <span className="text-sm font-normal text-ink-mute">— edit these to match the plans you’re offered</span>
            </h3>
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              {_.map(e => <div className={`card p-4 ${e.id === x.best.plan.id ? `ring-2 ring-mint-500` : ``}`} key={e.id}>
                  <div className="font-bold">{e.name}</div>
                  <div className="text-xs text-ink-mute">{e.tag}</div>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {[[`premium`, `Premium / mo`, `$`, null], [`deductible`, `Deductible`, `$`, `deductible`], [`coins`, `Coinsurance`, `%`, `coinsurance`], [`oopMax`, `Out-of-pocket max`, `$`, `oopMax`]].map(([t, n, r, i]) => <label className="text-xs font-medium text-ink-soft" key={t}>
                        {n}
                        {i && <InfoTip k={i} />}
                        <input inputMode="numeric" value={e[t]} onChange={n => P(e.id, t, +n.target.value.replace(/\D/g, ``) || 0)} className="field mt-1 h-9 w-full text-sm" aria-label={`${e.name} ${n} (${r})`} />
                      </label>)}
                    {e.hsa && <label className="col-span-2 text-xs font-medium text-ink-soft">
                        Employer HSA contribution
                        <input inputMode="numeric" value={e.hsaSeed} onChange={t => P(e.id, `hsaSeed`, +t.target.value.replace(/\D/g, ``) || 0)} className="field mt-1 h-9 w-full text-sm" />
                      </label>}
                  </div>
                  {!e.hsa && Object.keys(e.copays).length > 0 && <p className="mt-2 text-xs text-ink-mute">
                      Copays:{" "}
                      {Object.entries(e.copays).map(([e, t]) => `${e.toUpperCase()} $${t}`).join(` · `)}
                    </p>}
                </div>)}
            </div>
            <p className="mt-4 flex gap-2 text-xs leading-relaxed text-ink-mute">
              <Info className="mt-0.5 h-4 w-4 shrink-0" />
              Starting numbers are illustrative 2026-style designs for one person, not real quotes. Service prices are
              rough U.S. averages. Preventive care is free on ACA plans and is left out. HSA tax savings assume a 22%
              tax bracket. This is an educational estimate — not financial advice.
            </p>
          </div>}
      </div>
    </section>;
}
function Cz({
  path: e
}) {
  let t = {
      employer: {
        icon: Briefcase,
        title: `Start with your employer’s plans`,
        body: `Job-based coverage is usually your best value because the employer pays much of the premium. If the cheapest employee-only plan costs more than about 10% of household income, you may qualify for Marketplace help instead.`,
        link: null
      },
      marketplace: {
        icon: Building,
        title: `Shop the HealthCare.gov Marketplace`,
        body: `Compare bronze, silver and gold plans. Your age, county, household and income set your premium and any tax credit.`,
        link: [`https://www.healthcare.gov/`, `Go to HealthCare.gov`]
      },
      medicaid: {
        icon: HeartPulse,
        title: `You likely qualify for MO HealthNet (Medicaid)`,
        body: `Coverage has little or no premium and very low costs. Apply any time of year. Note: federal law adds work/community-engagement reporting for expansion adults (19–64) starting around the end of 2026, and eligibility checks every 6 months from 2027 — keep your contact info current.`,
        link: [`https://mydss.mo.gov/healthcare`, `Apply for MO HealthNet`]
      },
      medicare: {
        icon: Landmark,
        title: `Medicare is your main path`,
        body: `Compare Original Medicare + Medigap + Part D against Medicare Advantage plans during Open Enrollment (Oct 15 – Dec 7). Free, unbiased counseling is available from Missouri SHIP: 1-800-390-3330.`,
        link: [`https://www.medicare.gov/plan-compare/`, `Medicare Plan Finder`]
      }
    }[e.key],
    Cn = t.icon;
  return <div className="card p-5">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-white">
          <Cn className="h-5 w-5" />
        </span>
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.14em] text-brand-600">Your coverage path</p>
          <h3 className="mt-0.5 font-sans text-lg font-bold">{t.title}</h3>
          <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">{t.body}</p>
          {e.notes.map(e => <p className="mt-2 flex gap-2 rounded-lg bg-brand-50 p-2.5 text-xs leading-relaxed text-brand-800" key={e}>
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {e}
            </p>)}
          {t.link && <a href={t.link[0]} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-brand-600 hover:text-brand-800">
              {t.link[1]} <ArrowRight className="h-4 w-4" />
            </a>}
        </div>
      </div>
      {e.key === `medicare` && <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[420px] text-xs">
            <thead>
              <tr className="text-left text-ink-mute">
                <th className="py-1.5" />
                <th className="py-1.5 font-semibold">Original + Medigap + Part D</th>
                <th className="py-1.5 font-semibold">Medicare Advantage</th>
              </tr>
            </thead>
            <tbody className="text-ink-soft">
              {[[`Doctors`, `Any provider taking Medicare`, `Plan network (HMO/PPO)`], [`Monthly cost`, `Part B + Medigap + Part D premiums`, `Part B premium; plan premium often $0`], [`Yearly cap`, `None without Medigap`, `Built-in out-of-pocket limit`], [`Extras`, `Rarely`, `Often dental/vision/hearing`], [`Prior auth`, `Rare`, `More common`]].map(e => <tr className="border-t border-line" key={e[0]}>
                  <td className="py-1.5 font-semibold text-ink">{e[0]}</td>
                  <td className="py-1.5 pr-2">{e[1]}</td>
                  <td className="py-1.5">{e[2]}</td>
                </tr>)}
            </tbody>
          </table>
        </div>}
      <p className="mt-4 text-xs text-ink-mute">
        Need imaging soon?{" "}
        <Link to="/" className="font-semibold text-brand-600 underline">
          Compare prices near you
        </Link>
        .
      </p>
    </div>;
}
export default I
