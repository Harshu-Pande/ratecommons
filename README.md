# RateCommons

A free, public, deduplicated dataset of the negotiated rates that health insurers publish under
the federal Transparency in Coverage (TiC) rule. It comes with free tools to query it: a web app,
an MCP connector for AI assistants, and CareCompass, a price-shopping app for patients.
Everything runs on free, no-card services: GitHub Actions, Hugging Face, Kaggle and Vercel.

- Design doc (the blueprint): https://claude.ai/artifact/7d81McCZzQwiNqL6i28pNK
- Where reality changed the blueprint, newest first: [docs/DECISIONS.md](docs/DECISIONS.md)
- Current state, for anyone picking the work up: [docs/HANDOFF.md](docs/HANDOFF.md)
- Who is doing what right now: [docs/WORKLOG.md](docs/WORKLOG.md)
- Build plan: [docs/NEXT.md](docs/NEXT.md)

## Status (November 2026)

| Payer | Dataset | In the apps |
| --- | --- | --- |
| Cigna | `ratecommons/cigna`, complete | Every code, every network |
| Aetna | `ratecommons/aetna`, complete (about 6,200 networks) | Every code for the 20 largest network groups; the 62 common services for every network; exact employer-plan lookup |
| BCBS (Blue companies) | `ratecommons/bcbs`: TN, IL and TX own networks plus BlueCard, and 28 more Blue companies | Every code for 33 main networks (TN, IL, TX and the largest home network of 20 more Blue companies); the 62 common services for every network. |
| Anthem (14 states) | `ratecommons/anthem`, complete | Every code for the 5 largest network families; the 62 common services for every network |
| UnitedHealthcare | `ratecommons/uhc`, being reduced wave by wave | 2 test files only, more in batches as waves finish |

Some payer files cannot be downloaded at all; they are listed in [ops/unavailable.txt](ops/unavailable.txt).

## Using the data

**Web app and API:** https://ratecommons-cloud.vercel.app. It looks up rates by billing code,
state, provider, network or plan, gives market distributions and provider rankings, and shows
the Medicare rate alongside.

**MCP connector** (Claude, ChatGPT and other MCP clients): `https://ratecommons-cloud.vercel.app/mcp`.
Its tools are `lookup_rates`, `market_distribution`, `provider_rates`, `rank_providers`,
`compare_providers`, `benchmark_provider`, `network_breadth`, `provider_networks`, `find_plans`,
`list_products`, `search_providers`, `code_info`, `medicare_rate`, `data_status` and `run_sql`.
Answers carry coverage notes that say when a code is served only for a payer's main networks.

**CareCompass:** https://carecompass-wheat.vercel.app, for patients. It covers 62 common
procedures, with prices by ZIP code and plan.

**The raw tables:** each payer dataset on Hugging Face is Parquet, readable with DuckDB, pandas
or Polars straight from `hf://datasets/ratecommons/<payer>`. Its dataset card describes the tables.

### How to read the data

- A missing rate means "no published rate", never "out of network".
- A provider group is a TIN plus a sorted list of NPIs. `npi: [0]` means the whole TIN.
  Names such as network_name or business_name are not used for identity.
- Amounts are integers in ten-thousandths of a dollar, and the raw published string is kept beside them.
- Nothing is discarded. Every raw value is kept as published, and deviations from the schema are
  recorded as flags rather than failing the file.
- CPT descriptor text (AMA copyright) and other licensed code text is withheld. Code numbers and rates are public.

## How it is built

```
payer indexes ──archive──> raw-manifests        (daily, only changes are stored)
in-network files ──map──> work bucket           (Rust core, parallel GitHub/Kaggle jobs, one shard each)
map output ──reduce waves──> merge ──> <payer> dataset   (deduplicated, content-hashed IDs)
<payer> dataset ──serve──> serving pack ──cloud──> small per-code/per-state files ──> web app + MCP
                                         └─shop──> CareCompass offers
```

- **IDs are content hashes** (xxh3-128 of a canonical encoding), so any worker computes the same ID
  and files can be deduplicated across payers' many near-identical copies.
- **History is stored as changes** (valid_from / valid_to). An unchanged fact writes nothing.
- **The orchestrator** (`ops/orchestrate.py`, the `orchestrate` workflow) runs reduce waves in
  order once every shard of a wave is mapped (see `ops/waves.txt`). It also starts the next map
  runs and chains serve → cloud → shop for some payers.
