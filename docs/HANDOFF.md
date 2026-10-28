> **State on 2026-10-28 (01:00 CT), for a session picking this up:** the orchestrator (`ops/orchestrate.py`, cron +
> end of every map/reduce run) works through `ops/waves.txt`: Aetna waves 1-15 reduced (16 + merge left); BCBS
> (`bcbs`: HCSC IL/TX indexes, BlueCard files, BCBS of Tennessee's own networks as shards 20-23) fully mapped, wave 1
> dims re-running after the pyarrow streaming fix, then wave 2 (20-23) and merge; Anthem mapping (71 non-empty shards
> of an 80-shard plan; retry failed shards with a `map.yml` dispatch, `range` = comma list); UHC waves of 12 shards
> run by the orchestrator. After a bcbs/anthem merge, AUTO_PACK chains serve pack -> cloud pack -> CareCompass
> rebuild. Check runs with `gh api repos/Harshu-Pande/ratecommons/actions/runs`; read failed job logs with
> `gh api .../actions/jobs/<id>/logs`. Lessons go in `docs/DECISIONS.md`.

> **CareCompass v2 (2026-10-27):** the patient app is in `carecompass/` (Vite + React; Vercel project `carecompass`,
> root directory `carecompass`, deployed from GitHub). It reads static JSON from the work bucket under `shop/v1/`:
> `offers/<procedure>/<zip3>-<ST>.json` (places with their offers; a `g` map of TIN -> group name), `meta/zip3.json`,
> `meta/zip/<zip3>.json`, `meta/products.json`. Built by `src/ticdata/shop.py` (`ticdata shop-sources`, `shop-build
> --states`, `shop-meta`) through `.github/workflows/shop.yml` (`ops/shop-request.txt`: `all`, `meta`, or state groups).
> Procedures are in `src/ticdata/shopcatalog.py` (exported to `carecompass/src/data/procedures.json`). Method and
> lessons: `docs/DECISIONS.md` (2026-10-27). Production promotion of a preview deployment is a manual step.

> **Update 2026-10-27:** the app now runs serverless at https://ratecommons-cloud.vercel.app (code in
> `cloud/`, data in the public work bucket under `serve/v2/` (env `RC_DATA_URL`; v2 buckets provider sets by code prefix), built by `.github/workflows/cloud.yml`). The
> old address https://ratecommons-atticusfinch.vercel.app forwards there. The Mac setup below is retired.
> Tools include `run_sql` (sandboxed DuckDB SELECT over `rc_*` table functions; see its description in
> `cloud/api/_tooldocs.py`) and `rank_providers`. To release app code: push to main, set the Vercel env `RC_CODE_REF` (project `ratecommons-cloud`) to the
> commit, redeploy. To refresh data: rebuild serving packs (serve.yml), then cloud packs (cloud.yml).

# Handoff: RateCommons Explorer (state on 2026-10-22, 15:45 CT)

