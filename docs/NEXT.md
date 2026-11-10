# Build plan from day 1

## Overnight 2026-11-10 (see DECISIONS)

Done: national hospital files (3,227 parsed, 2,242 hospitals, address fallback), percent-of-charges -> dollars with
the hospital's gross charge, claims-backed hospital figures override insurer rows >25% off, triangulation numbers,
apartment addresses excluded, imaging sites named for the scanning practice, every-code hospital normalization
running into hospitals/full/ (public dataset next: create `ratecommons/hospitals` and its Trusted Publisher entry).

Next:
- Publish hospitals/full as a dataset with a card (schema, sources, how files attach to hospitals).
- Unattached hospital files (~760): psychiatric/rehab hospitals are not sites (fine); for the rest match
  location_name + city within the state as a last resort, with a manual review list.
- Medicare Advantage copays from the CMS Plan Benefit Package files; MA networks from Plan Finder.
- Medicaid: "who accepts it" from MCO provider directories (FHIR Plan-Net where available).
- UHC: only part 1 is loaded; facility fees for UHC come almost entirely from hospital files until the rest merges.

## Patient data rebuild (started 2026-11-09; see DECISIONS 2026-11-09 evening)

| Track | Done | Next |
| --- | --- | --- |
| Site registry (`sites.py`, sites.yml) | National registry and capability evidence; shop/v2 live on ratecommons.org (query server RC_SHOP_URL default, app data URLs versioned) | Bump DATA_VERSION in carecompass/src/lib/data.js on each data release; random-sample audit of site precision per capability (web check of 100 sites each); add FDA MQSA mammography list and CLIA labs as sources |
| Releases | meta/version.json (written by the META job, last) is the release id; the app adds it to every data URL and the query server caches per id, so a data release reaches ratecommons.org with no deploy | Space RC_CODE_REF only changes for server code |
| Hospital price files (`hospitals.py`) | cms-hpt.txt crawl (4,242 locations / 3,516 files); JSON v2/v3 and tall-CSV normalizers; St. Louis pilot facility fees in src/ticdata/data/hospital_fees.json | Wide-CSV layout; attach files to sites by type_2_npi -> NPPES address (not names); national download/normalize on Actions into a `ratecommons/hospitals` dataset (needs the Trusted Publisher entry); triangulate with TiC (EIN + type-2 NPI) |
| Facility fees from payer files | none | Category rates (UHC CSTM CAT/MRI per diems, Cigna per diems) via a crosswalk; % of charges x hospital gross charge |
| Original Medicare | data located: PFS (have), OPPS Addendum B Oct 2026 (cms.gov/files/zip/October-2026-OPPS-Addendum-B.zip) | `medicare` payer in the app: hospital = OPPS (wage-adjusted) + PFS facility pro; office/IDTF = PFS non-facility; patient 20% after the $283 Part B deductible |
| Medicare Advantage / Medicaid | hospital files carry MA (all) and Medicaid (Mercy) plans | MA: hospital-file rates + PBP copays + Plan Finder / FHIR directories; Medicaid: "who accepts it" from MCO directories, MO HealthNet fee schedule |
| Office visits (live check 2026-11-09) | billing-evidence rule; clinics named for the billing practice | St. Louis Aetna 99213 still lists hospice, home-care, rehab and state-agency groups at $35-37: restrict visit sites to clinic sources (FQHC/RHC/clinic/group/urgent/hospital), drop groups whose main taxonomy is hospice/home health/agency, and check Aetna's $35 fee-schedule rows |
| Ghost rates (professional) | sites + capability remove most | per TIN x site plausibility: out-of-state reading groups, Medicare billing of the code family by the TIN's clinicians at that site |


Rule of the day: never wait on a running job. Start the long job first, then write
code for another track until it reports to `datasets/ratecommons/ops`.

## Already measured (night before day 1)

- `runs/2026-10-21-gha-*/`: GitHub runner speed per payer, rapidgzip vs zlib.
- `runs/20261021-kaggle-*/`: Kaggle reaches UHC/UMR only; its speed and disk.
- How to start runs and read results without the Actions API: see DECISIONS
  (edit `ops/smoke-request.txt`, `ops/archive-request.txt`, `ops/kaggle-request.txt`).

## Status, night of day 1 (2026-10-22, 03:30 UTC)

| Track | Done | Next |
| --- | --- | --- |
| A. Map | Cigna re-mapped with the Rust core. Aetna shards 0-39 mapped (447 files); shards 40-251 running (about 13 h at 12 jobs) | When the map run ends: reduce waves of ~16 shards (`aetna 2026-10 all wave=N a-b`) |
| Reduce | Cigna 2026-10 republished and verified (304,777,863 facts). Aetna waves 1-2 reduced (242.7M and 127.1M facts per wave), wave 3 (24-39) running | After the last wave: `aetna 2026-10 all merge`, then `verify` on one Aetna file, `card`, `codebook` |
| B. Rust core | Provider lists; ps_id over lists; shard-level dim seen-sets; 0.2 GB/s per runner on Aetna | Price-term path |
| C. Identity | NPPES, DAC, IRS EO for 2026-10 | NPPES weekly when CMS returns |
| Licensing | Withheld text; private copies | Harshu chose to leave the Cigna dataset history as is (Oct 22) |

Reduce wave plan for the rest of Aetna: 40-55, 56-71, 72-87, 88-103, 104-119, 120-135, 136-151,
152-167, 168-183, 184-199, 200-215, 216-231, 232-251 (waves 4-16), then merge.

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
