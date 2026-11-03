import { Link } from 'react-router-dom'
import { ArrowRight, Database, ExternalLink, FileCheck2, Fingerprint, Layers, Scale } from 'lucide-react'
import { CodeBlock, PAYER_LABEL, PageHero, statusSummary, useDataStatus, usePageTitle } from './ui'
import { GITHUB, HF } from './SiteLayout'

/** Repository sizes on Hugging Face, 2026-11-02 (all releases plus the serving pack). */
const DATASETS = [
  ['cigna', 'Cigna', '29 GB'],
  ['uhc', 'UnitedHealthcare', '34 GB'],
  ['aetna', 'Aetna', '669 GB'],
  ['bcbs', 'Blue Cross Blue Shield plans', '438 GB'],
  ['anthem', 'Anthem (Elevance)', '257 GB'],
  ['identity', 'Provider identity: NPPES registry, IRS exempt organizations, Medicare fee schedule', '1.5 GB'],
]

const TABLES = [
  ['rate_fact', 'One row per distinct rate fact: a billing code, the providers it applies to, a price list, and the set of networks it appears in.'],
  ['price_term', 'One negotiated price: type, amount (exact published string plus an integer in ten-thousandths of a dollar), billing class, setting, modifiers, expiration and flags.'],
  ['provider_group', 'Tax ID plus sorted NPI list. NPI 0 means the whole tax ID. Business names are kept only as hints.'],
  ['provider_set / provider_list', 'Which provider groups each rate applies to, exactly as the insurer grouped them.'],
  ['price_list', 'The price terms in one published list of negotiated prices.'],
  ['network_set / network', 'Which networks (distinct source files) carry each fact.'],
  ['source_file', 'Every file read: name, URL, size, fingerprint, header, counts and parser flags.'],
  ['code', 'Billing codes as published. Descriptor text is withheld where it is licensed (CPT, CDT, revenue codes, proprietary DRGs).'],
]

const DUCK = `INSTALL httpfs; LOAD httpfs;
-- Read straight from Hugging Face; DuckDB fetches only the parts a query needs.
SET VARIABLE base = 'hf://datasets/ratecommons/cigna/release=2026-10';

SELECT count(*) AS rate_facts
FROM read_parquet(getvariable('base') || '/rate_fact/*.parquet')
WHERE billing_code_type = 'CPT' AND billing_code = '99213';`

const PY = `# pip install duckdb huggingface_hub
import duckdb

con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs;")
base = "hf://datasets/ratecommons/cigna/release=2026-10"
terms = con.sql(f"""
    SELECT negotiated_type, billing_class, count(*) AS n, median(rate_e4) / 1e4 AS median_rate
    FROM '{base}/price_term/*.parquet'
    GROUP BY ALL ORDER BY n DESC LIMIT 20
""").df()
print(terms)`

