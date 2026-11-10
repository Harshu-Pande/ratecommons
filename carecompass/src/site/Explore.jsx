import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowDownUp, Bot, Check, Code2, Copy, Download, Loader2, Play } from 'lucide-react'
import { MCP_URL, PAYER_LABEL, callTool, usePageTitle } from './ui'

/** Each tool, its place in the menu, plain-language copy and a working example. */
export const TOOLS = [
  { group: 'Look up prices', name: 'lookup_rates', title: 'Rates for a service',
    blurb: 'Every published rate for one billing code in one state: one row per insurer product, provider group and price.',
    ex: { code: '99213', state: 'MO', zip_prefix: '631', limit: '200' } },
  { group: 'Look up prices', name: 'market_distribution', title: 'Market spread',
    blurb: 'The range of rates for one service in a state: low, typical and high, by insurer, product or setting, with Medicare alongside.',
    ex: { code: '99214', state: 'MO', group_by: 'payer', place: 'office' } },
  { group: 'Look up prices', name: 'provider_rates', title: "A provider's rates",
    blurb: 'What each insurer pays one provider group for a set of services. Search by name, NPI or tax ID (the example is Saint Louis University, tax ID 430654872).',
    ex: { provider: '430654872', codes: '99213,99214', state: 'MO' } },
  { group: 'Compare and benchmark', name: 'compare_providers', title: 'Compare providers',
    blurb: 'Several provider groups side by side for the same services and insurers. The example compares Saint Louis University and Washington University by tax ID.',
    ex: { codes: '99213,99214', state: 'MO', providers: '430654872, 430653611' } },
  { group: 'Compare and benchmark', name: 'benchmark_provider', title: 'Benchmark a practice',
    blurb: "Where one practice's rates sit against its market and against Medicare, code by code.",
    ex: { provider: '430654872', codes: '99213,99214,99215', state: 'MO' } },
  { group: 'Compare and benchmark', name: 'rank_providers', title: 'Rank provider groups',
    blurb: 'Rank provider groups by their rates across a basket of codes, in one state or the whole country.',
    ex: { codes: '70450,71250,74177,72148', state: 'MO', specialty: 'Radiology' } },
  { group: 'Networks and plans', name: 'find_plans', title: "Find an employer's plan",
    blurb: 'Search employer and plan names to find which insurer networks they use.',
    ex: { query: 'Boeing' } },
  { group: 'Networks and plans', name: 'network_breadth', title: 'Network breadth',
    blurb: 'How many providers of a specialty each network includes in an area.',
    ex: { state: 'MO', specialty: 'Cardiovascular Disease' } },
  { group: 'Networks and plans', name: 'provider_networks', title: "A provider's networks",
    blurb: 'Which insurer networks list a provider group.',
    ex: { provider: 'Saint Louis University', state: 'MO' } },
  { group: 'Networks and plans', name: 'search_providers', title: 'Find providers',
    blurb: 'Search the federal provider registry by name, place, specialty or NPI.',
    ex: { state: 'MO', city: 'Saint Louis', specialty: 'Radiology' } },
  { group: 'Advanced', name: 'run_sql', title: 'Custom SQL',
    blurb: 'Read-only SQL (DuckDB) over the full data through table functions such as rc_rates, rc_medicare and rc_nppes.',
    ex: { sql: "SELECT payer, count(DISTINCT tin) AS groups, median(rate) AS median_rate\nFROM rc_rates('all', 'MO', '99213', '', 'office')\nWHERE negotiated_type = 'negotiated' AND rate > 0.01 AND rate < 99999\nGROUP BY payer ORDER BY payer" } },
  { group: 'Advanced', name: 'code_info', title: 'Code lookup',
    blurb: 'What a billing code is and how widely each insurer prices it.',
    ex: { code: '70553' } },
  { group: 'Advanced', name: 'medicare_rate', title: 'Medicare fee schedule',
    blurb: "Medicare's 2026 physician fee schedule amounts for any codes, nationally or by state.",
    ex: { codes: '99213,99214', state: 'MO' } },
  { group: 'Advanced', name: 'data_status', title: 'Data status',
    blurb: 'Which insurers and networks are loaded right now, and when each was built.', ex: {} },
]
const BY_NAME = Object.fromEntries(TOOLS.map((t) => [t.name, t]))
const GROUPS = [...new Set(TOOLS.map((t) => t.group))]

