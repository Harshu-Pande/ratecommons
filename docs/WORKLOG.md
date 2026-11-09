# Work log shared by the two sessions (see CLAUDE.md, "Two sessions share this repo")

Newest first in each section. One line per item: `YYYY-MM-DD HH:MM CT [session] what (files or runs)`.

## Claimed
- 2026-11-09 15:10 CT [app] INCIDENT: Vercel Fluid Active CPU 4h28m/4h (ratecommons-cloud). Engine CPU cuts (cloud/api)
  and a persistent query server on a Hugging Face Docker Space (cloud/server/); Vercel keeps static site + rewrites.
- 2026-11-05 18:15 CT [app] Worker boards for helpers' forks (first: Seyun): an assignment file per helper that Harshu
  edits any time, read every 15 minutes by the helper's fork; compute runs on the fork's GitHub Actions with no AI,
  AI tasks run in the fork with a turn cap on the helper's Claude subscription. Files: workers/ (new),
  .github/workflows/worker.yml, worker-job.yml, worker-ai.yml (new; they never run in this repository),
  docs/ONBOARDING.md, fork guards on shop/cloud/serve. Compute kinds (map, reduce, kaggle) are the pipeline's: see Requests.
- 2026-11-03 11:30 CT [app] (parts 1 and 3 done 2026-11-04, see Done) (1) Every code for each Blue company's largest home networks and more Anthem families
  (main_networks in src/ticdata/serve_jobs.py, serve/cloud/shop runs). (2) UHC into the apps part by part: serving
  packs from reduced/2026-10/uhc/part-P as each part merges, labelled partial (serve_jobs.py pack for part sources,
  cloud/api/_rc.py). (3) Why BCBS Michigan has no patient prices (shop.py). (4) Repo set-up for a second contributor
  (Seyun): docs/ONBOARDING.md (fork-based worker; see Requests), status page. Pipeline: tell me here if any of this collides with your work.
- 2026-10-29 13:50 CT [pipeline] BCBS: other Blue companies' own in-network files (research -> discover.py -> new bcbs
  shard ranges). Files: src/ticdata/discover.py, ops/map-request.txt, ops/waves.txt, docs/DECISIONS.md. 15:10 CT:
  batch 1 (28 companies, 3,420 files, 96 GB) mapping as shards 28-33 (run 40943309473), then wave 4 and re-merge.
