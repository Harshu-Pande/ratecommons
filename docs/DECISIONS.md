# Decisions and lessons

The design doc is the blueprint; this file records where reality changed it.
Newest first. One entry per lesson: what we saw, what we changed.

## 2026-10-22

- **Overnight orchestration without a chat session.** `orchestrate.yml` runs every 30 minutes:
  it dispatches the next reduce wave from `ops/waves.txt` once every shard of the wave has a
  successful map job, then the merge once every wave is in `reduced/`. It waits while a
  reduce runs and stops after a failed reduce until someone looks. `reduce.yml` accepts a
  full request line as a workflow_dispatch input. (The GitHub REST API is reachable from
  this environment now; GraphQL is not.)
- **Aetna waves reduce well.** Wave 1 (shards 0-7, 143 files): 4.62 billion map fact rows to
  242,692,818 distinct facts (19x), 17.6 GB reduced. Wave 2 (shards 8-23, 304 files): 6.08
  billion to 127,100,097 (48x), 9.1 GB, about 10 minutes per part. Fixes on the way: facts are
  grouped in hash slices of about 15 million rows after one streaming split pass (BLOB and
  VARCHAR aggregate states do not spill), DuckDB at 7 GB and 2 threads, dimension slices
  sized to about 300 MB. Waves of about 16 shards keep each reduce job's input near 25 GB.
- **Aetna wave 1 mapped: 143 of 143 files, shards 0-7 (the largest files).** 3.29 TB of JSON,
  5,043,986,639 negotiated rates, 261 GB of gzip in; 140 GB of map output (0.54x the gzip
  size, down from 1.3x before shard-level dimension seen-sets), so all of Aetna should need
  about 4.3 TB of shuffle space, inside the 7.8 TB limit. 35-45 minutes per 33 GB shard on
  one runner. Peak RSS 14 GB on the 14-file shard (DuckDB in the consolidation step now
  capped at 6 GB). Wave 2 (shards 8-39) launched while wave 1 reduces.

## 2026-10-21

- **Aetna wave 1, first try: parsing fine, consolidation ran out of disk.** All 8 jobs parsed
  their files (about 115 s per 2.3 GB file, RSS under 5 GB) but failed at the end: 14 files'
  outputs (about 42 GB) plus DuckDB's temp space for `DISTINCT ON` filled the 44 GB left.
  Now: the files of a shard share dimension seen-sets (`TIC_SEEN_DIMS`, like seen-blocks),
  so a later file does not rewrite price terms, lists, sets or codes an earlier one wrote;
  consolidation is a streaming concatenation with no dedup; and a chunk is flushed at 12 GB
  of staged output as well as at 25 files.
- **Cigna 2026-10 republished from the Rust re-map and verified again.** Blocks mode:
  1,242,508,174 map fact rows (down from 1,928,514,784 thanks to per-shard block dedup)
  reduce to 304,777,863 facts (68,421 more than the first release, from the provider-list
  `ps_id`); 130,324 provider lists, 1,659,804 provider sets. `verify` on the national OAP
  file: 103,603,271 facts, zero defects in every check including provider lists.
- **Aetna is mapped in waves because its map output would not fit Hugging Face's 7.8 TB.**
  The first real Aetna chunk (3 files, 2.2 GB gzip, 40 GB of JSON) produced 2.86 GB of map
  output, so all 8 TB of Aetna would leave about 10 TB of shuffle files. The map request takes
  a shard range (`aetna 252 0 0-59`); a wave is reduced and measured before the next starts,
  and its map outputs can be deleted once its reduce is published. Org usage before Aetna:
  0.13 TB public, 0.07 GB private. Measured on GitHub: about 19.5 GB of JSON per Aetna file,
  0.11 GB/s per runner before the provider-set changes (about 0.2 GB/s after), RSS 4 GB, and
  32% of the second file's records were blocks already written by the first.
