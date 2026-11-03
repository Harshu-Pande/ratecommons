import { Link } from 'react-router-dom'
import { Ban, Cookie, EyeOff, HardDrive, Lock, UserX } from 'lucide-react'
import { PageHero, usePageTitle } from './ui'
import { CONTACT, GITHUB } from './SiteLayout'

const PROMISES = [
  [UserX, 'No accounts', 'There is nothing to sign up for, so there is no profile about you.'],
  [Cookie, 'No cookies or trackers', 'No advertising, no analytics scripts, no tracking pixels, no third-party fonts.'],
  [HardDrive, 'Plan details stay on your device', 'Your deductible, coinsurance and anything you type about your plan never leave your browser.'],
  [EyeOff, 'Card scans stay on your device', 'Text is read from a photo of your insurance card inside your browser. The photo is never uploaded.'],
  [Ban, 'Nothing to sell', 'We have no data about you to sell, share or hand over.'],
]

export default function Privacy() {
  usePageTitle('Privacy')
  return (
    <>
      <PageHero kicker="Privacy" title="We never receive your health information."
        lead="RateCommons is built so that the personal parts of a price check happen on your own device. Here is exactly what that means, including the few technical details a website cannot avoid." />

      <section className="wrap py-14">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {PROMISES.map(([Icon, t, d]) => (
            <div key={t} className="card p-5">
              <Icon className="h-6 w-6 text-brand-600" aria-hidden="true" />
              <p className="mt-3 font-bold text-ink">{t}</p>
              <p className="mt-1 text-[14px] leading-relaxed text-ink-soft">{d}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="wrap pb-20">
        <article className="prose-site max-w-3xl">
          <h2>What happens when you check a price</h2>
          <p>Prices are published in files grouped by service and area. When you search, your browser downloads the file for the service you picked and for the areas near you, identified by the first three digits of the ZIP code, and then finds and ranks places on your device. Your full ZIP code, your plan details and your estimate are worked out in your browser and are not sent to us.</p>
          <p>Plan details you enter are kept in your browser's session storage so they survive moving between pages. They are erased when you close the tab. You can also clear them at any time from the plan panel.</p>

          <h2>What a web server always sees</h2>
          <p>Like every website, ours has to receive a request to send a page back. Each request carries your IP address, your browser type and the address of the file asked for. Our host, Vercel, processes these requests and may keep short-lived technical logs for security and reliability. We do not add our own analytics, we do not combine these logs with anything else, and we do not use them to identify anyone.</p>
          <p>The Explorer and the AI connector send the arguments of each query (for example a billing code and a state) to our data service so it can run them. We do not log who asks what.</p>

          <h2>Other services the site uses</h2>
          <ul>
            <li><b>Vercel</b> hosts the site and data service.</li>
            <li><b>Hugging Face</b> stores the price files. Your browser gets them through our own domain, so Hugging Face does not see your visit.</li>
            <li><b>Map tiles</b> come from Esri. The map loads only when you choose to show it, and showing it sends the map area you are viewing to Esri.</li>
            <li><b>AI assistants</b> you connect, such as Claude or ChatGPT, handle your conversation under their own privacy policies. RateCommons receives only the tool requests your assistant makes.</li>
          </ul>

          <h2>About HIPAA</h2>
          <p>HIPAA is the federal law that protects health information held by health plans, health care providers and their business partners. RateCommons is none of these: we publish prices, we don't provide care or coverage, and we don't receive your health information at all. So HIPAA doesn't apply to us, and instead of relying on it, we designed the site so there is nothing to protect on our side.</p>
          <p>Please don't send us personal health information through GitHub issues or other channels. If you need help with a bill, the <Link to="/care/resources">help paying</Link> page lists free services that can take your details safely.</p>

          <h2>Children</h2>
          <p>RateCommons does not knowingly collect information from anyone, including children.</p>

          <h2>Changes and questions</h2>
          <p>If this page changes, the change will be visible in our public code history on <a href={GITHUB} target="_blank" rel="noreferrer">GitHub</a>. Questions about privacy: <a href={CONTACT} target="_blank" rel="noreferrer">open an issue</a>.</p>
          <p className="!mt-8 text-sm text-ink-mute"><Lock className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" />Last updated November 2, 2026.</p>
        </article>
      </div>
    </>
  )
}
