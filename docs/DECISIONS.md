# Decisions and lessons

The design doc is the blueprint; this file records where reality changed it.
Newest first. One entry per lesson: what we saw, what we changed.

## 2026-10-21

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