const LABEL = {
  code: 'Billing code', codes: 'Billing codes', state: 'State', payer: 'Insurer', network: 'Network or plan',
  city: 'City', zip_prefix: 'ZIP prefix', specialty: 'Specialty', provider: 'Provider (name, NPI or tax ID)',
  providers: 'Providers (comma-separated)', billing_class: 'Billing class', limit: 'Row limit', group_by: 'Group by',
  place: 'Setting', modifier: 'Modifier', weights: 'Code weights', min_codes: 'Minimum codes', query: 'Employer or plan name',
  name: 'Name', npi: 'NPI', sql: 'SQL', max_rows: 'Row limit',
}
const CHOICES = {
  payer: [['', 'All insurers'], ...Object.entries(PAYER_LABEL)],
  billing_class: [['', 'Any'], ['professional', 'Professional'], ['institutional', 'Institutional']],
  place: [['office', 'Office'], ['facility', 'Facility'], ['any', 'Any']],
  modifier: [['', 'None (base rate)'], ['26', '26 (professional part)'], ['TC', 'TC (technical part)']],
}
const GROUP_BY = { market_distribution: [['payer', 'Insurer'], ['product', 'Product'], ['setting', 'Setting'], ['none', 'Nothing']] }
const SLOW = new Set(['provider_rates', 'compare_providers', 'benchmark_provider'])
const ADVANCED = new Set(['limit', 'max_rows', 'weights', 'min_codes', 'billing_class', 'modifier', 'zip_prefix', 'network'])

const PREFER = ['median', 'median_rate', 'rate', 'p50', 'score', 'allowed', 'nonfacility_amount', 'providers', 'provider_groups', 'groups', 'n']
const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
const nice = (k) => k.replace(/_/g, ' ')

function fmt(v, k = '') {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  if (typeof v === 'number') {
    if (/pct|percent/.test(k)) return `${v.toLocaleString('en-US', { maximumFractionDigits: 1 })}%`
    return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toLocaleString('en-US', { maximumFractionDigits: 2 })
  }
  return String(v)
}

function toCsv(rows) {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))]
  const q = (v) => {
    v = v === null || v === undefined ? '' : Array.isArray(v) ? v.join('; ') : typeof v === 'object' ? JSON.stringify(v) : String(v)
    return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v
  }
  return [cols.join(','), ...rows.map((r) => cols.map((c) => q(r[c])).join(','))].join('\n')
}