- **Provider sets are stored as lists of provider lists (design change).** On Aetna a
  negotiated rate's provider set names about 1,800 provider groups, and 3,000 records
  produced 52,814 distinct sets: 1.54 GB of Parquet, 15 s of writer time, and the memory
  blow-up that killed the first Aetna jobs (exit 143 at 15 GB RSS). The design's identity is
  kept (`ps_id` = hash of the flattened, sorted group list) but the set is stored as the
  provider lists it was built from: new table `provider_list` (`pli_id` = hash of one
  reference's sorted group list, `pg_ids`), and `provider_set` holds `pli_ids`. Same 3,000
  records: 4.1 MB + 10.5 MB, writer time 0.2 s. Python and Rust match. Cigna's first
  release used the flat form; it is re-mapped with the Rust core so every payer has one schema.
- **`ps_id` hashes the set's provider lists, not its flattened groups.** Flattening meant
  touching about 2,000 group IDs for each of 53,570 new Aetna sets in 3,000 records (105
  million IDs, 4.6 s of 11.3 s of worker time). `ps_id` is now the hash of the sorted,
  distinct `pli_ids` (0.19 s). Trade-off: two sets with the same groups split differently
  across references get different IDs, so a few identical sets may not merge; the data is
  never wrong. Lists are written once per distinct reference in the references pass. With a
  fast path for place-of-service lists, the same Aetna sample runs in 6.8 s instead of 12.8 s.
- **Aetna jobs died after about a minute with exit code 143** (GitHub's runner kills the job
  under memory pressure), before any file finished. Likely cause: the Rust core queued up to
  256 whole records for its workers, and Aetna records can be very large. In-flight records
  are now bounded by bytes (768 MB, `TIC_INFLIGHT_MB`), the price-term and price-list seen
  sets are capped at 60 million IDs each, the record cache at 10 million records, and the
  core prints progress (JSON read, records, biggest record, provider groups, RSS) to the job
  log every 15 s so a killed job still shows how far it got.
- **Cigna 2026-10 verified end to end.** `verify` re-parsed the national OAP file (Rust core)
  and compared it with the published release: all 103,603,247 of its facts are published
  with its network in their set, no published fact claims that network without being in the
  file, and every price term, price list, provider set, provider group and code ID is
  published. Zero defects.
- **NPPES 2026-10 loaded** from NBER's copy of the CMS zip (`npi_raw_202610.zip`, files dated
  2026-10-11): 9,852,180 NPIs (330 columns), 1,274,332 practice locations, 864,775 other
  names, 608,236 endpoints. The weekly and deactivation files still need the CMS page.
- **Map outputs are uploaded per chunk of a shard, not per file.** Per-file folders meant
  about 25 objects per file: 155,000 for Aetna, and every reduce job would fetch about
  19,000 of them, against Hugging Face's few-large-files guidance and download rate limits.
  A shard now uploads one folder per 25 files (`map/<release>/<payer>/shard-NNN-CC/`):
  `metas.json`, `file_block` and `provider_reference` with a `file_key` column, dims distinct
  by ID, and 16 fact parts. Reduce reads both layouts (Cigna stays per file).
- **Byte-identical records are not parsed twice in a shard.** Near-duplicate files repeat
  most in_network records byte for byte. When two files carry the same provider_references
  (hashed in order as `refs_hash`), an identical record resolves identically, so the Rust
  core keys each record by xxh3-128(refs_hash + record bytes) and keeps, per shard, what a
  full parse produced (block, code, partition, counts, layout). A repeat costs one hash: only
  its `file_block` row is written. Records that raised any flag are never cached, so flag
  counts stay exact; a cached block whose facts were not written in this shard is parsed in
  full. Mid Cigna file mapped twice: second pass 3.1 s against 16.8 s, identical file_block.
- **Rust core speedups from a callgrind profile:** mimalloc, Fx hashing for maps keyed by
  hashes, no allocation per flag event, and the "several amounts" check reusing per-price
  hashes. Worker instructions down 24% on a small Cigna file.
- **GitHub Actions concurrency capped at 12 jobs (was 20) for map and reduce.** The design
  asks to keep it well below the 20-job cap to stay clear of the terms' gray zone. Measured
  cost: Aetna at about 0.25 GB/s of JSON per runner and 12 runners is roughly a day of wall
  time, so per-runner speed (and skipping byte-identical records across near-duplicate files)
  matters more than more runners.
- **Licensed code text was published by mistake, and is now split off before upload.**
  Cigna puts CPT short descriptors (AMA copyright) in `name` and `description` for
  94,234 of 116,566 codes; the first code table on `ratecommons/cigna` and the per-file
  map outputs in the public work bucket carried them. The design's rule is "publish code
  numbers, never republish CPT descriptions". `licensing.py` now withholds text for CPT
  (any 5-character CPT-shaped code, whatever the type label), CDT, revenue codes and the
  proprietary DRG groupers, including descriptions inside `bundle`; HCPCS Level II,
  MS-DRG, ICD, APC, HIPPS, NDC and payer-defined codes keep their text. To keep "discard
  no data", the raw text goes to a new private bucket `ratecommons/restricted` (map:
  `map/<release>/<payer>/<file>/code_text.parquet`; reduce:
  `release/<payer>/<release>/code_text.parquet`) before the redacted table is uploaded,
  and `code_id` is unchanged (it hashes the raw text). Rows carry `text_withheld`.
  The 124 Cigna map outputs and the published code table were rewritten; the old
  version still sits in the dataset's git history until the history is squashed.
