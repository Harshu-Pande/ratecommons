# Work log shared by the two sessions (see CLAUDE.md, "Two sessions share this repo")

Newest first in each section. One line per item: `YYYY-MM-DD HH:MM CT [session] what (files or runs)`.

## Claimed
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
- 2026-10-28 01:15 CT [pipeline] Pipeline lane: UHC down ops/waves.txt (orchestrator-driven; safety check-ins every ~4 h).
  BCBS, Aetna, Anthem merged; UHC waves 1-3 reduced.

## Requests
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
