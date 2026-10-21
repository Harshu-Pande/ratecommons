# Build plan from day 1

Rule of the day: never wait on a running job. Start the long job first, then write
code for another track until it reports to `datasets/ratecommons/ops`.

## Morning: read what the smoke run measured

- `runs/*-gha-*/gha-bench.json`: rapidgzip GB/s on a 4-vCPU runner, the real
  compression ratio, and the download speed from each host (experiment E2).
- `runs/*-kaggle-*/`: whether Kaggle reaches the payers and how fast it is.
- These numbers set the fleet: how many runners per month, what goes to Kaggle.

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

| Payer | Kaggle (Europe) | GitHub Actions (US) |
| --- | --- | --- |
| UHC / UMR | yes, 80 MB/s | to be measured |
| Cigna | no, geo-blocked | to be measured |
| Aetna | no, host unreachable | to be measured |

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