- **NPPES: the CMS download page stayed "down for maintenance until further notice".**
  The NBER mirror (data.nber.org/npi/zip/) keeps byte copies of the CMS monthly and
  weekly source zips (newest processed month listed: August 2026). The loader now falls
  back to the newest monthly zip there and records the mirror URL as the source.
- **Reduce: list aggregates over 120 million rows ran out of temp disk (81 GB free).**
  `list(DISTINCT network_id ORDER BY network_id)` per fact makes DuckDB buffer every
  input row for the ordered aggregate. Network sets are now grouped by fixed-size,
  order-free keys: `bit_xor` of the two 64-bit halves of each member network ID plus
  the member count, over distinct (fact, network) pairs. The published `ns_id` is
  unchanged (md5 over the sorted network IDs), computed once per set from one
  representative fact, and every set is checked to have as many members as its key
  says. In blocks mode a fact found in one block takes the block's set directly; only
  facts found in several blocks are exploded to (fact, network) pairs.
- **First full map run: Cigna October 2026, 124 of 124 files parsed, 0 failures.**
  1,928,514,784 negotiated rates in 30,297,670 billing-code records, from 1,237,558
  provider references. 17.6 runner-hours on 40 shards (about 78 minutes wall time at
  20 at a time). The largest files (1.6-1.8 GB, about 35 GB of JSON, 105-120 million
  rates each) took 45-75 minutes and peaked at 10.1 GB of memory, inside the 16 GB
  runners. Every file uses `provider_references`; versions 2.0.1 (122) and 2.0.0 (2).
  Flags seen: 2,960,698 price lists with several amounts under identical terms,
  260,368 provider groups with a stray `0` among real NPIs, 183,295 duplicate groups,
  17,328 unresolved provider references, 5,028 TINs needing trimming, 1,731 placeholder
  amounts ($0.01 or less). The six `localplus` / `az-localflex` variants each carry
  116-120 million rates and almost the same counts: near-duplicates, as the Duplicate
  files tab predicted.
- **Experiment E7: the Rust core on Cigna's national OAP file (34.7 GB of JSON).**
  zlib-rs inflated it at 1.9 GB/s on one GitHub core (18 s), faster than rapidgzip;
  the byte-level splitter ran at 0.69 GB/s; splitting plus a naive serde_json `Value`
  parse on 3 threads ran at 0.30 GB/s (117 s) against 2,850 s for Python v0, about 24x.
  Counts match Python exactly (66,734 references, 1,781,542 records, 104,870,647 rates).
  Decompression is not a bottleneck anywhere; the parser is, and typed parsing should
  move Rust well past 0.3 GB/s.
- **Experiment E2b: download whole files, and use cores for files, not inside a file.**
  On a GitHub runner, 8 parallel 64 MB range windows downloaded at 255 MB/s (Cigna
  national OAP, 1.59 GB in 6 s) and 281 MB/s (UHC P3, 15.5 GB in 55 s), about 2.5x
  one stream. rapidgzip on the local file gave 0.83 GB/s of JSON with 1 thread and
  0.67 GB/s with 4 (UHC P3: 306 GB of JSON in 6.4 min). Parallel decompression does
  not pay on these files, so the plan is: whole-file download, one decompression
  thread per file, several files per machine. UHC P3 is 306 GB of JSON (19.7:1).
- **Parser v0 (Python) runs at about 10-13 MB/s of JSON** after caching and is for
  Cigna only (about 0.5 TB of JSON). Aetna (about 72 TB of JSON) and UHC need the
  Rust core; its target is to parse at decompression speed, about 0.8 GB/s per file.
- **Parse memory.** rapidgzip's chunk cache cost about 2 GB per open file, so the
  Python parser reads gzip with zlib (the parser, not inflate, is the bottleneck).
  Price terms and price lists stream to disk with bounded "recently seen" sets;
  a 62 MB Cigna file now peaks at 2.3 GB (was 4.6 GB).
- **Identity sources loaded** to `datasets/ratecommons/identity`: Doctors and Clinicians
  (3,630,233 rows, release 2026-10) and IRS exempt organizations (1,975,975 rows).
- **NPPES bulk download was down for maintenance (07:14 UTC).** `NPI_Files.html`
  said "This site will be down for maintenance until further notice" and the October
  zip returned 404 (a cached copy of the page still listed it). Track C started with
  Doctors and Clinicians and the IRS exempt-organization file; the NPPES loader
  falls back to the documented file name pattern and is retried daily.
- **`run.yml` failures must fail the job.** A `ticdata ... | tee` pipeline reported
  success after a crash; the step now sets `pipefail`.