Written for whoever (human or AI) continues this work. Read `CLAUDE.md` first: its rules still apply
(no tokens in code/docs/commits, never trust names for identity, a missing rate means "no published
rate", call the older pipeline "our in-house pipeline").

## What exists

**Data (Hugging Face, org `ratecommons`)**
- `ratecommons/cigna` release=2026-10: all Cigna in-network files, verified. `serving/`: query pack, 8.1 GB.
- `ratecommons/uhc` release=2026-10: only 2 files, UHIC Choice Plus C2 and Options PPO P3. `serving/`: 17.5 GB.
- `ratecommons/aetna`: no release yet (full merge stalled, see below). `serving/`: pack from reduce wave 1,
  **nationwide but only 3 networks** (files matching `Choice_60178` = Aetna Open Access Managed Choice, and
  `TENET` = Tenet Healthcare's Choice POS II): 143,052,741 rate rows, 797,363 provider groups, 5.9 GB.
  (Earlier: all 140 wave-1 networks for Missouri only, 5.0 GB; all-networks national does not fit.)
- `ratecommons/identity`: NPPES, DAC, IRS EO; `serving/nppes.parquet` (NPI -> name, place, NUCC taxonomy),
  `serving/medicare_pfs.parquet` (CY2026 PFS per HCPCS/modifier, national "US" and per state by mean GPCI).

**Pack layout** (`src/ticdata/serving.py`, built by `.github/workflows/serve.yml` via `ops/serve-request.txt`):
`rate/part-XX` (code, ps_id, ns_id, pt_id; sorted by code), `price_term`, `ps_pli/state=XX`, `pli_pg`,
`provider_group`, `pg_npi/state=XX`, `ns`, `network`, `pg_network`, `code`. Join path:
rate -> ps_pli(state) -> pli_pg -> pg_npi(state) -> nppes; rate -> price_term; rate.ns_id -> ns -> network.

**App** (`space/`): `engine.py` (DuckDB over the packs), `app.py` (Gradio 6.29.1 UI + MCP server +
JSON API `POST /api/tool/<name>`), `ASK.md` (connector instructions). Tools: lookup_rates,
market_distribution, compare_providers, benchmark_provider, network_breadth, provider_networks,
find_plans, list_products, search_providers, code_info, medicare_rate, run_sql, data_status.
Comparisons default to `place="office"`: base rates without amount-changing modifiers (52/55/56/26/TC)
that apply in an office or anywhere; `facility` and `any` are options. A provider lookup also returns
flat all-services arrangements (code type CSTM-ALL, e.g. UHC pays Total Access Urgent Care $200/visit).

**Stable public address: https://ratecommons-atticusfinch.vercel.app** (UI, `/api/tool/<name>`, MCP at
`/gradio_api/mcp/`). It is a Vercel project (`ratecommons`, Harshu's Vercel account; code in `gateway/`)
that forwards every request to the Mac's current Cloudflare quick tunnel. The Mac's launchd agent
`org.ratecommons.tunnel` (`space/tunnel.py`) runs cloudflared and posts the tunnel address, signed with
HMAC, to the ntfy.sh topic in the gateway's `RC_ANNOUNCE_TOPIC` env var every 4 minutes; the key is in the
gateway env (`RC_ANNOUNCE_KEY`, sensitive) and `~/ratecommons-app/.announce_key` on the Mac, nowhere else.
When the Mac is off the gateway shows an "offline" page; after the Mac boots and logs in, launchd
(`org.ratecommons.app`, `org.ratecommons.tunnel`) brings everything back and the address is unchanged.
The gateway must not forward x-forwarded-* headers: Gradio's MCP server calls the app at its own root URL.

**Where it runs**: Harshu's Mac, `~/ratecommons-app` (repo clone in `repo/`, venv, `cloudflared`, data in
`data/`, ~29 GB). Both run as launchd agents (start at login, restart on exit): `run-app.sh` and `repo/space/tunnel.py`.
Restart the app after a `git pull`: `launchctl kickstart -k gui/$(id -u)/org.ratecommons.app`.
(`start.sh`/`stop.sh`/`restart-app.sh` are the older manual scripts; do not run them alongside launchd.)
The app keeps >= 10 GB free on the Mac (it refuses downloads that would go below; Harshu's rule).
It re-checks the datasets every 15 minutes and downloads new packs.

**AI**: users add `<link>/gradio_api/mcp/` as a custom connector in Claude (Settings -> Connectors).
Other MCP-capable assistants can use the same URL; anything else can call the JSON API.

## Measured
- 99214 office visit, Missouri, median per provider group: Cigna $124.78 (96% of MO Medicare $130.03),
  UHC $110.38 (85%), Aetna $93.75 (72%). Counts include NPs/PAs; pass `specialty` to narrow.
- Single-payer lookups ~5-15 s, all-payer distributions ~30-40 s on the Mac.

## Known gaps / next steps (in priority order for a demo)
1. **Speed**: every query re-joins parquet files. Ideas: cache per (code, state) results; materialize
   in-memory tables for `pli_pg`, `pg`, `pg_npi` of the queried state; push the provider-name lookup
   (`loc` CTE) after the aggregation.
2. **UI**: plain Gradio tables. No charts, no CPT descriptions (licensed text is withheld; descriptions
   could be added for HCPCS/DRG, or the AI supplies them). Product labels for Cigna are derived from file
   names and some are odd ("Cigna AZ Localflex..." appears in every state because the file is national).
3. **Always-on hosting**: the address is stable, but answers need the Mac to be on. Options to remove the
   Mac: HF PRO ($9/mo, deploy `space/` as a Gradio Space unchanged), a free VM, or re-cut the packs into
   small per-state/per-code files the Vercel side can fetch itself.
4. **Aetna**: full release merge is stuck: reduce wave 6 (`aetna 2026-10 all wave=6 72-87`) failed twice
   in the dims step; waves 7-16 and the merge wait behind it (`ops/waves.txt`, `ops/orchestrate.py`).
   Aetna provider sets explode (2.5 billion set->list rows for wave 1 nationally), so any Aetna pack must
   be state-limited (`aetna:wave-1:MO`).
5. **UHC**: only 2 of 7,316 files. Add more with `ops/map-request.txt` lines like
   `uhc 2 0 0-9 match=<name substring>,<name substring>`, then reduce (`uhc 2026-10 all`), then a pack.
6. Medicare comparison covers the physician fee schedule only (no OPPS/ASC/DRG).

## How to run things
- GitHub Actions is the orchestrator: append a line to `ops/<stage>-request.txt` and push, or
  `gh api -X POST repos/Harshu-Pande/ratecommons/actions/workflows/<wf>.yml/dispatches -f ref=main -f "inputs[request]=..."`.
- Local test of the app against a pack: `RC_NO_AUTOSTART=1 RC_DATA=<dir with identity/serving and <payer>/serving>`
  then `import engine as E; E.load(download=False)`.
- Tests: `python -m pytest -q tests`.
