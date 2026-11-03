import { Link } from 'react-router-dom'
import { ArrowRight, Bug, Code2, Handshake, Megaphone, Star } from 'lucide-react'
import { PageHero, usePageTitle } from './ui'
import { CONTACT, GITHUB } from './SiteLayout'

const TEAM = [
  ['HP', 'Harshu Pande', 'Founder', 'Second-year medical student at Saint Louis University School of Medicine, with an undergraduate degree in public health from Saint Louis University.'],
  ['SJ', 'Seyun Jeong', 'Co-founder', 'PhD student in Health Outcomes Research at Saint Louis University School of Medicine.'],
]

const BELIEFS = [
  ['Prices are public, so the tools should be too.', 'Insurers are required to publish these rates. Making them usable should not cost a five-figure license.'],
  ['Patients come first.', 'The hardest question is the simplest one: what will this cost me, and where? Every other feature serves that answer.'],
  ['Show the work.', 'Open code, raw values beside cleaned ones, and limitations written down. If a number is wrong, anyone can find out why.'],
  ['Collect nothing.', 'The personal parts of a price check happen on your device. We would rather not hold data than promise to guard it.'],
]

const HELP = [
  [Megaphone, 'Share it', 'Tell a patient, a clinician, a benefits team or a reporter who could use it.'],
  [Star, 'Star the repository', 'It helps others find the project and tells us it is useful.', GITHUB],
  [Bug, 'Report a wrong number', 'Open an issue with a link to the page. Bad data is the enemy, and we fix it fast.', CONTACT],
  [Code2, 'Contribute', 'Parsers, payer playbooks, design and writing are all open for contributions.', GITHUB],
  [Handshake, 'Partner with us', 'Universities, newsrooms, employers and patient advocates: we would love to work together.', CONTACT],
]

export default function About() {
  usePageTitle('About')
  return (
    <>
      <PageHero kicker="About RateCommons" title="Health care prices, made usable by everyone."
        lead="RateCommons is a free, independent project started in St. Louis. We turn the price files insurers are required to publish into tools anyone can use, from a patient comparing MRI prices to a researcher studying a whole market." />

      <section className="wrap grid gap-10 py-16 lg:grid-cols-[1.1fr_1fr]">
        <div className="prose-site">
          <h2 className="!mt-0">Why we built it</h2>
          <p>Since 2022, health insurers have published what they pay doctors and hospitals. The files are enormous, inconsistent and almost impossible to read without specialist software, and most of that software is sold to the industry, not given to the public.</p>
          <p>We saw the gap from inside medicine and public health: patients facing bills they could not predict, clinicians who wanted to refer people to fair-priced care but had no way to check, and researchers paying for access to data that is public by law.</p>
          <p>RateCommons is our answer: the same capabilities the paid platforms offer, free, and a patient tool simple enough to use the night before an appointment.</p>
        </div>
        <div className="grid content-start gap-4">
          {BELIEFS.map(([t, d]) => (
            <div key={t} className="rounded-2xl bg-white p-5 shadow-[inset_0_0_0_1px_#dce3e0]">
              <p className="font-bold text-ink">{t}</p>
              <p className="mt-1 text-[15px] leading-relaxed text-ink-soft">{d}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="border-y border-line bg-white">
        <div className="wrap py-16">
          <p className="kicker">The team</p>
          <h2 className="h-section mt-2">Founders</h2>
          <div className="mt-8 grid gap-6 md:grid-cols-2">
            {TEAM.map(([init, name, role, bio]) => (
              <div key={name} className="card flex gap-5 p-6">
                <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-night font-display text-xl font-bold text-sea" aria-hidden="true">{init}</span>
                <div>
                  <p className="text-xl font-bold text-ink">{name}</p>
                  <p className="text-sm font-semibold text-brand-700">{role}</p>
                  <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">{bio}</p>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-ink-mute">RateCommons is not affiliated with or endorsed by Saint Louis University, any insurer or any government agency.</p>
        </div>
      </section>

      <section className="wrap py-16">
        <p className="kicker">Support our work</p>
        <h2 className="h-section mt-2">Help us make prices usable</h2>
        <p className="lead mt-3 max-w-2xl">We don't take donations right now. The best support is using RateCommons, telling people about it, and helping us make it better.</p>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {HELP.map(([Icon, t, d, href]) => {
            const inner = (
              <>
                <Icon className="h-6 w-6 text-brand-600" aria-hidden="true" />
                <p className="mt-3 font-bold text-ink">{t}</p>
                <p className="mt-1 text-[14px] leading-relaxed text-ink-soft">{d}</p>
              </>
            )
            return href
              ? <a key={t} href={href} target="_blank" rel="noreferrer" className="card p-5 transition hover:border-brand-300">{inner}</a>
              : <div key={t} className="card p-5">{inner}</div>
          })}
        </div>
        <div className="mt-10 flex flex-wrap items-center justify-between gap-4 rounded-3xl bg-night px-7 py-6 text-white">
          <p className="text-lg"><b>Get in touch.</b> <span className="text-night-text">Questions, partnerships or press: open a GitHub issue and we'll reply there.</span></p>
          <a href={CONTACT} target="_blank" rel="noreferrer" className="btn-sea">Contact us <ArrowRight className="h-4 w-4" /></a>
        </div>
        <p className="mt-8 text-center text-[15px] text-ink-soft">
          Curious how it works? Read the <Link to="/methodology" className="font-semibold text-brand-700 underline decoration-brand-200 underline-offset-2">methodology</Link>.
        </p>
      </section>
    </>
  )
}