/** A spread chart (p10 to p90 with the median) when the rows carry percentiles, else a bar chart of one measure. */
function ResultChart({ rows, tool }) {
  if (!rows.length || rows.length > 40) return null
  const first = rows[0]
  const cols = Object.keys(first)
  const labelCol = cols.find((c) => typeof first[c] === 'string' && !/^(state|code|place|modifier)$/.test(c)) || cols.find((c) => typeof first[c] === 'string')
  if (!labelCol) return null
  const label = (r) => (labelCol === 'payer' ? PAYER_LABEL[r.payer] || r.payer : String(r[labelCol] ?? ''))
  const medicare = rows.every((r) => isNum(r.medicare)) ? rows[0].medicare : null
  if (rows.every((r) => isNum(r.p10) && isNum(r.p90) && isNum(r.median))) {
    const top = Math.max(...rows.map((r) => r.p90), medicare || 0) * 1.08
    const X = (v) => `${(v / top) * 100}%`
    return (
      <figure className="mt-6" aria-label={`Median and 10th to 90th percentile by ${nice(labelCol)}`}>
        <figcaption className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-ink-soft">
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-brand-600" />Median</span>
          <span className="flex items-center gap-1.5"><span className="h-1.5 w-5 rounded bg-brand-200" />Middle 80% of provider groups (10th to 90th percentile)</span>
          {medicare && <span className="flex items-center gap-1.5"><span className="h-3 border-l-2 border-dashed border-clay-600" />Medicare {fmt(medicare)}</span>}
        </figcaption>
        <div className="relative grid gap-3">
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-[minmax(110px,180px)_1fr_80px] items-center gap-3 text-[15px]">
              <span className="truncate font-semibold text-ink" title={label(r)}>{label(r)}</span>
              <span className="relative h-7">
                {medicare && <span className="absolute inset-y-[-6px] border-l-2 border-dashed border-clay-600" style={{ left: X(medicare) }} aria-hidden="true" />}
                <span className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-brand-200" style={{ left: X(r.p10), width: `calc(${X(r.p90)} - ${X(r.p10)})` }} />
                <span className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-brand-600" style={{ left: X(r.median) }} />
              </span>
              <span className="num text-right font-semibold">${fmt(r.median)}</span>
            </div>
          ))}
        </div>
      </figure>
    )
  }
  const valCol = PREFER.find((c) => rows.every((r) => isNum(r[c])))
  if (!valCol || rows.length < 2) return null
  const max = Math.max(...rows.map((r) => r[valCol]))
  if (!(max > 0)) return null
  const money = /rate|median|allowed|amount|p\d/.test(valCol)
  return (
    <figure className="mt-6" aria-label={`${nice(valCol)} by ${nice(labelCol)}`}>
      <figcaption className="mb-3 text-[13px] text-ink-soft">{nice(valCol)} by {nice(labelCol)}</figcaption>
      <div className="grid gap-2.5">
        {rows.slice(0, 20).map((r, i) => (
          <div key={i} className="grid grid-cols-[minmax(110px,220px)_1fr_90px] items-center gap-3 text-[14px]">
            <span className="truncate font-medium text-ink" title={label(r)}>{label(r)}</span>
            <span className="h-5 rounded bg-brand-600" style={{ width: `${Math.max(1, (r[valCol] / max) * 100)}%` }} />
            <span className="num text-right font-semibold">{money ? '$' : ''}{fmt(r[valCol])}</span>
          </div>
        ))}
      </div>
    </figure>
  )
}

