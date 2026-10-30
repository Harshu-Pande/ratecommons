# Decisions and lessons

The design doc is the blueprint; this file records where reality changed it.
Newest first. One entry per lesson: what we saw, what we changed.

## 2026-10-30: shards resume, stop before the job limit, and can be balanced by file count
- Blue batch 1's last shard got 3,251 files of 5.8 GB (Excellus' 2,556 small `.json.zip` files among them): the plan
  balances bytes, but each file costs ~7 s (download, Python parser for zip). It parsed 2,675 in 5 hours and was
  heading for the 350-minute job limit, after which a plain re-run would have started from zero.
- `run_shard` now resumes: files already in this shard's uploaded chunks (their metas.json) are skipped and new chunks
  are numbered after the existing ones. A time budget (`TIC_SHARD_BUDGET_MIN`, 320) stops starting files before the
  job limit; unstarted files go in the status file as failed, so the shard stays unmapped until a re-run finishes it.
- `plan --file-mb N` (map-request word `perfile=N`) adds a per-file cost when balancing. Opt-in: a re-plan of a payer
  must keep the shard contents of plans already mapped (UHC's 1,024 shards).
- map-request words after the 4th are now `key=value` in any order, and `plan=<path in the ops dataset>` reuses a stored
  plan as is, so retrying shards of a `match=` plan keeps exactly the files they had.

## 2026-10-29: BCBS IL/TX and Anthem get every code for main networks; wide lists split per state
- BCBS main networks: every TN home family + the 3 largest IL (PPO, Blue Options, TraditionalBlue) and TX (Blue
  Choice PPO, Blue Essentials, ParPlan) home families (RC_BCBS_MAIN_PLANS). Pack: 309M rate rows, 644M set -> list
  links, 17 GB; 22,821 codes in the app. Two OOM fixes: group states from distinct (group, state) pairs (serving.py);
  the per-group display summary as its own step with 2 threads per state (cloudpack.py).
- Anthem: every code for its 5 largest families (29,340 codes). Its lists are wide (Indiana: 2,731 lists of >5,000
  groups hold 2/3 of the rows), so states over 2M list -> group rows are split: narrow lists per code bucket
  (plipg/<t>/<b>.parquet) + one file per wide list (biglist/<pli>.parquet, index biglists.parquet). The app fetches
  only the lists a question uses (Indiana 99213: 3.5 s; it failed before on a 706 MB file).
- market_distribution falls back to every place of service when no office-setting rate is published (Anthem prices
  27447 only for facility places of service).

## 2026-10-29: the reduce chain blocks per payer; a merge is redone when its waves hold more files
- A wave waiting for its shards used to stop the whole chain: BCBS wave 4 (other Blue companies, added after the BCBS
  merge) would have stalled every UHC wave, or waited behind 86 of them at the end of waves.txt. Now a payer waiting
  for shards, or a merge waiting for its waves, only skips that payer's later lines.
- `merge_done` also compares the release's files (rows of source_file.parquet) with the files of its waves (each wave's
  metas.json), so the added wave re-merges BCBS; Aetna 6,229/6,229, Anthem 1,002/1,002, BCBS 1,911/1,911 today.
  AUTO_PACK then rebuilds serve -> cloud -> shop after that newer merge. bcbs joins `STATUS_REQUIRED`.

## 2026-10-29: the other Blue companies' own networks: where they are, and how little is new
- Research (index host, reachability, distinct own files and gzip size of the fully insured indexes, measured from a Claude
  session on 2026-10-29; self-funded employer indexes repeat the same networks):

  | Company (BLUE_OWN key) | Index host / kind | New files | GB |
  | --- | --- | --- | --- |
  | Blue Shield of California (bsca) | HealthSparq `latest_metadata.json` | 939 | 1,520 |
  | BCBS Arizona (bcbsaz) | HealthSparq | 508 | 1,219 |
  | Blue Cross NC (bcbsnc) | `mrfmftprod.bcbsnc.com/.../non-aso/<date>_..._index.json` (dated) | 10 | 38.5 |
  | BCBS Michigan (bcbsm) | Sapphire hub `tocs/<YYYYMM>/<YYYY-MM-01>_<slug>_index.json` | 10 | 18.4 |
  | Horizon NJ (horizon) | Sapphire hub | 52 | 12.3 |
  | Florida Blue (floridablue) | CloudFront TOCs (static) | 16 | 6.7 |
  | BCBS MN (bcbsmn) | `mktg.bluecrossmn.com/mrf/<year>/<month>-01_..._index.json` | 342 | 4.0 |
  | BCBS Louisiana (bcbsla) | Sapphire hub | 16 | 3.7 |
  | Premera (premera) | HealthSparq | 41 | 3.6 |
  | Excellus (excellus) | HealthSparq (TOCs only; files are `.json.zip`) | 2,562 | 2.3 |
  | BCBS OK/NM/MT (bcbsok, bcbsnm, bcbsmt) | HCSC landing pages, Azure blob TOCs | 18 | 1.3 |
  | Blue KC, IBX (QCC/KHPE/IAC), BCBS ND, WY, CareFirst, Highmark PA/BSPA/DE/WV/WNY/NENY, AL, AR, Wellmark, Capital, NE | Sapphire / GCS monthly / Highmark hub / scrape / HealthSparq | ~800 | ~4 |
  | BCBS Mississippi (bcbsms) | static TOC | 0 | 0 |