- **Big payers are served in two tiers.** Every code is served for the main networks, and the 62
  common services for all networks. With every code for every network the files would be too
  large for a free serverless function. Payers with thousands of networks are grouped by product,
  and the exact employer plan is still searchable.

### Workflows

Start a run by committing an edit to the request file. The last non-comment line is the request.
Results and reports land in `datasets/ratecommons/ops`.

| Workflow | Request file | Does |
| --- | --- | --- |
| `archive-manifests` | `ops/archive-request.txt` (also daily) | Archive each payer's raw index files |
| `map` | `ops/map-request.txt` | Map one payer's shards of in-network files into Parquet |
| `reduce` | `ops/reduce-request.txt` | Reduce one wave, or merge the waves into the release |
| `orchestrate` | scheduled | Drive map and reduce waves and the serving chain |
| `serve` | `ops/serve-request.txt` | Build a payer's serving pack (`payer:source:states:match:codes`) |
| `cloud` | `ops/cloud-request.txt` | Turn a serving pack into the app's small files |
| `shop` | `ops/shop-request.txt` | Rebuild CareCompass offers |
| `core` | `ops/core-request.txt` | Build and test the Rust core |
| `run` | `ops/run-request.txt` | Run any `ticdata` command |
| `kaggle`, `smoke` | `ops/kaggle-request.txt`, `ops/smoke-request.txt` | Kaggle jobs, platform smoke tests |

GitHub writes to Hugging Face through Trusted Publishers: short-lived tokens, nothing stored.
A new dataset or bucket needs this repo added as a trusted publisher in its settings. The only
repository secret is `KAGGLE_API_TOKEN`. Tokens never go in code, docs, commits or issues.

### Where the data lives (Hugging Face, org `ratecommons`)

| Name | Kind | Holds |
| --- | --- | --- |
| `cigna`, `aetna`, `bcbs`, `anthem`, `uhc` | dataset | Each payer's published release: rate_fact, provider_group, provider_set, provider_list, network_set, price_list, price_term, code, source_file |
| `identity` | dataset | Public provider identity sources (NPPES, Doctors and Clinicians, IRS exempt orgs) and shared serving tables |
| `raw-manifests` | dataset | Each payer's raw index files as served, daily, changes only |
| `ops` | dataset | Run reports from every worker |
| `work` | bucket | Scratch for map and reduce, and the app's serving files (`serve/`, `shop/`) |
| `restricted` | bucket, private | Licensed code text withheld from the public tables |

All names live in `project.toml`.

## Local use

```bash
pip install -e ".[dev]"
pytest
ticdata --help
ticdata parse-file <in-network.json.gz> out/   # parse one payer file into the release tables
ticdata verify --help                          # re-parse a source file and check it against the release
cd core && cargo build --release               # the Rust map core (ticcore)
```

## Layout

```
src/ticdata/        Python pipeline: discover, net (range reads), parse, pipeline (map shards),
                    reduce, consolidate, verify, card, codebook, identity, licensing,
                    serving + serve_jobs (serving packs), cloudpack (app files),
                    shop + shopcatalog (CareCompass), orchestration helpers
core/               ticcore, the Rust streaming splitter and mapper; same IDs as parse.py
                    (tests/test_core_parity.py checks this)
cloud/              the web app, JSON API and MCP server (Vercel, Python + DuckDB)
carecompass/        the patient app (Vite + React, Vercel)
space/, gateway/    the earlier Gradio explorer and its tunnel front door
ops/                request files, orchestrate.py, waves.txt, unavailable.txt
kaggle/             Kaggle kernel generator
.github/workflows/  the workflows above
docs/               DECISIONS, HANDOFF, WORKLOG, NEXT
```

## Working on this repo

Two Claude sessions work here at once. One owns the pipeline and the other the apps. Each
changes only its own lane, claims tasks in `docs/WORKLOG.md`, and records every lesson in
`docs/DECISIONS.md`. The rules are in [CLAUDE.md](CLAUDE.md).

## License

Code: Apache-2.0. Data: rates and code numbers are published as the TiC rule intends, for public
use. Licensed descriptor text is withheld (see `src/ticdata/licensing.py` and each dataset card).