function ResultTable({ rows }) {
  const [sort, setSort] = useState({ k: null, dir: 1 })
  const cols = useMemo(() => [...new Set(rows.flatMap((r) => Object.keys(r)))], [rows])
  const sorted = useMemo(() => {
    if (!sort.k) return rows
    return [...rows].sort((a, b) => {
      const x = a[sort.k], y = b[sort.k]
      return (x === y ? 0 : x == null ? 1 : y == null ? -1 : x < y ? -1 : 1) * sort.dir
    })
  }, [rows, sort])
  return (
    <div className="mt-6 max-h-[70vh] overflow-auto rounded-xl border border-line">
      <table className="w-full border-collapse text-left text-[14px]">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c} scope="col" className="sticky top-0 z-[1] whitespace-nowrap border-b border-line bg-[#f7f9f8] p-0 font-semibold text-ink-soft">
                <button type="button" onClick={() => setSort((s) => ({ k: c, dir: s.k === c ? -s.dir : 1 }))}
                  className="flex w-full items-center gap-1 px-3 py-2.5 text-left hover:text-ink">
                  {nice(c)} <ArrowDownUp className={`h-3.5 w-3.5 ${sort.k === c ? 'text-brand-600' : 'text-ink-mute/50'}`} aria-hidden="true" />
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.slice(0, 2000).map((r, i) => (
            <tr key={i} className="border-b border-[#eef2f0] hover:bg-canvas">
              {cols.map((c) => (
                <td key={c} className={`max-w-[420px] truncate whitespace-nowrap px-3 py-2 align-top ${isNum(r[c]) ? 'num text-right' : ''}`} title={typeof r[c] === 'string' && r[c].length > 50 ? r[c] : undefined}>
                  {c === 'payer' ? PAYER_LABEL[r[c]] || r[c] : fmt(r[c], c)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 2000 && <p className="p-3 text-sm text-ink-mute">Showing the first 2,000 of {rows.length.toLocaleString('en-US')} rows. Download the CSV for all of them.</p>}
    </div>
  )
}

function useSchemas() {
  const [s, setS] = useState(null)
  useEffect(() => {
    fetch('/api/tools').then((r) => r.json()).then((xs) => setS(Object.fromEntries(xs.map((x) => [x.name, x])))).catch(() => setS({}))
  }, [])
  return s
}

export default function Explore() {
  const [params, setParams] = useSearchParams()
  const schemas = useSchemas()
  const name = BY_NAME[params.get('tool')] ? params.get('tool') : 'market_distribution'
  const tool = BY_NAME[name]
  usePageTitle(`${tool.title}: Explore the data`)
  const schema = schemas?.[name]
  const props = schema?.inputSchema?.properties || {}
  const required = schema?.inputSchema?.required || []

  const initial = () => {
    const fromUrl = {}
    for (const [k, v] of params.entries()) if (k !== 'tool' && k !== 'run') fromUrl[k] = v
    return Object.keys(fromUrl).length ? fromUrl : { ...tool.ex }
  }
  const [args, setArgs] = useState(initial)
  const [showMore, setShowMore] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState('')
  const ctl = useRef(null)
  const ran = useRef(false)

  useEffect(() => { setArgs(initial()); setRes(null); setErr(''); ran.current = false }, [name]) // eslint-disable-line react-hooks/exhaustive-deps

  const clean = (a) => Object.fromEntries(Object.entries(a)
    .filter(([k, v]) => v !== '' && v != null && (!schema || k in props))
    .map(([k, v]) => [k, ['integer', 'number'].includes(props[k]?.type) && v !== '' && !Number.isNaN(Number(v)) ? Number(v) : v]))

  const run = async (e, override) => {
    e?.preventDefault()
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    setBusy(true); setErr(''); setRes(null)
    const t0 = performance.now()
    try {
      const body = clean(override || args)
      const d = await callTool(name, body, { signal: c.signal })
      let rows = d.rows
      if (!rows) { const { ok, seconds, notes, truncated, ...rest } = d; rows = [rest] }
      // some tools lead with a summary row (payer "_summary"): show it as a line, not as data
      const summary = rows.filter((r) => r.payer === '_summary')
      rows = rows.filter((r) => r.payer !== '_summary')
      const sumNotes = summary.map((r) => Object.entries(r).filter(([k, v]) => k !== 'payer' && v != null && v !== '' && !(Array.isArray(v) && !v.length))
        .map(([k, v]) => `${nice(k)}: ${fmt(v, k)}`).join(' · '))
      setRes({ rows, notes: [...sumNotes, ...(d.notes || [])], truncated: d.truncated, secs: ((performance.now() - t0) / 1000).toFixed(1) })
      const q = new URLSearchParams({ tool: name, ...body })
      setParams(q, { replace: true })
    } catch (x) {
      if (x.name !== 'AbortError') setErr(x.message || String(x))
    } finally {
      if (ctl.current === c) setBusy(false)
    }
  }

  useEffect(() => {
    if (schema && params.get('run') === '1' && !ran.current) { ran.current = true; run(null, initial()) }
  }, [schema]) // eslint-disable-line react-hooks/exhaustive-deps

  const copy = async (what, text) => {
    try { await navigator.clipboard.writeText(text); setCopied(what); setTimeout(() => setCopied(''), 1800) } catch { /* */ }
  }
  const curl = `curl -X POST https://www.ratecommons.org/api/tool/${name} \\\n  -H 'content-type: application/json' \\\n  -d '${JSON.stringify(clean(args)).replace(/'/g, "'\\''")}'`
  const aiPrompt = `Using the RateCommons connector, run ${name} with ${JSON.stringify(clean(args))} and explain what the results show.`
  const download = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([toCsv(res.rows)], { type: 'text/csv' }))
    a.download = `ratecommons-${name}.csv`
    a.click()
  }

  const fields = Object.entries(props).filter(([k]) => showMore || !ADVANCED.has(k) || required.includes(k) || args[k])
  const hidden = Object.keys(props).filter((k) => ADVANCED.has(k) && !required.includes(k) && !args[k]).length

  return (
    <div className="bg-[#f6f8f9]">
      <div className="mx-auto flex w-full max-w-[1360px] flex-wrap items-start gap-7 px-4 py-7 sm:px-7">
        <label className="block w-full lg:hidden">
          <span className="mb-1.5 block text-[13px] font-semibold text-[#2e3e4c]">Tool</span>
          <select className="field w-full" value={name} onChange={(e) => setParams({ tool: e.target.value })}>
            {GROUPS.map((g) => (
              <optgroup key={g} label={g}>
                {TOOLS.filter((t) => t.group === g).map((t) => <option key={t.name} value={t.name}>{t.title}</option>)}
              </optgroup>
            ))}
          </select>
        </label>
        <nav aria-label="Tools" className="hidden min-w-0 flex-[1_1_240px] gap-5 lg:sticky lg:top-24 lg:grid">
          {GROUPS.map((g) => (
            <div key={g}>
              <p className="mb-1.5 ml-3 text-xs font-bold uppercase tracking-[0.06em] text-ink-mute">{g}</p>
              {TOOLS.filter((t) => t.group === g).map((t) => (
                <Link key={t.name} to={`/explore?tool=${t.name}`} aria-current={t.name === name ? 'page' : undefined}
                  className={`block rounded-lg px-3 py-2 text-[15px] ${t.name === name ? 'bg-[#e6f2ed] font-semibold text-brand-800' : 'text-[#2e3e4c] hover:bg-[#eef2f5] hover:text-ink'}`}>
                  {t.title}
                </Link>
              ))}
            </div>
          ))}
        </nav>

        <div className="grid min-w-0 flex-[999_1_720px] grid-cols-[minmax(0,1fr)] gap-5">
          <div>
            <h1 className="font-display text-[32px] font-bold text-ink">{tool.title}</h1>
            <p className="mt-1.5 max-w-3xl text-base text-[#4a5a68]">{tool.blurb}</p>
          </div>

          <form onSubmit={run} className="card grid gap-4 p-5" aria-label="Query">
            {!schemas ? (
              <p className="flex items-center gap-2 text-ink-mute"><Loader2 className="h-4 w-4 animate-spin" /> Loading the tool…</p>
            ) : !schema ? (
              <p className="text-clay-600">The data service did not answer. Please refresh in a moment.</p>
            ) : (
              <>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {fields.map(([k, p]) => {
                    const id = `f-${k}`
                    const lab = <span className="mb-1.5 block text-[13px] font-semibold text-[#2e3e4c]">{LABEL[k] || nice(k)}{required.includes(k) ? ' *' : ''}</span>
                    const hint = p.description ? p.description.split(/(?<=\.)\s/)[0] : ''
                    const set = (v) => setArgs((a) => ({ ...a, [k]: v }))
                    if (k === 'sql') {
                      return (
                        <label key={k} htmlFor={id} className="block sm:col-span-2 lg:col-span-3">{lab}
                          <textarea id={id} rows={8} spellCheck={false} value={args[k] ?? ''} onChange={(e) => set(e.target.value)}
                            className="w-full rounded-[10px] border border-[#c9d3cf] bg-white p-3 font-mono text-[13.5px] text-ink focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-100" />
                          <span className="mt-1 block text-[13px] text-ink-mute">Table functions: rc_rates, rc_rates_by_product, rc_medicare, rc_groups, rc_group_npis, rc_nppes, rc_codes, rc_products. Read-only.</span>
                        </label>
                      )
                    }
                    const choices = (k === 'group_by' && GROUP_BY[name]) || CHOICES[k]
                    return (
                      <label key={k} htmlFor={id} className="block" title={p.description || ''}>{lab}
                        {choices ? (
                          <select id={id} className="field w-full" value={args[k] ?? (k === 'payer' ? '' : choices[0][0])} onChange={(e) => set(e.target.value)}>
                            {choices.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                          </select>
                        ) : (
                          <input id={id} className="field w-full" value={args[k] ?? ''} onChange={(e) => set(k === 'state' ? e.target.value.toUpperCase() : e.target.value)}
                            placeholder={k === 'state' ? 'e.g. MO' : hint.slice(0, 48)} />
                        )}
                      </label>
                    )
                  })}
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <button type="submit" className="btn-go" disabled={busy}>
                    {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Play className="h-4 w-4" />} {busy ? 'Running…' : 'Run'}
                  </button>
                  <button type="button" className="btn-line btn-sm" onClick={() => setArgs({ ...tool.ex })}>Load the example</button>
                  {hidden > 0 && <button type="button" className="text-sm font-semibold text-brand-700" onClick={() => setShowMore(true)}>More options ({hidden})</button>}
                  {busy && <span className="text-sm text-ink-mute">{SLOW.has(name) ? 'Provider and row-level queries scan every network and can take two to four minutes.' : 'Market-wide queries can take about a minute.'}</span>}
                </div>
              </>
            )}
          </form>

          {err && <div role="alert" className="card border-clay-100 bg-clay-50 p-4 text-[15px] text-clay-700">{err}</div>}

          {res && (
            <section className="card p-5 sm:p-6" aria-label="Result">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <p className="text-[15px] text-ink-soft">
                  <b className="text-ink">{res.rows.length.toLocaleString('en-US')}</b> row{res.rows.length === 1 ? '' : 's'} in {res.secs}s{res.truncated ? ' (truncated: narrow the query)' : ''}
                </p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="btn-line btn-sm" onClick={download} disabled={!res.rows.length}><Download className="h-4 w-4" /> Download CSV</button>
                  <button type="button" className="btn-line btn-sm" onClick={() => copy('api', curl)}>{copied === 'api' ? <Check className="h-4 w-4" /> : <Code2 className="h-4 w-4" />} {copied === 'api' ? 'Copied' : 'Copy API call'}</button>
                  <button type="button" className="btn-line btn-sm" onClick={() => copy('ai', aiPrompt)}>{copied === 'ai' ? <Check className="h-4 w-4" /> : <Bot className="h-4 w-4" />} {copied === 'ai' ? 'Copied' : 'Copy a prompt for my AI'}</button>
                </div>
              </div>
              {res.notes.length > 0 && (
                <ul className="mt-4 grid gap-1.5 rounded-xl bg-canvas p-4 text-[14px] leading-relaxed text-ink-soft">
                  {res.notes.slice(0, 6).map((n) => <li key={n}>{n}</li>)}
                </ul>
              )}
              {res.rows.length ? (
                <>
                  <ResultChart rows={res.rows} tool={name} />
                  <ResultTable rows={res.rows} />
                </>
              ) : (
                <p className="mt-4 text-[15px] text-ink-soft">No published rates match. A missing rate means no published rate, not that a provider is out of network.</p>
              )}
              <p className="mt-4 text-[13px] leading-relaxed text-ink-mute">
                Source: insurers' Transparency in Coverage files, as cleaned by RateCommons. Rates are contract amounts, not a patient's cost.{' '}
                <Link to="/methodology" className="font-medium text-brand-700 underline decoration-brand-200 underline-offset-2">How this is calculated</Link>
              </p>
            </section>
          )}

          <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-night px-6 py-5 text-[#e8eef2]">
            <p className="text-base"><b className="text-white">Prefer to ask in plain English?</b> Add <code className="font-mono text-sea">{MCP_URL}</code> to Claude or ChatGPT and your assistant runs these tools for you.</p>
            <Link to="/ai" className="btn-sea btn-sm">Connect your AI</Link>
          </section>
        </div>
      </div>
    </div>
  )
}