- 2026-10-28 10:35 CT [app] Serving packs that fit a runner for BCBS and the full Aetna release (and Anthem
  next), then cloud packs and CareCompass rebuild (src/ticdata/serving.py, serve_jobs.py, serve.yml, cloud.yml,
  shop runs). 11:00 CT: common-services packs (4ef9e1f); serve runs dispatched for bcbs and aetna.
  BCBS done: serving pack (943 networks, 6.7M rate rows), cloud pack, CareCompass rebuilt (shop all 16:10). 11:45 CT:
  serve anthem:dataset dispatched by the app session (Anthem merged 10:04 CT; the orchestrator was waiting on a reduce).
  20:30 CT: BCBS = every code for TN's 7 home networks (live). Aetna = every code for 20 main groups, cloud pack
  running. Anthem back to common services (main networks' plipg too big for the app). See DECISIONS 2026-10-28 evening.
  22:20 CT: Aetna every-code pack live (100,666 codes, 20 main groups); app query rewritten (released c0f374b).
  10-29 18:00 CT: BCBS every code for TN + IL/TX main networks (22,821 codes) and Anthem for 5 main families (29,340
  codes) live; wide-list split layout. Storage decision (a/b/c above) is with the user.
  11-02 14:10 CT: bcbs pack after Blue batch 1 (4,183 networks -> product mode, 391 products): pg_state in hash
  slices, serve re-dispatched. FYI pipeline: UHC wave 12 failed 10-30 (out of disk), orchestrator stopped since.
- 2026-10-28 01:15 CT [pipeline] Pipeline lane: UHC down ops/waves.txt (orchestrator-driven; safety check-ins every ~4 h).
  BCBS, Aetna, Anthem merged; UHC waves 1-3 reduced.

## Requests
- 2026-11-05 18:40 CT [app -> pipeline] Worker mode is now built as worker boards (workers/README.md); this replaces
  the ops/workers.txt idea below. A helper's fork reads workers/<user>.yml from main every 15 min and runs compute
  items as workers/kinds/<kind>.sh on a fresh checkout of main (fork runners, id-token: write; env RC_REQUEST,
  RC_PART, RC_PARTS, RC_ID, RC_WORKER). Nothing for you to sync into forks. What only you can add: (1) kinds
  `map` (and `reduce`/`kaggle` if they make sense for a helper), e.g. RC_REQUEST "uhc 30-40" mapping those waves
  split over RC_PARTS runners, writing where your reduce expects shards; (2) the orchestrator skips (does not
  dispatch or count as missing) waves named on any workers/*.yml compute item that is running, and treats their
  shards as normal once written; (3) `if: github.repository == 'Harshu-Pande/ratecommons'` on your workflows' jobs,
  so a fork that does get synced never fires them (done for shop, cloud, serve). Seyun's username is still to come;
  the board starts with a `smoke` item only. Note when (1) is ready and Harshu can assign UHC waves on the board.
- 2026-11-03 12:10 CT [user, relayed by app -> pipeline] Second contributor with his own compute ("2 people, twice the
  compute"): Seyun will run work from a FORK of this repo (his GitHub Actions limits, his Kaggle account), set up by
  his own AI from docs/ONBOARDING.md. That needs a "worker mode" in your lane before his fork runs anything:
  (1) a fork must never run the orchestrator's clean/part-merge/dispatch of serve, cloud, shop, nor cron work: guard
  jobs on github.repository (main repo) vs. a worker fork; push-triggered request files must not fire in forks when
  he syncs main; (2) `ops/workers.txt` (format yours; ONBOARDING.md assumes it lists the fork owner and the work, e.g.
  a range of UHC waves to map and reduce, or a Kaggle job), which the main orchestrator skips when it dispatches maps
  and a fork's runs are limited to; (3) whatever his runs need to write to the work bucket and ops dataset (app will
  add his fork as a Hugging Face trusted publisher once we have his usernames; say if a different scope is needed).
  He reports in a GitHub issue "Worker log: Seyun" and sends code only as pull requests that Harshu merges. Please
  adjust ONBOARDING.md Part B/C to match what you build, and note here when worker mode is live.
- 2026-11-03 11:30 CT [user, relayed by app -> pipeline] UHC: two ideas the user wants. (1) Main files first: re-plan
  only the not-yet-mapped UHC files so one representative per (product code, near-equal size) group (the 1,268 groups
  of DECISIONS 10-27, ~11.8 TB) maps first, then loners, then the dense near-copy clusters last. Every file is still
  mapped, so order cannot lose data; shards already mapped keep their contents. Goal: every UHC network in the apps
  within days, employer carve-outs filling in later. (2) Kaggle as extra UHC capacity (it reached UHC every time; 1.1 TB
  disk avoids the small-runner 'No space left' failures), e.g. for the files that crash GitHub runners. App will pack
  each merged part (part-1 now) into the apps, so earlier parts that cover more networks help most. Your call on how.
- 2026-11-02 20:20 CT [user, relayed by app -> pipeline] Whole nation for the Blues: the user wants every Blue company's
  own networks, not BlueCard only. After BCBS Michigan (request above), please add discovery, map and merge for the
  ones bcbs does not have yet: BCBS Massachusetts, BCBS Rhode Island, BCBS Vermont, BCBS South Carolina, BCBS Kansas
  (Topeka), Regence (OR, ID, UT, WA), Blue Cross of Idaho, HMSA (Hawaii), Triple-S (Puerto Rico); then Blue Shield of
  California and BCBS Arizona (already planned after UHC). Please confirm BCBS Alabama is in the 2026-10 release (it is in
  discover.py but not in Blue batch 1's list). Keep retrying CareFirst and Arkansas when their sites allow downloads.
  Storage limits from the 10-30 decision still apply. App will re-pack serve -> cloud -> shop after each merge.
- 2026-11-02 18:55 CT [app -> pipeline] Re the 10-30 requests: bcbs serve (41514669631), cloud (41538708281) and shop
  'all' (41547830524) all succeeded with Blue batch 1. CareCompass now shows BCBS offers in NC, FL, WA, MA and PA. But
  Michigan has no BCBS offers at all, and bcbs products list only 'Blue Cross Blue Shield of Michigan (BlueCard)', none
  of BCBSM's or Blue Care Network's own networks. Is shard 29 (BCBS Michigan) in the bcbs 2026-10 release? If not,
  please map and merge it; app will re-pack after. CareFirst, Arkansas and the Horizon files stay noted as unavailable.
- 2026-11-02 16:55 CT [pipeline -> user] UHC map paused (PIPELINE = {}, ae29232): UHC published November files and the
  map plan is recomputed from the live index, so the 20:44 UTC map run mapped November files into map/2026-11/uhc
  (shards 156-167 under November's plan; nothing the orchestrator counts) and its next step started run 41527886315
  (waves 14-15, also November). Cancelling 41527886315 was refused by the session's permission check: it keeps
  uploading November map output nothing will reduce or clean (~0.4 TB per wave). Please cancel it if you agree
  (Actions -> run 41527886315 -> Cancel). Waves 1-13 (October) are reduced; deciding how to finish October vs start
  November after a probe of the October URLs from a runner.
- 2026-10-30 08:45 CT [user, relayed by app -> pipeline] Storage decision: do all three options. (a) delete the
  reduced/ wave outputs of Aetna and Anthem (keep BCBS's: the other Blue companies are being re-merged into bcbs);
  (b) merge UHC in parts and delete its reduced waves as parts merge; (c) map Blue Shield of California and BCBS
  Arizona only after UHC, wave by wave.
- 2026-10-30 02:25 CT [pipeline -> app] The AUTO_PACK `serve bcbs:dataset` after the Blue batch 1 merge failed
  (run 41013817050, job 123925493604, 54 min): serving.py build_pack line 225, `CREATE TABLE pg_state AS SELECT
  DISTINCT pg_id, state FROM pg_npi` ran out of DuckDB's 10.2 GB. Inputs at that point: 4,399,575 provider groups,
  ps_pli 689,391,149 rows, 215.6M prefiltered facts, 391 products from 4,183 networks, source 17.7 GB. The orchestrator
  will not retry it (it waits for a successful serve), so the live bcbs packs still hold the pre-batch data.
  Please make the pack fit (or run it in parts the way anthem's `:::main:5` did) and re-dispatch serve -> cloud ->
  shop; the request above (verify the new companies) still applies.
- 2026-10-30 01:30 CT [pipeline -> app] Rebuild/verify the bcbs packs: Blue batch 1 (other Blue companies' own
  networks: BCBS NC, Michigan, Horizon, Florida Blue, MN, LA, Premera, Excellus, OK/NM/MT, Blue KC, Independence, ND,
  WY, Highmark's six plans, Wellmark, Capital Blue, NE, MS; shards 28-33, wave 4) is merged (run 41009163756):
  bcbs 2026-10 now holds 5,291 source files, 4,183 networks, 4.55M codes, 1.32B rate facts. AUTO_PACK started
  `serve bcbs:dataset` (41013817050); please confirm the serving pack, cloud pack and CareCompass show the new
  companies, and note there that CareFirst, Arkansas and two Horizon files are missing (publishers refuse them,
  ops/unavailable.txt). Michigan's codes carry very large bundle text (9.7 GB decoded in one file) if serving.py
  reads code whole.
- 2026-10-29 15:10 CT [pipeline -> user] Storage: the 7.8 TB budget looks AT RISK, from UHC more than from the Blues.
  Used now 2.8 TB (work bucket 1.8 incl. 0.83 of UHC map output in flight; datasets 1.03). UHC so far: ~0.04 TB of
  reduced output per wave x 86 waves = ~3.4 TB, plus ~2 TB of map output in flight and a UHC release of 1-3 TB: about
  6-8 TB more. Other Blue companies: batch 1 (all but two) is only 96 GB of gzip; Blue Shield of California (1.5 TB)
  and BCBS Arizona (1.2 TB) are mostly per-employer near-copies and are held back. Options, your call: (a) delete
  reduced/ wave outputs of payers already merged (Aetna, Anthem, BCBS: 0.65 TB; needed only to re-merge); (b) merge UHC
  in parts and delete its reduced waves as parts merge; (c) map BSCA/AZ only after UHC, wave by wave like UHC.
- 2026-10-28 12:30 CT [pipeline -> app] FYI: `serve aetna:dataset` (run 40718817163) failed after 70 min: DuckDB out of
  memory (10.2 GiB) in serving.py build_pack line 80, `CREATE TABLE ns_all AS SELECT DISTINCT ns_id,
  unnest(network_ids)` over Aetna's full network_set (6,229 networks, 16 parts). Anthem's pack succeeded (40728881719);
  its cloud pack starts on the next orchestrator call.
- 2026-10-28 08:50 CT [pipeline -> app] Aetna 2026-10 is now a full release in `ratecommons/aetna` (all 6,229 files;
  the old serving pack is from wave 1 only, 3 networks). Aetna is not in AUTO_PACK: rebuild its serving/cloud packs
  when you want them (it is big: 2.94B facts, 438 provider_set parts; the BCBS out-of-disk note above applies).
- 2026-10-28 04:55 CT [pipeline -> app] BCBS 2026-10 is merged (run 40654175658: HCSC IL/TX own networks + every
  Blue plan's BlueCard files; 184 provider_set parts). The AUTO_PACK serving pack started and failed:
  run 40658312801 `serve bcbs:dataset`, "No space left on device" writing the DuckDB file in serving.py
  build_pack (fx table) after "source ready: 110.2 GB". BCBS needs a serving pack that fits a runner's disk
  (your lane: serving.py / serve_jobs.py / serve.yml). Once a `serve bcbs:dataset` run succeeds, the orchestrator
  starts the cloud pack and the CareCompass rebuild by itself. Anthem (merge later today) will be bigger still.
- 2026-10-28 02:45 CT [pipeline -> app] FYI: run 40651057695 `serve bcbs:dataset` was started by the orchestrator
  on an incomplete BCBS release (the failed merge left rate_fact published; HCSC's own networks not yet in). I did
  not cancel it (your lane). Its pack will be stale: the orchestrator now rebuilds serve -> cloud -> shop after the
  next successful bcbs merge. Please don't build a cloud pack or CareCompass from 40651057695's output.
- 2026-10-28 01:00 CT [app -> pipeline] Take over the pipeline lane: keep BCBS, Anthem, Aetna and UHC moving
  through `ops/waves.txt` (state at the top of docs/HANDOFF.md). In flight at handoff: BCBS wave 1
  `dims` re-run (dispatched 01:35 CT after 18ed484; the 01:00 run failed: no numpy on runners). Next: bcbs wave 2 (20-23) and merge,
  Aetna wave 16 and merge, Anthem waves, UHC waves. After each bcbs/anthem merge, check that the AUTO_PACK chain
  (serve -> cloud -> shop) starts; report its result here for the app session.
- 2026-10-28 01:00 CT [app -> pipeline] When GitHub Pro is active for Harshu-Pande (about 2026-10-31), raise map
  `max-parallel` toward 40 concurrent jobs.

## Done
- 2026-11-06 09:45 CT [pipeline] UHC part 3 (waves 25-36) merged and verified: 864 files = plan, none missing; waves 25-36 deleted. Waves 37-38 reduced, 39-40 mapping (38 of 86 waves done).
- 2026-11-05 09:45 CT [pipeline] Pipeline session checks UHC only every ~12 h from now (low on usage); the orchestrator re-runs failures by itself. If a reduce run shows 3 failed attempts or nothing has moved for hours, dispatch orchestrate.yml or note it here.
- 2026-11-05 09:40 CT [pipeline] Safety check: UHC wave 28 reducing (attempt 2), waves 30-31 mapping; shards 326/342 re-mapped. No action needed.
- 2026-11-05 05:40 CT [pipeline] Safety check: UHC waves 26, 27 reduced (27 after an automatic re-run); shards 326, 342 re-mapping after failed files; wave 28 next. No action needed.
- 2026-11-05 01:35 CT [pipeline] Safety check: UHC part 2 (waves 13-24) merged in 28 min: 864 files = the plan's 864 for shards 144-287, none missing, 30.1 GB; waves 13-24 deleted. Waves 24, 25 green (lost-runner re-runs automatic). UHC reduced now 118.7 GB for 25 waves (part-1 70.1, part-2 30.1, wave-25 18.5). Wave 26 waits for shard 308 (mapping with wave 27).
- 2026-11-04 21:30 CT [pipeline] UHC wave 22 facts green with the sub-sliced multi step (part 5: 23.4 nets per block, 576 sub-slices, 35 min); wave 23 green; both had lost-runner failures re-run within minutes by the new after-failure dispatch. Wave 24 reducing, waves 25-26 mapping; part 2 (13-24) next.
- 2026-11-04 18:10 CT [pipeline] Safety check: UHC wave 22 fact reduce out of memory in 11 of 16 parts twice (facts repeated across many blocks); multi step now sub-sliced by fan-out; wave 22 facts re-requested fresh (queued behind attempt 3).
- 2026-11-04 13:50 CT [pipeline] Safety check: UHC wave 22 reducing (attempt 2; attempt 1 predates the after-failure hook, re-run came from a map run's next step); waves 23-24 mapped (shards 266, 285 re-mapped after failed files). Part 2 next after wave 24.
- 2026-11-04 12:00 CT [app] Claim parts (1) and (3) done. BCBS: every code for 33 main network families (TN, IL,
  TX and the largest home family of 20 more Blue companies; North Carolina and Michigan get a smaller family: their
  largest need a pack of their own). Serve 41808926636 (804M rate rows), cloud 41852460738 (223,583 codes; code
  rows match the serve pack after the split-code fix). Patient tool: every state builds again (group slices; MI has
  Blue Cross); shop all 41880676454 refreshing with the new BCBS. Lessons in DECISIONS 2026-11-03 (evening).
- 2026-11-04 09:50 CT [pipeline] Safety check: UHC waves 20 (re-run) and 21 reduced, 22 queued, 23-24 mapping. workflow_run never fired (bot-started runs), so a failed reduce now dispatches the orchestrator itself (after-failure job).
- 2026-11-04 05:45 CT [pipeline] Safety check: wave 19 green (attempt 2); wave 20 lost part 3 to a runner at 09:31 UTC and waited 2 h: no scheduled orchestrator run at all since 07:40. orchestrate.yml now also runs on every map/reduce run end (workflow_run); pass dispatched by hand.
- 2026-11-04 01:40 CT [pipeline] Safety check: wave 19 lost part 13 to a small runner (05:51 UTC) and sat for ~2 h because the cron did not fire (last 02:13 UTC); orchestrate dispatched by hand (re-run), cron now every 15 min.
- 2026-11-03 22:35 CT [pipeline] UHC wave 18 green (41709999742 attempt 3: attempt 2 lost part 5 to a runner, no log); shard 206 repair complete. Wave 19 reducing; waves 20-22 mapped and waiting (3 in flight, so the next map starts after wave 20).
- 2026-11-03 19:35 CT [pipeline] Shard 206 re-mapped (new chunk 06 = the UMR SPRING-HEALTH file; status 6 files, 0 failed); wave 22 mapping. Wave 18 reduce 41709999742 ending (7-8 parts failed on the deleted chunk); its failed parts are re-run next, reading chunk 06.
- 2026-11-03 17:30 CT [pipeline] UHC wave 18: the failures are one unreadable chunk (shard-206-02, Hugging Face storage), not transient errors; the orchestrator deletes it and re-maps shard 206 (BAD_CHUNKS), then reduces wave 18 again.
- 2026-11-03 15:10 CT [pipeline] Safety check: UHC wave 18 reduce failed twice on transient Hugging Face download errors (5 fact parts); _fetch now falls back to per-file retries; wave 18 facts re-run fresh. Waves 20-21 mapped and waiting; the orchestrator resumes when wave 18 is green.
- 2026-11-03 11:30 CT [app] BCBS relabel chain done: serve (41566296964), cloud (41575996770), shop all (41581045145),
  app released at cececb2: bcbs products carry Blue company names. Coverage table fixed (3d25e3d): main networks show
  'every published service', UHC shown as an early sample. Michigan still has no bcbs offers (claimed above).
- 2026-11-03 11:00 CT [pipeline] Safety check: waves 17 (auto re-run: small runner, out of disk) and earlier reduced; 18 reducing, 20-21 mapping. Orchestrator now re-runs a failed reduce up to twice.
- 2026-11-03 06:55 CT [pipeline] Safety check: UHC waves 14 (auto re-run), 15, 16 reduced; wave 17 queued, waves 18-19 mapping beside it. ~1 wave per 1.5 h now; part 2 (13-24) follows wave 24.
- 2026-11-03 02:55 CT [pipeline] Safety check: waves 16-17 mapped (October plan, 41574448878); wave 14 reduce lost fact part 2 to a runner (log gone) and the orchestrator re-ran it by itself (attempt 2, running since 07:25 UTC). BCBS serve/cloud/shop all green again (app).
- 2026-11-03 [app] New public website live at ratecommons.org (carecompass/ app, Vercel routes on both projects,
  privacy fixes, docs). See DECISIONS 2026-11-03. Known follow-ups: provider tools take 2-4 min; patient results
  still include some unlikely places (data quality).
- 2026-11-02 22:50 CT [pipeline] Safety check: waves 14-15 mapped from the October plan in ~3.5 h (two waves per run),
  wave 14 reducing (41565385989). Map and reduce were taking turns (MAX_WAVES_IN_FLIGHT 2 counted the two mapped
  waves), so it is now 3: the next two-wave map run starts while 14-15 reduce. BCBS cloud pack and CareCompass done.
- 2026-11-02 app: shop 'all' rebuilt with Blue batch 1 (run 41547830524, success). Web app fix for BCBS lookups is pushed but waits on a Vercel release (needs the user's approval of Vercel team access).
- 2026-11-02 19:00 CT [pipeline] Storage 2.06 TB of 7.8 (was 3.18 on 10-30): work bucket 0.91 (UHC map in flight 0.38, bcbs reduced 0.25, UHC reduced 0.09, serve 0.09, old cigna/bcbs-2026-09 map 0.06), datasets 1.16.
- 2026-11-02 app: BCBS cloud pack with the 28 new Blue companies is live (serve/v2/bcbs, built 23:30Z). Fixed lookup_rates crash for BCBS (main network with no plan names, cloud/api/_rc.py). Shop rebuild 'all' dispatched (run 41547830524).
- 2026-11-02 18:45 CT [pipeline] UHC back on October: the November run 41527886315 was cancelled (the 16:55 request is
  resolved); one more November run (41533695599) came from its next step on the old commit; its successor 41539453778
  (waves 14-15, shards 156-179) maps from the stored October plan. clean() deleted the stray November output. Wave 13
  reduced; part 1 (waves 1-12, 864 files) merged in 20 min to 70.1 GB (part-00: 498M wave facts -> 111M distinct;
  12 separate waves were ~300 GB) and waves 1-12 were deleted. BCBS serving pack done, cloud pack running (app).
- 2026-11-02 17:40 CT [pipeline] UHC October files are still served (runner probe); UHC map dispatch re-enabled with the
  stored October plan pinned (MAP_PLANS) and the stray November map output (map/2026-11/uhc) cleaned by clean().
  Run 41527886315 (November) still runs; once it ends, its next step dispatches October waves 14-15. Cancelling it
  early still saves ~1 h of 24 runners and its uploads (they are deleted either way).
- 2026-11-02 16:55 CT [pipeline] Wave 12 green after the re-run; orchestrator (new code) dropped aetna and anthem reduced
  waves (2,151 + 615 files, dropped.json first); wave 13 reducing. UHC map paused (see Requests).
- 2026-11-02 15:10 CT [pipeline] Storage decision applied (DECISIONS 2026-11-02): (a) aetna/anthem reduced waves are
  deleted by the orchestrator's clean() after writing dropped.json (re-merging them now needs a re-reduce); (b) UHC
  merges in 7 parts (waves.txt `part=P a-b`; part 1 = waves 1-12 runs after wave 12), each part's waves deleted once
  it is complete; (c) BSCA and BCBS AZ wait for the UHC merge. Also: streamed list tables are now written ~2.4x smaller.
- 2026-11-02 app: README.md rewritten for the current state (payers, apps, MCP, pipeline, workflows, storage, layout). Shared doc: pipeline session, correct anything in your lane.
- 2026-11-02 14:20 CT [pipeline] UHC was stalled since 2026-10-30 22:50 CT: reduce wave 12 (41139945672) lost parts 4,
  5, 10 to small runners (32 GB free disk). Failed jobs re-run (attempt 2); the orchestrator now re-runs a failed
  reduce once by itself. GitHub Pro: map max-parallel 24 (two UHC waves per map run), reduce 14. Rule from today: when
  the pipeline session will be idle or out of usage, it says so here first, so the app session or the user can watch
  the orchestrator (`gh run list`; a red reduce run twice in a row needs a person).
- 2026-10-30 06:25 CT [pipeline] Safety check: UHC waves 7 and 8 reduced (41013857656, 41028620741; 8 provider_set jobs each, no failures), wave 9 (96-107) mapping. bcbs serving-pack OOM request still open for the app session.
- 2026-10-30 02:25 CT [pipeline] Safety check: UHC wave 7 reducing (41013857656, first wave with 8 provider_set jobs, no failures), wave 8 (84-95) mapping. Storage 3.18 TB of 7.8 (work 2.02, datasets 1.16).
- 2026-10-30 01:30 CT [pipeline] Blue batch 1 merged into bcbs: shard 29 re-mapped after streaming code redaction;
  wave 4 dims re-run after streaming the code table and splitting wave provider_set into 8 jobs (41006022322); bcbs
  merge 41009163756 succeeded (5,291 files, 1.32B facts). AUTO_PACK serve running; UHC wave 7 reduce queued,
  wave 8 mapping. Next Blue batches wait on the storage decision (BSCA 1.5 TB, BCBS AZ 1.2 TB).
- 2026-10-29 22:30 CT [pipeline] Safety check: UHC wave 5 reduced, wave 6 reduced, wave 7 (72-83) mapping. Blue batch 1:
  shard 33 resumed and finished except 40 files the publishers refuse (CareFirst own files 403, Arkansas 404, two
  stale Horizon entries), now listed in ops/unavailable.txt so they no longer block the wave (retry in a later batch).
  Shard 29 (BCBS Michigan HMO) crashed on 9.7 GB of code bundle text read whole; redaction now streams; shard 29
  re-queued alone (6773b6d). Then bcbs wave 4 reduce, re-merge, and a pack-rebuild request for the app session.
- 2026-10-29 17:50 CT [pipeline] Safety check: UHC wave 4 reduced (40928439451); wave 5 reducing, wave 6 mapping. Blue batch 1
  (40943309473): 5 of 6 shards mapped; shard 29 lost its runner (GitHub shutdown signal), to be retried once shard 33 ends.
- 2026-10-29 13:45 CT [pipeline] UHC wave 3 reduced (40912655610, all 16 parts; ~79 GB disk free per part after
  d2bc403). Orchestrator carries UHC again: wave 4 reduce (40928439451, wave-ready passed), wave 5 map (40928394758).
- 2026-10-29 11:40 CT [pipeline] UHC wave 3 facts re-run 40864095201: 15 of 16 parts out of disk again (sliced input
  kept until the end). Fix d2bc403 (slices deleted as processed); facts re-run dispatched.
- 2026-10-29 06:20 CT [pipeline] UHC wave 3 reduce 40847293649: dims ok, 14 fact parts lost their runners (disk full,
  ~44 GB per part). Fix e6fd5e5 (batched download + slice); facts-only re-run queued behind it. Wave 4 mapped (40833009843).
- 2026-10-29 04:10 CT [pipeline] UHC wave 3 mapped clean (run 40810183212, with the download resume fix; shards 24, 25,
  32 had broken downloads before it). `wave-ready` passed; wave 3 reduce dispatched (40847293649). Orchestrator is
  mapping wave 4 (40833009843).
- 2026-10-28 16:55 CT [pipeline] Cancelled run 40770018611 (UHC wave 3 reduce dispatched by the orchestrator while wave 3
  was still mapping; user approved). Its `next` (clean) never ran; nothing deleted. Fix c97e8ca; wave 3 reduce will be
  re-dispatched once map 40756027556 finishes and `ticdata wave-ready` passes.
- 2026-10-28 14:40 CT [pipeline] UHC wave 1 reduced (40742402318); orchestrator runs on: wave 2 reduce, wave 3 map.
- 2026-10-28 14:15 CT [pipeline] AUTO_PACK chain finished for anthem (shop all 40744161977 ok) and bcbs (40723364771 ok).
- 2026-10-28 13:20 CT [pipeline] AUTO_PACK for anthem: serve 40728881719 ok, cloud 40742473756 ok, shop all 40744161977
  started. UHC wave 1 facts out of disk -> fix 31fbb29, re-running (facts only).
- 2026-10-28 12:30 CT [pipeline] AUTO_PACK: bcbs shop all ok (40723364771); anthem serve ok (40728881719).
- 2026-10-28 11:10 CT [pipeline] Anthem 2026-10 merged (run 40712256664): 1,002 files, 787M rate facts, all tables.
- 2026-10-28 11:10 CT [pipeline] AUTO_PACK for bcbs: serve 40718802331 ok, cloud 40720884027 ok, shop all 40723364771
  queued. Anthem's serving pack starts on the next orchestrator call. UHC wave 1 reduce queued (40723371695).
- 2026-10-28 08:50 CT [pipeline] Aetna 2026-10 merged (run 40693836067): 6,229 files, 2.94B rate facts, all tables.
- 2026-10-28 04:55 CT [pipeline] BCBS 2026-10 merged (waves 1-3, 1,795 files incl. HCSC's own networks).
- 2026-10-28 01:45 CT [app] Anthem retry run 40639683209 succeeded (13 shards); shard 1 still needed the pipeline
  session's fix (see Claimed). The app session stopped watching pipeline runs at 02:30 CT.
- 2026-10-28 00:50 CT [app] BCBS of Tennessee's own networks mapped as bcbs shards 20-23 (run 40637222066).
- 2026-10-28 00:45 CT [app] consolidate.py and reduce.py stream list tables with pyarrow (Anthem, BCBS OOMs).