- **Kaggle's exit country changes from session to session; probe it, never assume it.**
  The two runs launched from here exited in France and the Netherlands, and could
  reach only UHC. The first run launched from GitHub exited in the US (Atlanta) and
  reached all three payers: UHC 101 MB/s, Aetna 308 MB/s, Cigna 117 MB/s. Rule:
  every worker checks its exit country and which payers it can reach before taking
  work, and only takes jobs for those payers. The UHC/UMR-only routing below was
  correct for those sessions, but it is not a fixed property of Kaggle.
- **GitHub Actions runner, measured (first smoke run).** 4 vCPU AMD EPYC 9V45,
  16.4 GB RAM, 91 GB free disk (not 14 GB), egress US (Dallas). All three payers
  reachable: 64 MB-window reads at 116 MB/s (UHC), 488 MB/s (Aetna), 93 MB/s
  (Cigna). Cigna's national-oap file (1.59 GB, 34.7 GB of JSON, ratio 21.8)
  streamed and decompressed in 51 s.
- **Streaming through Python wastes rapidgzip.** Over our HTTP file object, 4-thread
  rapidgzip gave 0.68-0.72 GB/s of JSON, the same as single-thread zlib on the
  same bytes (0.74 GB/s). Every block crosses the Python file object under the GIL.
  First experiment on day 1: download whole files to local disk (91 GB free), then
  rapidgzip the local file. This is also the design doc's full-download-first rule.
- **No long-lived Hugging Face token in GitHub.** Workflows use Hugging Face Trusted
  Publishers: the job's GitHub OIDC token is exchanged for a one-hour token scoped to
  one dataset or bucket (`hfio.token_for`). `raw-manifests`, `ops` and the `work`
  bucket each trust `Harshu-Pande/ratecommons` on branch `main` (set in each
  resource's Hugging Face settings). A new dataset or bucket needs the same entry.
  An `HF_TOKEN` secret, if ever added, still takes precedence.
- **Agents start runs by committing, and read results from Hugging Face.** The
  session's GitHub access cannot call the Actions API (dispatch, secrets, run
  logs). So each workflow also runs on a push that edits its `ops/*-request.txt`
  file, and every job writes its reports to `datasets/ratecommons/ops`.
- **Workers are routed by what they can reach, not just by CPU.** The first Kaggle
  run (4 vCPU, 32.9 GB RAM, egress in Europe: CloudFront POP `CDG50`) showed:
  - UHC works: 80.5 MB/s from `mrfstorage.uhc.com`, faster than our US test box.
  - Cigna is geo-blocked: CloudFront answers 403 "configured to block access from
    your country" for the table of contents and every file behind it.
  - Aetna is unreachable: Kaggle's resolver returns `127.0.0.1` for
    `mrf.healthsparq.com`, so the connection is refused.
  So Kaggle takes UHC and UMR (the 89 TB bulk, all on UHC's host), and Cigna and
  Aetna go to US-based workers (GitHub Actions).
- **Kaggle benchmark (UHC P3 file, 4 vCPU).** rapidgzip produced 20.1 GB of JSON
  from 1.07 GB compressed in 61 s: 0.33 GB/s of JSON, ratio 18.7. Download alone ran
  at 84 MB/s, so decompression, not the network, is the limit (about 18 MB/s of
  compressed input). Each Kaggle session has 1.1 TB of free scratch disk (20.9 GB
  in `/kaggle/working`), so downloading whole files first is practical there.
  Consequence: UMR cannot be fully decompressed by brute force (about 1.7 PB of
  JSON); the tail-fingerprint dedup before download, and later the Rust splitter,
  carry the plan. Every report now records the
  worker's exit country (`machine().egress`) so this is checked, not assumed.
- **Lightning AI and Modal are out for now.** Lightning is not accepting new
  accounts; Modal requires a card. Neither is in the plan until that changes.
- **No `If-Range` on range requests.** Aetna's BunnyCDN reports ETag
  `"6ac42905-426438df"` (mtime-size), while a response that came from its Google
  Cloud origin reported `"-CI6x1vb2o5cDEAE="` for the same file. An `If-Range` the
  origin does not recognise turns a range request into a full-file `200`. Object
  identity is now checked by the total size in `Content-Range` (and the gzip tail
  fingerprint), never by ETag.
- **Never read a `200` body when a range was asked for.** UHC's Cloudflare front
  answered 6,209 of 7,312 first tail requests with the whole file; the second request
  returns `206`. `net.fetch_range` closes the connection at once and retries; the
  tests in `tests/test_net.py` simulate exactly this server.
- **One name, one config file.** Every Hugging Face repo and bucket name comes from
  `project.toml` so the project can be renamed without code changes.
- **Daily raw-manifest archive starts before any parsing.** Payers keep no history,
  so the indexes are archived from day 0; only changed sources are committed.
- **Workers report to Hugging Face, not to chat.** Every job writes JSON reports to
  `datasets/ratecommons/ops`, readable from any session.
