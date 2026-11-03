import { Link } from 'react-router-dom'
import { ArrowRight, Bot, MessageSquareText, ShieldCheck, Wrench } from 'lucide-react'
import { CodeBlock, CopyBox, MCP_URL, PageHero, usePageTitle } from './ui'
import { TOOLS } from './Explore'

const CLIENTS = [
  {
    name: 'Claude', note: 'Web, desktop and mobile. Free plans allow one custom connector.',
    steps: [
      <>Open <b>Customize</b>, then <b>Connectors</b>.</>,
      <>Click <b>+ Add</b>, then <b>Add custom connector</b>.</>,
      <>Name it <b>RateCommons</b> and paste the address above. Click <b>Continue</b>.</>,
      <>Choose <b>no sign-in</b> (RateCommons needs none), then click <b>Add</b>.</>,
      <>In a chat, click <b>+</b>, open <b>Connectors</b> and switch RateCommons on.</>,
    ],
    help: ['Claude help: custom connectors', 'https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp'],
  },
  {
    name: 'ChatGPT', note: 'Uses developer mode. Which plans offer it changes, so check OpenAI’s help page.',
    steps: [
      <>Open <b>Settings</b>, then <b>Apps &amp; Connectors</b>, then <b>Advanced settings</b>, and turn on <b>Developer mode</b>.</>,
      <>Back in <b>Apps &amp; Connectors</b>, click <b>Create</b>.</>,
      <>Name it <b>RateCommons</b>, paste the address above and choose <b>No authentication</b>.</>,
      <>Create the app, then pick it from <b>+</b> and <b>More</b> in a new chat.</>,
    ],
    help: ['OpenAI help: developer mode', 'https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt'],
  },
  {
    name: 'Other MCP clients', note: 'Cursor, VS Code, Claude Code, agents you build, and anything that speaks MCP over HTTP.',
    steps: [
      <>Add a remote (streamable HTTP) server with the address above. No key or header is needed.</>,
      <>Or, from a terminal with Claude Code: <code className="font-mono text-[13px]">claude mcp add --transport http ratecommons {MCP_URL}</code></>,
    ],
  },
]

const QUESTIONS = [
  ['Patients', 'What does UnitedHealthcare pay for a brain MRI near 63110, and where is it cheapest?'],
  ['Providers', 'Benchmark Saint Louis University’s rates for 99213 to 99215 against the Missouri market and Medicare.'],
  ['Employers', 'Which insurer pays least for a mid-level office visit in Missouri, and how wide is the range?'],
  ['Researchers', 'Write and run SQL comparing median 99214 rates by insurer product in Missouri, then chart it.'],
]

export default function AI() {
  usePageTitle('Ask with your AI assistant')
  return (
    <>
      <PageHero kicker="Ask with AI" title="Ask health price questions in plain English."
        lead="Connect RateCommons to Claude, ChatGPT or any assistant that supports the Model Context Protocol (MCP). Your assistant picks the right tool, runs it on the live data and explains the answer, with numbers you can check.">
        <div className="mt-8 max-w-2xl">
          <p className="mb-2 text-sm font-semibold text-ink">Connector address</p>
          <CopyBox text={MCP_URL} label="Copy address" />
          <p className="mt-3 text-sm text-ink-mute">Free. No account, key or sign-in.</p>
        </div>
      </PageHero>

      <section className="wrap py-16">
        <p className="kicker">Set up in about a minute</p>
        <h2 className="h-section mt-2">Add the connector</h2>
        <div className="mt-8 grid gap-5 lg:grid-cols-3">
          {CLIENTS.map((c) => (
            <div key={c.name} className="card flex flex-col p-6">
              <h3 className="flex items-center gap-2 text-xl font-bold text-ink"><Bot className="h-5 w-5 text-brand-600" aria-hidden="true" />{c.name}</h3>
              <p className="mt-1 text-sm text-ink-mute">{c.note}</p>
              <ol className="mt-5 grid gap-3">
                {c.steps.map((s, i) => (
                  <li key={i} className="flex gap-3 text-[15px] leading-relaxed text-ink-soft">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-bold text-brand-700">{i + 1}</span>
                    <span className="min-w-0 break-words">{s}</span>
                  </li>
                ))}
              </ol>
              {c.help && <a href={c.help[1]} target="_blank" rel="noreferrer" className="mt-auto pt-5 text-sm font-semibold text-brand-700 hover:text-brand-800">{c.help[0]} ↗</a>}
            </div>
          ))}
        </div>
        <p className="mt-4 text-sm text-ink-mute">Menus in these apps change from time to time; the linked help pages have the latest steps.</p>
      </section>

      <section className="border-y border-line bg-white">
        <div className="wrap py-16">
          <p className="kicker">Try asking</p>
          <h2 className="h-section mt-2">Questions it can answer</h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            {QUESTIONS.map(([who, q]) => (
              <div key={q} className="rounded-2xl bg-canvas p-5">
                <p className="text-xs font-bold uppercase tracking-[0.06em] text-brand-700">{who}</p>
                <p className="mt-2 flex gap-2.5 text-[16px] leading-relaxed text-ink"><MessageSquareText className="mt-1 h-4 w-4 shrink-0 text-ink-mute" aria-hidden="true" />{q}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="wrap grid gap-10 py-16 lg:grid-cols-2">
        <div>
          <p className="kicker">What your assistant gets</p>
          <h2 className="h-section mt-2">{TOOLS.length} tools, one data source</h2>
          <p className="lead mt-4">The same tools power the <Link to="/explore" className="font-semibold text-brand-700 underline decoration-brand-200 underline-offset-2">Explorer</Link>, so anything your assistant finds, you can open and check yourself.</p>
          <ul className="mt-6 grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {TOOLS.map((t) => (
              <li key={t.name}><Link to={`/explore?tool=${t.name}`} className="flex items-center gap-2 text-[15px] text-ink-soft hover:text-brand-700"><Wrench className="h-3.5 w-3.5 text-ink-mute" aria-hidden="true" />{t.title}</Link></li>
            ))}
          </ul>
        </div>
        <div className="grid content-start gap-5">
          <div className="card p-6">
            <h3 className="flex items-center gap-2 text-lg font-bold text-ink"><ShieldCheck className="h-5 w-5 text-brand-600" aria-hidden="true" />What we see, and what we don't</h3>
            <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
              Your assistant sends us only the tool arguments it chooses, such as a billing code and a state. We never see your
              conversation, and we don't log who asks. Your assistant's own provider handles your chat under its own privacy policy.
            </p>
          </div>
          <div>
            <p className="mb-2 text-sm font-semibold text-ink">Test it from a terminal</p>
            <CodeBlock label="MCP test" code={`curl -X POST ${MCP_URL} \\
  -H 'content-type: application/json' \\
  -H 'accept: application/json, text/event-stream' \\
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`} />
          </div>
          <Link to="/for/developers" className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:text-brand-800">Building something? See the developer page <ArrowRight className="h-4 w-4" /></Link>
        </div>
      </section>
    </>
  )
}