- Highmark's hub (`mrfdata.hmhs.com`, a static page whose script builds `files/<code>/<st>/inbound/local/<YYYY-MM>-01_
  <name>_index.json`) also lists NE, AZ, ID, FL, MN, LA and IBC NA under `363/pa`: Highmark-administered alliance products,
  not those companies' networks; left out. HealthSparq looked session-only in its web app (API "User object was not found
  in the session"), but its public egress `<insurer>-egress.nophi.kyruushsq.com/prd/mrf/<INSURER>/<BRAND>/
  latest_metadata.json` (the path Aetna's discovery uses) answers for all seven Blues there; no sign-in needed.
- A Blue company's BlueCard files (`<YYYY-MM>_<plan>_<prefix>_in-network-rates`) are its own networks as the other Blues see
  them, and HCSC's listing already has 941 of them: Highmark PA's index lists 796 files, 782 of them already ours. So most
  of each company's "own networks" were in the release already; the new data is its local products (~100 GB, BSCA and
  AZ aside) plus the few BlueCard names HCSC does not list (CareFirst 35, AL 29, Highmark PA 14). Rule in `bcbs()`: skip a
  name already listed, skip BlueCard names of another month (several indexes already list November's), keep the rest.
- Not reached from a Claude session, retried from a runner: BCBS Massachusetts (TLS fails through the session proxy),
  BCBS Kansas (`mrf.secure.bcbsks.com` answers 403), Regence (landing page 404 to this client). Not located yet: BCBS SC
  (myhealthtoolkit app), Vermont (`bluecrossvt.org/documents/toc-json`), Rhode Island, HMSA, Blue Cross of Idaho.
- Two companies list different files under one name (Highmark PA / Blue Shield PA, 59 names); since a map key comes from
  the name, the second gets the company in front (`listed_name` keeps the original). HCSC's Illinois page linked a dated
  index that 404s (2026-10-23); `_hcsc_index_urls` now falls back to the newest index of that name from the last 14 days.
- `match=by:<company>` plans every file one company lists. Planned as bcbs shards 28-33 with `release=2026-10` (some
  companies date their files 2026-11-01; the release is the month we collect).

## 2026-10-29: big fact parts are downloaded and sliced in batches
- UHC wave 3's reduce lost 14 of 16 fact runners to a full disk ("No space left on device" even for the runner's
  own log): ~44 GB of map facts per part (wave 1: ~32 GB), downloaded whole and then copied into hash slices, so
  ~88 GB sat on the runner's 104 GB at once.
- A fact part over 20 GB (`RC_BATCH_SPLIT_BYTES`) is now fetched in ~12 GB batches; each batch is sliced into
  `fact_split-XX` (DuckDB `FILENAME_PATTERN 'b<n>_{uuid}'`, so batches append) and deleted before the next.
  The slice count comes from the first batch's rows per byte plus 10%. Same wave output (test).
- The batched split was not enough: the re-run still filled the disk inside the per-slice loop, because the
  sliced input (~44 GB) stayed until the end for one query (the networks of each set's representative fact) while
  the merged facts grew beside it. Merged facts now keep `blk` (their block, when they have one) and multi-block
  facts' (fact, net) pairs go to `multi_dir`; members come from those, and each slice is deleted once processed.

## 2026-10-28 (night): the app's rate query narrows hop by hop, with integer keys, in price slices for heavy codes
- With Aetna's every-code pack, office visits in Texas (5.5M price rows, 34M set -> list links in the state) and head
  CT in Tennessee ran the 1.7 GB function out of memory: the query expanded sets to groups before narrowing.
- `_rows` now goes prices -> lists -> groups with DISTINCT at each hop, a price as a 64-bit hash of its fields and a
  product as a small int (fields joined back at the end), and codes with more than RC_SLICE_ROWS (600k) price rows
  run in price slices (pid % n) into a shared table. Live: Aetna 99213 TX by product 86 s cold, 70450 TN 18 s,
  BCBS TN 99213 ~1 s. A plain DuckDB TEMP table is per connection; the app's cursors each are one, so it is a table.

## 2026-10-28 (evening): main-network packs per payer; Anthem's provider lists are too wide for the app layout
- Main networks are whole network families (every part file with the same app label): BCBS TN posts Network S as
  32 files, each its own network id; picking the "20 largest networks" had picked 20 parts of S and P.
- BCBS: every code for Tennessee's 7 home networks (IL/TX home networks: 1 billion set -> list links, a runner's disk
  is too small; they need a split build). Aetna: every code for its 20 main file groups (45 GB serving pack, 391M
  rate rows, 797M set -> list links). Anthem: lists average 1,139 groups (9.7 billion list -> group links in the
  release); with 20 main families the pack's list -> group table was ~2.2B rows and filled the disk; with 5 it built
  (769M rows) but the cloud pack's per-state plipg files reached 706 MB (IN), more than a Vercel function's /tmp.
  Anthem is back on the common-services pack until plipg gets a layout a query can read in pieces.
- The app refuses any file over 150 MB (RC_FILE_MB) and always removes partial downloads: one oversized file had
  filled /tmp and broke every query on that instance.

## 2026-10-28: a broken single-GET download resumes with Range; the orchestrator re-maps only missing shards
- UHC wave 3, shard 32: a 15 GB UMR file broke after 9.3 GB and 45 minutes (`ChunkedEncodingError`,
  IncompleteRead) on the single-GET path, which had no retry. It now resumes from the bytes on disk with a Range
  request (or starts over if the server answers 200), up to 5 tries; the result records `resumes`.
- The orchestrator then re-ran all 12 shards of the wave for that one file. `start_maps` now dispatches only the
  wave's unmapped shards.

## 2026-10-28: a UHC shard is mapped only when its run wrote its status file; reduce refuses unfinished waves
- The orchestrator dispatched UHC wave 3's reduce (run 40770018611) while the wave's map was still running: every chunk
  of a shard uploads its own metas.json, and `mapped_shards` counted a shard as mapped once its first chunk landed.
  Reduced, the wave would have been missing most files, and `clean()` would then have deleted their map output.
- For payers in `pipeline.STATUS_REQUIRED` (uhc), a shard counts only when `shard-NNN-status.json` (written at the end
  of each shard run) exists with no failures. The reduce workflow's args job runs `ticdata wave-ready` for wave
  requests and stops before any reduce job when a shard is unfinished.

## 2026-10-28: wave outputs are not sorted; the sliced copy is freed before the last write
- UHC wave 1 (12 shards, ~32 GB of map facts per part): 9 of 16 fact parts filled the runner's 104 GB of disk in the
  final `COPY ... ORDER BY` (DuckDB spill: "max_temp_directory_size"), with the sliced input copy, the merged facts
  and the sort spill on disk at once. Wave outputs are read only by the merge, which sorts, so they are written
  unsorted; and the sliced copy is deleted once network sets are resolved.

## 2026-10-28: serving packs for the big payers hold common services only, streamed from the release
- The BCBS serving pack ran out of disk (110 GB release on one runner). Measured from Parquet footers: BCBS has
  3.7 billion provider set -> list links (5M sets) and 940M facts; Aetna 41.8 billion links (207M sets), 2.94B facts
  and 9.7B network-set entries. A full per-state pack of either does not fit free runners or storage.
- CareCompass's 62 codes plus CSTM-ALL (flat all-services contracts) are ~0.5% of the facts: ~24M links for BCBS,
  ~320M for Aetna. `serve_jobs.prefilter` streams the release one file at a time (download, keep matching rows,
  delete) into a small release folder; `build_pack` runs on it unchanged. Cigna stays a full pack (FULL_PACK).
- The pack records `code_subset`; the cloud pack copies it into meta.json, and the app adds a note whenever a
  payer's pack lacks an asked code, so it never reads as "no published rate". Full packs for the big payers need
  a distributed build (per state or per code slice) and a storage budget; not done yet.

## 2026-10-28: big merges are sliced: fact parts by fact_id hash, provider_set across 8 jobs
- Aetna's merge (16 waves) failed in every fact part: DuckDB's `GROUP BY fact_id` over ~9.5 GB of wave facts per
  part ran out of 6.5 GB. `merge_part_local` now cuts a part into hash slices of fact_id (~600 MB each,
  `RC_MERGE_SLICE_BYTES`); every row of a fact is in one slice, so each slice merges alone, then one sorted COPY
  writes the part. Same facts and network sets (test). Each slice needs its own temp file name: DuckDB applied a
  reused file's Parquet statistics to its new content ("perfect hash aggregate ... statistics corrupt").
- dims-provider_set lost its runner after an hour: Aetna's wave provider sets are 137.6 GB, past one runner's disk.
  A merge now runs `dims-provider_set.<j>of8` jobs; each downloads every input in batches but keeps only slices
  i % 8 == j. Streamed batches are sized to ~64 MB of rows instead of 500 rows.
- The sliced fact merge still ran out of memory resolving network sets: merged set keys recur in every slice and
  their member lists were aggregated per slice. Now each slice only records (merged key -> wave keys) for one
  fact per key; those mappings are deduplicated and resolved into member lists in hash slices of the key
  (`RC_SET_SLICE_ROWS`, 2M), and facts join a narrow key -> ns_id table.
- Note: a network is a file's content identity, so byte-identical files in two waves would fail the merge's
  set check (loudly); not seen so far.

## 2026-10-28: every bucket download takes a fresh OIDC token
- Aetna wave 16 dims-price_term: the streamed split ran ~80 minutes (it refreshes its own token), then
  `reduce_dims` fetched the metas with the job's first token: 401 Unauthorized. `reduce._fetch` now exchanges
  a fresh token per 200-file batch when running on OIDC (the merge path had the same gap).
- The same split moved price_term 500 rows at a time (a size meant for BCBS provider sets): 83 minutes for one
  wave, so a 16-wave merge would pass the 300-minute job limit. Only provider_set/provider_list stream with
  pyarrow now; price_term/price_list split in 50k-row batches and are deduplicated per slice with DuckDB.

## 2026-10-28: single-file dims (provider_group, code) are joined from their slices with pyarrow
- BCBS wave 3 (HCSC's own networks): dims-provider_group deduplicated its slices, then ran DuckDB out of memory
  (6.5 GB) in the COPY that joins them into one `provider_group.parquet`. The join now streams through
  `consolidate.concat_parquet` (20k-row batches); same rows.

## 2026-10-28: packs start only after a successful merge run, and again after a newer one
- The failed bcbs merge (dims-provider_set OOM) had published rate_fact and source_file, which was all
  `merge_done` checked, so the orchestrator started `serve bcbs:dataset` on an incomplete release (07:35 UTC).
- `merge_done` now needs every merged table (provider_set, provider_list, price_list, price_term too).
  `packs()` follows the newest `reduce <payer> <release> all merge` run: it must have succeeded (or be the run
  calling the orchestrator from its last job), and serve/cloud must be newer than it, so a re-merge is packed again.

## 2026-10-28: HCSC's own networks belong to release 2026-10 (their file names say 2026-09); merge streams list dims
- 1,142 HCSC files (IL/TX own networks, 15.6 GB) are named `2026-09-12_...` (13 `-14`, 3 `-15`) but listed as
  current in October's index. `release_of` filed them under `map/2026-09/bcbs/`, so the 2026-10 waves and merge
  left them out (found by comparing the plan with the waves' metas.json). `ticdata plan --release` and a 7th
  map-request word `release=YYYY-MM` now stamp a release on planned files; they are re-mapped as bcbs shards 24-27
  (wave 3). The old `map/2026-09/bcbs/` output (60 chunk folders) is left for a clean-up step, not deleted by hand.
  Next month: HCSC's names will again lag the listing month.
- The bcbs merge's dims-provider_set ran DuckDB out of memory: the merge path used the DuckDB split, not the
  streamed one. Merge dims of list tables now go through `_fetch_split` + `dedup_stream` like the waves.

## 2026-10-28: a shard with a failed file is not "mapped"; each shard run writes shard-NNN-status.json
- Anthem shard 2 counted as mapped (its chunks had metas.json) although `NY_HXSQMEDDORC.json.gz` (5 GB) had failed
  in the Rust core: its wave would have been reduced without that file. Found by comparing the stored plan with
  every chunk's metas.json (shards 1 and 2 only; shard 70's nameless 2.8 KB index page parses as an empty file).
- `run_shard` now writes `map/<release>/<payer>/shard-NNN-status.json` (`{"files", "failed": [names]}`), rewritten
  by every run of the shard; `orchestrate.mapped_shards` leaves out shards whose status lists failures, and
  `parse-shard` exits non-zero so the job shows red. Rust failures record `rust_exit` (negative = signal).

## 2026-10-28: streamed dims dedup casts IDs to plain binary (Rust and Python map files mix)
- BCBS wave 1 dims (after the numpy fix): provider_set, provider_list and price_list failed in `dedup_stream`:
  `pa.unify_schemas` cannot merge the Rust core's `fixed_size_binary[16]` IDs with parse.py's `binary` (files that
  fell back to Python). DuckDB had read both as BLOB. dedup_stream now unifies on `binary`, inside lists too
  (DuckDB's `hash()` slices both types the same way); test `tests/test_reduce_stream.py`.

## 2026-10-28: the Rust core's reference pass flushes provider lists by id count, and holds each reference's ids once
- Anthem shard 1 (three NY files, `NY_HX*MED*.json.gz`, 5 GB gzip each) died in the Rust core at ~240 s, max RSS
  15 GB of 16, before any rate was written: 17 GB of provider_references (~48k groups, each reference listing
  thousands of them). RSS climbed ~0.4 GB per GB of references and spiked by ~8 GB whenever the main thread sent
  its batch of 20,000 provider lists to the writer (no size cap there, unlike the workers' 2M-id cap).
- The reference pass now sends provider lists every 2M ids (`TIC_PLI_BATCH_IDS`, counted as `ref_pli_batches`),
  and the lookup map and the provider_reference rows share one `Arc` of each reference's ids instead of two copies.
  Same tables and IDs (parity test with small batches); retry anthem shard 1.
- The retry still failed. Run locally under a 12 GB cap, the core aborted at the end of the file: provider_reference
  was written as one Arrow batch of every reference's ids. It is now written in batches of ~2M ids as well.

## 2026-10-28: list dimension reduce (provider_set, provider_list, price_list, price_term) is streamed with pyarrow
- BCBS wave 1: dims-provider_set and dims-provider_list ran DuckDB out of memory (6.5 GiB) in the hash-split COPY;
  BlueCard provider sets hold thousands of list ids per row.
- `split_stream` now slices each downloaded batch 500 rows at a time (slice = DuckDB `hash(key) % k` on the key
  column alone, so slices match the old ones) and `dedup_stream` keeps the first row per key within a slice,
  holding only that slice's keys in memory.
- Runners have no numpy (only what `pip install -e .` pulls): the streaming code uses pyarrow.compute and DuckDB's
  `.arrow()` only. Test new runner code in a venv with the pinned DuckDB and without numpy. Same output as `DISTINCT ON (key)`, since IDs are content hashes.

## 2026-10-28: chunk consolidation streams file_block and provider_reference too
- Anthem retry: 13 of 18 shards parsed every file, then ran out of DuckDB memory (7.4 GiB) in the chunk's
  `SELECT *, file_key ... UNION ALL` of provider_reference (Anthem references carry very wide NPI lists).
- Both tables now go through `concat_parquet` (pyarrow, batch by batch) with the file_key added per input file;
  same columns and order as before. The provider_group fallback (when DISTINCT runs out of memory) streams too.

## 2026-10-28: BCBS of Tennessee's own files come from its CloudFront index, added as shards 20-23
- bcbst.com/tcr links two directories on `d7k0rj9u1dp84.cloudfront.net`: `non_aso_directory.json` (one index,
  "BCBST Fully Insured" + individual/group EHB plans) and `aso_directory.json` (one index per self-funded employer).
- The fully insured index lists BCBST's own networks as `TCR_Output_JSON/<net>/<date>_890_<prefix>_in-network-rates_
  NNNN_of_NN.json.gz` (Network S 58A0, P 58B0, E 58M0, L 58Q0, Behavioral Health, Medical Dental, Teladoc; 116 files,
  2.8 GB) and every Blue plan's BlueCard files, but for next month (2026-11). Those BlueCard files are skipped: the
  release takes BlueCard files from HCSC's listing of the same month. Networks S and P are also BlueCard files
  890_58A0/B0; both copies are kept (the reduce dedups identical facts; labels say which is which).
- A GitHub runner's CloudFront edge served a stale `non_aso_directory.json` naming the 2026-09-27 index, which
  answers 403. Discovery now fetches the directory with a cache-buster, checks the named index, and otherwise probes
  `TCR_TOC_Output/NON-ASO/<date>_bcbst_index.json` for the last 10 days.
- Files found after a payer's map are planned on their own (`match=`) with `base=N`, so they get new shard folders
  (shard-020..023) instead of overwriting the mapped ones; waves.txt gets a wave for them before the merge.

## 2026-10-27

- **BCBS BlueCard provider sets are enormous: dims are concatenated with pyarrow, streaming.** BCBS North
  Carolina's 7.3 GB file yields 100,125 provider sets averaging 4,232 provider lists (max 102,890): 424M ids,
  a 4.6 GB `provider_set.parquet` from one file. DuckDB's COPY of it ran out of 7.4 GB even with byte-sized
  row groups. `consolidate.concat_parquet` copies a single input as is and streams several with pyarrow
  (`pre_buffer=False`, 1 MB buffers, no dictionary): 1.6 GB peak instead of 5.8 GB for reading alone.

- **BCBS BlueCard files end with a few bytes that are not gzip.** BCBS North Carolina's 7.3 GB BlueCard file is
  three gzip members (19.7 MB header/providers, 30.2 GB of rates, 2 bytes `]}`) followed by 8 stray bytes.
  `gzip -t` accepts it; flate2's `MultiGzDecoder` failed with UnexpectedEof after 42 GB of JSON. The Rust
  reader now walks members itself and stops at non-gzip trailing bytes, reported as `gzip_trailing_bytes`.
  After that panic the Python fallback ran on the same 30 GB file and took the runner down ~10 minutes
  later, so files over 2 GB no longer fall back to Python after a Rust failure (only zip input does).
- **Anthem chunk consolidation ran out of DuckDB memory (5.5 GB of 6) on its first shards**, after every file
  parsed. Consolidation now uses 2 threads, 8 GB, 250k-row groups, and keeps provider_group duplicates
  (the reduce dedups them) if the DISTINCT still runs out. map.yml `range` accepts a list ("0,1,8,12-14")
  to retry only failed shards.

- **New payers run hands-off to the app.** Payers `bcbs` and `anthem` have datasets (`ratecommons/bcbs`,
  `ratecommons/anthem`, trusted publisher set) and wave lines; once a merge lands, the orchestrator starts the
  serving pack, then the cloud pack (`prefix=serve/v2`), then a CareCompass rebuild (`AUTO_PACK`).
  CareCompass and the cloud app list a payer only when its cloud pack exists (`shop._published`,
  `payers_loaded`). Map runs now have one concurrency lane per dispatched payer plus one for pushed requests,
  so a request for one payer no longer cancels another payer's map. First BCBS shards parsed cleanly with the
  Rust core (BCBS Texas BlueCard 2 GB in 86 s).

- **Blue Cross Blue Shield: one BlueCard file per Blue plan network covers the country for 0.12 TB.** Every Blue
  plan's index lists, besides its own networks, the BlueCard files of all Blue plans:
  `<YYYY-MM>_<plan code>_<network prefix>_in-network-rates[_k_of_n].json.gz` on `<plan>.mrf.bcbs.com`
  (CloudFront, signed about a month). BCBS Illinois' index (32 MB, Azure blob `.../toc/`) names 113 such
  networks of 56 Blue plans, 0.12 TB in all (Anthem Indiana 30 GB, BCBS North Carolina 19 GB, BCBS Tennessee
  `890_58A0/B0/D0` 0.95 GB each, BCBS Texas `400_59C0/H0` 2 GB each). The same file name is listed by every
  Blue plan under its own subdomain, so files are keyed by name and fetched once. HCSC's own networks (IL, TX)
  add 1,143 files but only ~6 GB. Payer `bcbs` = HCSC IL/TX indexes; payer `anthem` = Anthem's index.
- **Anthem's index is 11.4 GB gzip of one JSON line; streamed with a regex in 8 minutes.** It repeats the same
  files once per employer (43.1M location references): 708 distinct own in-network files on Anthem's S3
  (`<ST>_<network code>MED<suffix>.json.gz`, ~0.8 TB, up to 5.3 GB each) and 294 BlueCard files that HCSC's
  index does not list (more networks per Blue plan, e.g. CareFirst BlueEssential). Descriptions name the
  BlueCard network ("BCBS Tennessee, Inc. : Network P") and are kept as labels. BCBS Tennessee's own
  index is not linked from its site; its networks come through BlueCard for now.

- **UHC flows map -> reduce -> delete, wave by wave (bucket has ~7.8 TB free).** The 256-shard map run
  would have written ~20 TB. Now `ops/waves.txt` lists 86 UHC waves of 12 shards (~1 TB of map output each);
  the orchestrator (`PIPELINE` in `ops/orchestrate.py`) starts a wave's map run itself (map.yml `range`
  input) when no map run is going and fewer than 2 mapped waves wait for reduce, and deletes every finished
  wave's map output (Aetna's too: 7,318 files of waves 1-9 at once). It runs on cron and at the end of
  every map and reduce run (cron alone fired once in ten hours). map.yml now cancels a running map when a new
  one starts, which only happens when a person pushes a map request over it. Reduced waves are small
  (Aetna: 18-47 GB per wave).

- **Full UHC map started (2026-10-27 evening).** Facts are content-hashed, so the reduce already stores a fact
  shared by many near-copy files once (with its network set); the real cost is parsing ~2,300 runner-hours.
  Plan: 1,024 shards (~90 GB gzip, ~2 h each) in size order, biggest first, run as four map runs of 256
  shards (`uhc 1024 0 0-255`, then 256-511, ...). Files with the same gzip trailer CRC32 + ISIZE (identical
  decompressed content, 555 of 6,824 files) are parsed once; the plan records `duplicates` {file: parsed twin}
  so their plan membership can be attached at merge. Old probe map folders (shards 0-7) are overwritten, not
  deleted; any leftover probe chunk holds facts of the same files, so reduce dedups them. Watch: map output
  is ~1 GB per GB gzip; reduce waves for UHC must be sized before the first wave line goes in `waves.txt`.

- **UHC products share most of their price facts (bottom-k sketch, k=20,000, 6 product files).** Normalized
  price facts of the mapped parts: Choice Plus C2 is 99% contained in a 0L Choice Plus file; two 0L/Select Plus
  TPA files have Jaccard 0.83; the Behavioral Health P3 file is 91% inside a 0L file; every small file is 68-99%
  inside some bigger one, while pairs of different networks overlap 36-64%. So storing each file as "its base +
  added facts - removed facts" (base = the most-containing file by sketch) should cut stored facts by well over
  half; whole-file dedup (4 TB of 93.8 TB) cannot. Next: fact-level store with per-file membership.

- **CareCompass v2 data: places, qualified clinicians, and Medicare evidence (`shop.py`).** The patient app needs
  prices per place, not per contract, and contracts carry no addresses. A place is a normalized practice address
  (street without suite/floor + ZIP5) from NPPES and Medicare's clinician directory. A contract's price shows at a
  place when one of its clinicians *whose specialty does that care* practices there (radiologists for readings,
  therapists for therapy...). This drops "ghost" rates (NPs and counselors carrying a group's CT fee schedule).
  Badges: confirmed (a qualified clinician billed the code or its 4-character family to Medicare), likely
  (qualified, no Medicare record: common in pediatrics), hidden (outside 0.15x-15x of the state's Medicare PFS),
  percentage (no dollar amount). Hospitals' reading groups come from CMS facility affiliations (radiologist ->
  CCN). Flat all-services contracts (UHC $200 per diem urgent care) are kept as a `FLAT` visit price.
- **No OR in big join conditions.** `JOIN ... ON a.code = b.code OR b.code = 'FLAT'` made DuckDB fall back to a
  nested-loop join and spilled 10 GB of temp files for one state. Flat contracts now join through a separate
  `qx` table (`UNION ALL` of per-code rows and one `FLAT` row per group/place/procedure).
- **Place x contract joins run one procedure at a time.** Tennessee's offers are 5-14M rows per payer before
  grouping (largest groups have 1,200 places); a single `GROUP BY ALL` with list columns ran out of 4 GB.
  Looping over the 56 procedures and inserting keeps each step small.
- **data.cms.gov rejects a browser-like User-Agent from our hosts (403)**; the default `requests` UA works.

- **The wave orchestrator now reads the bucket, not run history.** It found mapped shards by scanning the
  last 10 map runs' job names: UHC experiments pushed Aetna's map runs out of that window and mixed payers,
  and one failed page (HTTP 502) killed it. Mapped shards are now the shard folders with a `metas.json`
  in the work bucket. It also stopped the chain after any earlier failed run, even when called from a
  later successful one; a successful run now continues. Aetna's plan has 248 shards (0-247), not 252.

- **Cloud pack v2: provider sets split by code prefix.** A query needs only the provider sets priced for its
  codes, but `state/<ST>/pspli.parquet` held all of them (Aetna TX: 127 MB, 54.6M rows, for 3 networks;
  one code touches ~10k of 980k sets). Per-code files would total 5x the rows (275M for TX); per
  3-character code prefix they total 1.8x (98M) with the largest file ~1.4M rows. v2 writes
  `state/<ST>/pspli/<TYPE>/<key[:3]>.parquet` (+ `_cstm_all`), flagged by `"pspli": "bucket3"` in meta.json,
  under `serve/v2/` (built beside v1, then the app's `RC_DATA_URL` was switched). Aetna TX 70450
  distribution: 5.5 s cold with a 37 MB cache, where v1 needed the 127 MB file.

- **UHC near-copies are not byte copies; exact dedup saves only 4 TB.** Findings from `uhc_probe.py`:
  - UHC files are single-member gzip (no member starts in the last 1 MB of 6,775 of 6,824 files), so the
    gzip trailer's CRC32 + ISIZE fingerprints the whole decompressed file. 6,824 files give 6,269 distinct
    fingerprints: whole-file duplicates exist (C0 x47, P3 x30, C2 x17, C1 x13, dental and NDC files), but
    the representative set is still 89.8 TB of 93.8 TB.
  - The 465 "0L" (Choice Plus) UMR files have 459 distinct fingerprints. Their provider_references put a
    per-file `network_name` (the employer/plan label) in every record, number `provider_group_id`
    differently and list records in a different order; in the first 512 MB, about 75% of records are equal
    once the number and label are removed.
  - Grouping by product code and near-equal size gives 1,268 groups whose largest members total 11.8 TB.
    Mapping two 0L files (the generic HealthSCOPE Choice Plus file and HealthSCOPE's Tenet-in-Michigan
    variant, ~297 GB of JSON each, 19 min to parse on one runner) and comparing content-hashed facts
    (`uhc-compare`): 521.3M and 518.9M distinct (code, provider set, price list) facts, 518.8M shared.
    The variant lacks 2.5M (0.5%) of the generic file's facts and adds 0.16M, 44,650 of them the same code
    and provider set at another price (a carve-out). So near-copies are not copies: skipping them would
    drop real contract differences. Plan: parse every file once (unavoidable for exactness; ~20 min per
    15 GB file, ~2,000 runner-hours for UHC), but store each file as an exact delta (added and removed
    facts, new dimension rows) against its most similar already-stored file, chosen by a bottom-k sketch
    of its facts (`uhc-sketch`). Next measurement: similarity across product codes (0L, 58, TC, C0, SEL,
    P3, NXDT, C2), which decides whether a few bases can serve all 1,268 groups.
  - The earlier probe hung because it treated the first gzip member as the whole file
    (`decompressobj` stops at a member end); and UHC's Cloudflare front answers a first Range request with
    the whole 15 GB (`r.content` on it killed the runner). Both fixed.

- **Aetna provider_set dims outgrew a runner's disk, and the orchestrator did not notice.** Waves 6 and 7
  failed in `dims-provider_set` with "No space left on device" even with 105 GB free: the job held every
  downloaded input plus a full hash-sliced copy. `reduce_dims` now downloads the big list tables
  (`DIM_SLICES`) in batches of `RC_SPLIT_BATCH_BYTES` (12 GB), appends each batch to the sliced copy as
  zstd, and deletes the batch, so peak disk is about one copy. With that fix the job ran past an hour, and its upload
  then failed with 401: the GitHub OIDC exchange gives a one-hour Hugging Face token and the job fetched it
  once at the start. Uploads and later download batches now ask `token_for` again (it caches until expiry). The orchestrator called wave 7 "done"
  because it checked only rate_fact, code and metas; it now also requires every dims table.
- **AI clients cache tool lists; custom SQL is back, sandboxed.** ChatGPT kept calling `run_sql` from the old
  Mac app ("unknown tool run_sql"); re-adding the connector refreshes the list. The cloud app's `run_sql` takes
  any one DuckDB SELECT. Data comes in through table functions (`rc_rates`, `rc_rates_by_product`,
  `rc_medicare`, `rc_codes`, `rc_products`, `rc_groups`, `rc_group_npis`, `rc_nppes`, `rc_code_file`) that the
  engine resolves first: it fetches the needed small files and, for `rc_rates`, writes one Parquet per
  payer x state into a scratch folder. The user's query then runs on a fresh DuckDB with
  `allowed_directories` = cache + scratch, `enable_external_access=false`, `lock_configuration=true`, one
  SELECT statement only (checked by DuckDB's own parser), 1.1 GB memory, an interrupt at the time budget.
  No pyarrow (not on Vercel). `rc_rates` collapses payer products by default: Cigna CA for 4 codes was
  ~5.7M product-level rows and ran out of memory; without products it is 0.76M rows in 1.2 s. The user's
  "top radiology groups nationally on the 10 most common CPTs" runs on Vercel in 78 s (0.93M rows, every
  state). Function limit raised to 300 s.
- **The app runs in the cloud; the Mac is out of the loop.** Pre-joining rates to providers is not an
  option (a Cigna sample: one sixteenth of the codes in Missouri alone is 32.8 million provider-level
  rows, about 30 billion for all of Cigna). Instead `cloudpack.py` re-cuts each serving pack into small
  files in the public work bucket (`serve/v1/`): one Parquet per billing code (price fields inline, dense
  integer ids; most under 1 MB), five per state (set -> list, list -> group, group display, group -> NPI,
  group -> network), shared NPPES by state, an NPI -> state index and Medicare. Sizes: Cigna 75,130 files
  / 4.0 GB, Aetna (3 networks) 100,954 / 3.9 GB, UHC (2 files) 19,352 / 7.1 GB; builds 10-26 minutes.
- **Serverless app (`cloud/`)**: FastAPI on Vercel (`ratecommons-cloud.vercel.app`; the old
  `ratecommons-atticusfinch.vercel.app` now rewrites to it, MCP at `/mcp` and the old `/gradio_api/mcp/`).
  It fetches only the files a question needs from the bucket, caches them on the instance, and joins them
  with DuckDB. MCP is a small stateless JSON-RPC handler (no SSE). The deployed `api/index.py` is a loader
  that pulls `cloud/api/*` from GitHub at the commit in env `RC_CODE_REF`, so a release is: push, set the
  env var, redeploy. Measured from outside: 0.3-6.5 s per tool call (cold files), 1-3 s warm.
- **Vercel traps**: a Python project auto-detected as "fastapi" ignored `api/` and 404ed everything (set
  framework to null and use `api/index.py` + rewrites); `/:path*` rewrites drop trailing slashes.
- **UHC is 7,316 in-network files, 93.8 TB gzip** (mostly 15 GB files: 4,558 UMR files of ~14.9 GB,
  465 files of network "0L" at 15.0-15.1 GB). They look like near-copies; full parsing would be ~2 PB of
  JSON, so the plan is to fingerprint and cluster first and parse one representative per cluster.

## 2026-10-22

- **National Aetna by choosing networks, not states.** Facts of a few networks reference far fewer provider
  sets than all 140: three networks (Open Access Managed Choice, Tenet's Choice POS II) nationally give
  143,812,830 set -> list rows and a 5.9 GB pack, built in under 5 minutes (target
  `aetna:wave-1::Choice_60178,TENET`; serve targets are split on whitespace, so name fragments without spaces).
- **AI clients timed out (ChatGPT, 5-6 minutes).** Causes: Gradio ran one tool call at a time (queue
  concurrency now 6); a `billing_code IN (...)` list does not prune the code-sorted row groups, so
  multi-code lookups scanned whole rate tables (now one equality scan per code, UNION ALL); provider
  lookups now start from the provider's groups -> lists -> sets. New tool `provider_rates` (one provider,
  many codes, one call) and a `modifier` option (26/TC) on `market_distribution`. Through the Vercel
  gateway on the Mac, cold: 15 radiology codes for one NPI 13.5 s (was 70 s+), 5 urgent-care codes for one
  TIN 11.3 s, TC distribution 5.1 s. Running the three payers in parallel was slower on the 8 GB Mac.
- **Stable address without paid hosting.** Tailscale Funnel did not work out on Harshu's Mac. A Vercel
  function (`gateway/`) is the fixed front door and forwards to the Mac's Cloudflare quick tunnel, whose
  address it reads from HMAC-signed notes on an ntfy.sh topic (`space/tunnel.py`). App and tunnel are
  launchd agents, so a dead battery only means "offline" until the Mac is back. Two traps: Vercel's
  `/:path*` rewrite drops trailing slashes (MCP lives at `/gradio_api/mcp/`), and forwarding
  x-forwarded-host makes Gradio's MCP server call itself through the gateway (404 on queue/join).
- **Serving packs for interactive questions (`serving.py`, `serve.yml`).** The release tables
  are normalized for storage; "this code, in this state" needs another layout: rates (fact x
  price term) sorted by code in 50k-row groups, provider set -> list split by state, group ->
  NPI split by state (geography from NPPES by NPI and IRS exempt-org by EIN, never names),
  plus group -> network membership. Cigna's pack: 400,911,894 rate rows, 8.1 GB.
- **Aetna's provider sets are enormous.** Wave 1 explodes to 2,479,951,868 provider-set ->
  list rows for the sets its facts use; the pack ran a runner out of disk. Packs take an
  optional state list (`aetna:wave-1:MO,IL,KS`): only groups practicing there, their lists,
  and the facts of sets that reach them.
- **Hugging Face no longer hosts Gradio/Docker Spaces free** (402: PRO for users, Team for
  orgs; static Spaces stay free). The app (`space/`) runs on Harshu's Mac for now behind a
  Cloudflare quick tunnel (`~/ratecommons-app/start.sh`), with a 10 GB free-disk floor.
  Public hosting later means either PRO or re-cutting packs into small per-state/per-code
  files a serverless front end can fetch.
- **UHC first subset**: map accepts `match=` name filters; the UHIC Choice Plus C2 and
  Options PPO P3 files (15 GB gzip each) mapped to 28 GB and reduced into `ratecommons/uhc`
  (rate_fact 14.1 GB).
- **Medicare PFS**: PPRRVU columns are fixed by CMS (0 HCPCS, 1 MOD, 5 work, 6 NF PE, 8 F PE,
  10 MP, 25 CF); header detection by text failed because "HCPCS" itself looks like a code.
  State amounts use the mean locality GPCI of the state; 99213 national $95.19 (CF 33.4009).

- **Cigna dataset history is left as is (Harshu's call).** The current tables carry no
  licensed descriptor text; yesterday's first code table remains only in the dataset's git
  history. Not squashed.
- **Overnight check-in (09:36 UTC).** Map run for shards 40-251: 109 of 212 shards done, 0
  failed, 12 running. Reduce waves 3 (shards 24-39: 5.69 billion map fact rows to 79,590,344
  facts, 6.5 GB) and 4 (shards 40-55, dispatched by the orchestrator: 6.07 billion to
  93,049,737, 7.4 GB) succeeded. Reduced so far: 40.6 GB for waves 1-4 (751 files).
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
