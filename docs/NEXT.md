# Build plan from day 1

Rule of the day: never wait on a running job. Start the long job first, then write
code for another track until it reports to `datasets/ratecommons/ops`.

## Already measured (night before day 1)

- `runs/2026-10-21-gha-*/`: GitHub runner speed per payer, rapidgzip vs zlib.
- `runs/20261021-kaggle-*/`: Kaggle reaches UHC/UMR only; its speed and disk.
- How to start runs and read results without the Actions API: see DECISIONS
  (edit `ops/smoke-request.txt`, `ops/archive-request.txt`, `ops/kaggle-request.txt`).

## Status, day 1 (2026-10-21, evening)

| Track | Done | Next |
| --- | --- | --- |
| A. Map | Rust core default: 0.36 GB/s (Cigna) and 0.21 GB/s (Aetna) of JSON per runner, RSS 4.5 GB on Aetna. Provider sets stored as provider lists. Chunked uploads. Cigna re-mapped (124/124). Aetna wave 1 running: shards 0-7 of 252 (143 largest files, 261 GB gzip) | Measure wave 1 after reduce; plan the remaining waves against the 7.8 TB storage limit |
| Reduce | Fixed-size set keys; blocks mode; reads chunk layout | Cigna 2026-10 re-reduce running; then `verify` + `card`. Aetna: per-wave reduce, then a cross-wave merge (network sets of different waves are disjoint, so set keys combine by XOR) |
| B. Rust core | Parity with `parse.py`; mimalloc/Fx; record cache; byte-bounded queues; live progress | Price-term path (Aetna prices are ~76% unique) and record scanning |
| C. Identity | NPPES 2026-10 (via NBER), Doctors and Clinicians, IRS exempt orgs | NPPES weekly/deactivations when the CMS page returns |
| D. Code dictionary | `codebook` command | Run on Aetna (LOCAL codes) after its reduce |
| Licensing | Licensed descriptor text withheld; raw text private | Harshu to OK squashing the Cigna dataset history |

Scale note: an Aetna file holds about 33 million rates (20 GB of JSON); all 6,229 files are about
200 billion rate rows before cross-file dedup, and about 10 TB of map output.

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

- **CPT descriptions (AMA copyright).** Following the design's safe default, public
  tables never carry CPT (or CDT, revenue-code, proprietary DRG) descriptor text from
  payer files: `licensing.py` withholds it and the raw text is kept, as published, in the
  private `ratecommons/restricted` bucket (discard no data). We write our own
  plain-English descriptions for CPT codes later (Track E). HCPCS Level II text from CMS
  is public domain and stays.
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