export default function Data() {
  usePageTitle('Open data')
  const st = useDataStatus()
  const sum = statusSummary(st)
  return (
    <>
      <PageHero kicker="Open data" title="The full data, free to download."
        lead="Every in-network rate we have read, parsed, deduplicated and stored as Parquet on Hugging Face. No sign-up, no license fee, no data-room request.">
        <div className="mt-8 flex flex-wrap gap-3">
          <a href={HF} target="_blank" rel="noreferrer" className="btn-go">Browse on Hugging Face <ExternalLink className="h-4 w-4" /></a>
          <Link to="/explore?tool=run_sql" className="btn-line">Query it in your browser</Link>
        </div>
      </PageHero>

      <section className="wrap py-16">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="kicker">Datasets</p>
            <h2 className="h-section mt-2">One dataset per insurer</h2>
          </div>
          {sum && <p className="text-sm text-ink-mute">{sum.networks.toLocaleString('en-US')} networks loaded, latest build {sum.month}. <Link to="/coverage" className="font-semibold text-brand-700">Coverage details</Link></p>}
        </div>
        <div className="mt-8 overflow-hidden rounded-2xl border border-line bg-white">
          <table className="w-full text-left text-[15px]">
            <thead className="bg-[#f7f9f8] text-[13px] font-semibold text-ink-soft">
              <tr><th scope="col" className="px-5 py-3">Dataset</th><th scope="col" className="hidden px-5 py-3 sm:table-cell">Networks</th><th scope="col" className="px-5 py-3 text-right">Size</th></tr>
            </thead>
            <tbody>
              {DATASETS.map(([id, name, size]) => (
                <tr key={id} className="border-t border-line">
                  <td className="px-5 py-4">
                    <a href={`https://huggingface.co/datasets/ratecommons/${id}`} target="_blank" rel="noreferrer"
                      className="font-mono text-[14px] font-semibold text-brand-700 hover:text-brand-800">ratecommons/{id}</a>
                    <span className="mt-0.5 block text-sm text-ink-soft">{name}</span>
                  </td>
                  <td className="num hidden px-5 py-4 text-ink-soft sm:table-cell">{st?.payers?.[id] ? st.payers[id].networks.toLocaleString('en-US') : id === 'identity' ? '' : '…'}</td>
                  <td className="num px-5 py-4 text-right font-semibold">{size}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-sm text-ink-mute">Each insurer dataset has a <code className="font-mono">release=YYYY-MM</code> folder with the full tables, and a smaller <code className="font-mono">serving</code> pack laid out for fast lookups, which the site and API read.</p>
      </section>

      <section className="border-y border-line bg-white">
        <div className="wrap grid gap-10 py-16 lg:grid-cols-[1fr_1.2fr]">
          <div>
            <p className="kicker">What's inside</p>
            <h2 className="h-section mt-2">Tables that keep everything</h2>
            <p className="lead mt-4">Nothing is dropped for looking odd. Raw values sit beside the cleaned ones, and every oddity is recorded as a flag you can filter on.</p>
            <div className="mt-6 grid gap-4">
              {[
                [Fingerprint, 'Stable IDs', 'Every ID is a content hash, so the same provider group or price gets the same ID in every file, month and insurer.'],
                [Layers, 'Deduplicated', 'Insurers repeat the same rates across hundreds of files. Each distinct fact is stored once, with the list of networks that carry it.'],
                [FileCheck2, 'Traceable', 'Every fact leads back to the source files, with their URLs and fingerprints.'],
              ].map(([Icon, t, d]) => (
                <div key={t} className="flex gap-3">
                  <Icon className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" aria-hidden="true" />
                  <p className="text-[15px] leading-relaxed text-ink-soft"><b className="text-ink">{t}.</b> {d}</p>
                </div>
              ))}
            </div>
          </div>
          <dl className="grid content-start gap-px overflow-hidden rounded-2xl border border-line bg-line">
            {TABLES.map(([t, d]) => (
              <div key={t} className="bg-white p-4">
                <dt className="font-mono text-[14px] font-semibold text-ink">{t}</dt>
                <dd className="mt-1 text-[14px] leading-relaxed text-ink-soft">{d}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="wrap grid gap-8 py-16 lg:grid-cols-2">
        <div>
          <p className="kicker">Get started</p>
          <h2 className="h-section mt-2">Query it without downloading it</h2>
          <p className="lead mt-4">DuckDB reads Parquet straight from Hugging Face and fetches only what a query touches. The dataset card for each insurer has a full join example.</p>
          <div className="mt-6"><CodeBlock code={DUCK} label="DuckDB example" /></div>
        </div>
        <div className="grid content-start gap-4 lg:pt-[92px]">
          <CodeBlock code={PY} label="Python example" />
          <Link to="/for/developers" className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:text-brand-800">Prefer an API? See the developer page <ArrowRight className="h-4 w-4" /></Link>
        </div>
      </section>

      <section className="wrap pb-20">
        <div className="grid gap-6 md:grid-cols-2">
          <div className="card p-6">
            <h3 className="flex items-center gap-2 text-lg font-bold text-ink"><Scale className="h-5 w-5 text-brand-600" aria-hidden="true" />Provenance and terms</h3>
            <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
              The rates come from files insurers must publish under the federal Transparency in Coverage rule (45 CFR 147.212).
              RateCommons claims no ownership of them. Licensed code descriptions (such as CPT) are withheld; code numbers are kept.
              Our software is open source under the Apache 2.0 license.
            </p>
          </div>
          <div className="card p-6">
            <h3 className="flex items-center gap-2 text-lg font-bold text-ink"><Database className="h-5 w-5 text-brand-600" aria-hidden="true" />Read it correctly</h3>
            <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
              A missing rate means no published rate, not out of network. Check the negotiated type, billing class and setting before
              comparing amounts. The <Link to="/methodology" className="font-semibold text-brand-700 underline decoration-brand-200 underline-offset-2">methodology</Link> has the details,
              and the <a href={GITHUB} target="_blank" rel="noreferrer" className="font-semibold text-brand-700 underline decoration-brand-200 underline-offset-2">code</a> is public.
            </p>
          </div>
        </div>
        <p className="mt-6 text-sm text-ink-mute">Insurers covered: {Object.values(PAYER_LABEL).join(', ')}.</p>
      </section>
    </>
  )
}
