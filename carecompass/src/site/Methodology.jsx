import { Link } from 'react-router-dom'
import { PageHero, usePageTitle } from './ui'
import { GITHUB } from './SiteLayout'

const SECTIONS = [
  {
    id: 'source', title: 'Where the prices come from',
    body: (
      <>
        <p>Since 2022, the federal Transparency in Coverage rule (45 CFR 147.212) has required most employer and individual-market health plans to publish their in-network rates as machine-readable files. Each month, insurers post a table of contents and thousands of files, often hundreds of gigabytes each.</p>
        <p>RateCommons downloads those files from the insurers' own sites, records each file's URL, size and fingerprint, and archives the tables of contents daily. We use no claims data, no scraped quotes and no information about any patient.</p>
      </>
    ),
  },
  {
    id: 'parsing', title: 'Reading the files',
    body: (
      <>
        <p>Insurer files rarely match the published schema exactly. Our parser keeps <b>every value as published</b> and writes the cleaned value beside it. When a file departs from the schema (a missing field, an amount written as text, a placeholder price), we record a flag on the row instead of failing the file or dropping the row.</p>
        <p>Amounts are stored as whole numbers of ten-thousandths of a dollar, next to the exact string the insurer published, so no rounding ever changes a price.</p>
      </>
    ),
  },
  {
    id: 'dedup', title: 'Removing duplicates',
    body: (
      <>
        <p>Insurers repeat the same contracts across many files: one file per product, region or employer can carry identical rates. We give every provider group, price and price list an ID that is a hash of its content (xxh3-128), so identical facts get identical IDs no matter which file, month or computer they came from.</p>
        <p>Each distinct rate fact is stored once, with the set of networks (distinct files) that carry it. Cigna's October 2026 release, for example, turned 1.93 billion published rows into 305 million distinct rate facts.</p>
      </>
    ),
  },
  {
    id: 'identity', title: 'Who a provider is',
    body: (
      <>
        <p>A provider group is its <b>tax ID plus its sorted list of NPIs</b> (National Provider Identifiers). When an insurer lists NPI 0, the rate applies to everyone billing under that tax ID. We never use the names insurers type into their files to decide identity, because the same name is often spelled many ways and different groups share names.</p>
        <p>Locations and specialties come from public registries keyed by those numbers: the federal NPPES registry for NPIs and the IRS exempt-organization list for tax IDs.</p>
      </>
    ),
  },
  {
    id: 'stats', title: 'How the Explorer summarizes rates',
    body: (
      <>
        <p>Market tools report percentiles (10th, 25th, median, 75th, 90th) across <b>provider groups</b>, not across rows, so a group listed in 500 files counts once. Rates are kept apart by negotiated type, billing class (professional or institutional), setting (office or facility) and modifier (26 for the professional part, TC for the technical part), because these are not comparable amounts.</p>
        <p>Medicare's 2026 physician fee schedule is shown beside commercial rates as a yardstick: the non-facility amount for office services and the facility amount otherwise, adjusted for the state.</p>
      </>
    ),
  },
  {
    id: 'patients', title: 'How patient prices are chosen',
    body: (
      <>
        <p>For the patient price checker, we match each place (a clinic, imaging center or hospital campus) to the provider groups that practice at its address, then pick the rate for the service under the chosen plan. Each price carries a label:</p>
        <ul>
          <li><b>Confirmed</b>: a clinician at that place, covered by the contract, billed this service (or a closely related one) to Medicare in the latest public data, and the price is in a normal range.</li>
          <li><b>Likely</b>: the contract covers clinicians there whose specialty fits, but we found no Medicare record. Common for children's and women's health.</li>
          <li><b>Hidden</b>: the price is below 15% or above 15 times what Medicare pays, or far outside the insurer's own spread when Medicare has no price. These are hidden by default and shown with a warning on request.</li>
        </ul>
        <p>For imaging, the facility fee and the radiologist's reading fee are priced separately, because they are usually separate bills. Your out-of-pocket estimate applies your deductible, coinsurance and out-of-pocket maximum to those prices, entirely in your browser.</p>
      </>
    ),
  },
  {
    id: 'limits', title: 'Known limitations',
    body: (
      <ul>
        <li><b>A missing rate means no published rate</b>, not out of network. Insurers do not publish every contract, and some publish percentages or formulas instead of dollar amounts.</li>
        <li>A published rate is the contract amount, not a bill. Facility fees, extra services and your plan's rules can change what you pay.</li>
        <li>Insurer files contain stale and placeholder entries, such as $0.01 or $99,999, and rates for clinicians who would never provide a service. We flag what we can detect, but some will get through, including places that appear to offer a service they do not.</li>
        <li>For some insurers we have loaded common services first. The <Link to="/coverage">coverage page</Link> shows exactly what is loaded.</li>
        <li>Plan-to-file matching relies on the insurer's table of contents, which is sometimes incomplete.</li>
      </ul>
    ),
  },
]

export default function Methodology() {
  usePageTitle('Methodology')
  return (
    <>
      <PageHero kicker="Methodology" title="How RateCommons turns insurer files into prices."
        lead="Everything here is reproducible: the code is open source, every rate keeps its raw value and its source file, and the limitations are written down." />
      <div className="wrap grid gap-10 py-14 lg:grid-cols-[220px_1fr]">
        <nav aria-label="On this page" className="hidden lg:block">
          <ul className="sticky top-24 grid gap-1 border-l border-line">
            {SECTIONS.map((s) => (
              <li key={s.id}><a href={`#${s.id}`} className="-ml-px block border-l-2 border-transparent py-1.5 pl-4 text-sm text-ink-soft hover:border-brand-600 hover:text-ink">{s.title}</a></li>
            ))}
          </ul>
        </nav>
        <article className="prose-site max-w-3xl">
          {SECTIONS.map((s) => (
            <section key={s.id} id={s.id} className="scroll-mt-24">
              <h2>{s.title}</h2>
              {s.body}
            </section>
          ))}
          <section className="scroll-mt-24" id="code">
            <h2>Check our work</h2>
            <p>The parsers, the pipeline, the data service and this website are all in one public repository: <a href={GITHUB} target="_blank" rel="noreferrer">{GITHUB.replace('https://', '')}</a>. If you find a number that looks wrong, please open an issue with the link to the page you saw it on.</p>
          </section>
        </article>
      </div>
    </>
  )
}
