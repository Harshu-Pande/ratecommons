# Build plan from day 1

Rule of the day: never wait on a running job. Start the long job first, then write
code for another track until it reports to `datasets/ratecommons/ops`.

## Already measured (night before day 1)

- `runs/2026-10-21-gha-*/`: GitHub runner speed per payer, rapidgzip vs zlib.
- `runs/20261021-kaggle-*/`: Kaggle reaches UHC/UMR only; its speed and disk.
- How to start runs and read results without the Actions API: see DECISIONS
  (edit `ops/smoke-request.txt`, `ops/archive-request.txt`, `ops/kaggle-request.txt`).

## Head start (night of 2026-10-21): where each track stands

| Track | Done | Next |
| --- | --- | --- |
| A. Parser v0 | `parse.py` (Parser-rules flags, content-hashed tables), `pipeline.py` + `map.yml` (40 shards). Full Cigna run launched: 124 files, 29.7 GB | Check `runs/*-map-cigna-*`; fix failures; then `reduce` |
| Reduce | `reduce.py` + `reduce.yml`: 16 fact parts + dims, derived networks and network sets, published to `datasets/ratecommons/cigna` (trusted publisher set) | Run `cigna 2026-10` once the map run is clean; then a dataset card |
| B. Rust core | `core/` splitter: zlib-rs inflate thread + byte-level record cutter; counts match Python exactly. `core.yml` E7 bench on Cigna national OAP launched | Typed parse (simd-json or serde structs), the same canonical hashes as `parse.py` (cross-check test), Parquet out; then Aetna |
| C. Identity | `datasets/ratecommons/identity`: Doctors and Clinicians (3.63M rows), IRS exempt orgs (1.98M). NPPES loader ready | NPPES when CMS's download page is back; reassignment (PPEF) |
| D. Code dictionary | not started | DuckDB query over the reduced Cigna tables: every CSTM-ALL / LOCAL code with counts and example rates |

How to run things (no Actions API needed): edit the last line of `ops/run-request.txt`
(any `ticdata` command), `ops/map-request.txt` (`<payer> <shards> [limit]`),
`ops/reduce-request.txt` (`<payer> <release>`), `ops/core-request.txt` (`<payer> <name>`),
`ops/kaggle-request.txt` (job folder), then commit and push. Reports land in
`datasets/ratecommons/ops/runs/`.

## Tracks, in the order they start

| Track | First deliverable | Runs while |
| --- | --- | --- |
| A. Parser v0 (Python) | Parse Cigna's 124 files (30 GB) on an Actions matrix into Parquet v0 | B is being written |
| B. Rust core | Byte-level record splitter + order-independent record hash; benchmark against A | A and C run |
| C. Identity tables | NPPES, provider enrollment (reassignment), Doctors and Clinicians, IRS exempt orgs -> Parquet on HF | A and B are coded |
| D. Code dictionary | Every `CSTM-ALL` / `LOCAL` code with counts and example rates, from A's output | B runs on samples |
| E. Code descriptions | HCPCS Level II from CMS as published; our own plain-English text for CPT | anything long runs |

Payer order: Cigna (30 GB) -> Aetna (8 TB) -> UHC insurer files (1 TB after dedup) -> UMR (89 TB, last, on the Rust core).

Where each payer runs (measured 2026-10-21, see DECISIONS):

| Payer | Kaggle, Europe session | Kaggle, US session | GitHub Actions (US) |
| --- | --- | --- | --- |
| UHC / UMR | yes: 84 MB/s, 0.33 GB/s JSON | yes: 101 MB/s | yes: 116 MB/s, 0.72 GB/s JSON |
| Cigna | no, geo-blocked | yes: 117 MB/s | yes: 93 MB/s, 0.68 GB/s JSON |
| Aetna | no, host unreachable | yes: 308 MB/s | yes: 488 MB/s |

Kaggle's region varies per session, so workers probe reachability at start and only
take jobs for payers they can reach (see DECISIONS).

Day-1 experiment before Track A scales out: whole-file download to runner disk, then
rapidgzip on the local file, against today's streaming 0.7 GB/s (see DECISIONS).

## Standing answers to the risks the design doc raised

- **CPT descriptions (AMA copyright).** We write our own plain-English description
  for each CPT code from public explanations, check it, and publish it as our text.
  It reads better for patients and AI anyway. HCPCS Level II text comes from CMS and
  is public domain. Payers' own `description` fields stay in the raw tables exactly
  as published. If the AMA objects to anything, we change it then.
- **Hugging Face storage ceiling.** Deduplicate first, Parquet with ZSTD, measure in
  experiment E3, and apply for Hugging Face's storage grant for impactful public work
  as soon as the first real dataset is up.
- **GitHub Actions terms.** Keep each run modest, put the UHC/UMR bulk on Kaggle,
  and move the repo to a dedicated organization if usage grows.
- **Payer front doors changing.** The daily manifest archive doubles as an alarm:
  a source that disappears or shrinks by more than 10% shows up in `checks/`.

## Open items for Harshu

- Data license for the published dataset (suggestion: CC0 for our derived tables).
- Pre-October-2026 history: any old raw files from the earlier pipeline worth importing.
