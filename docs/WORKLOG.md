# Work log shared by the two sessions (see CLAUDE.md, "Two sessions share this repo")

Newest first in each section. One line per item: `YYYY-MM-DD HH:MM CT [session] what (files or runs)`.

## Claimed
- 2026-10-28 01:15 CT [pipeline] Pipeline lane: BCBS and Anthem to merged, Aetna/UHC down ops/waves.txt
  (src/ticdata/{reduce,pipeline,cli}.py, core/, ops/, map/reduce runs). State 02:30 CT: BCBS waves 1-2 reduced;
  merge failed (DuckDB OOM in merge dims, fixed e906ae8). HCSC's own networks (1,142 files named 2026-09-*) were
  missing from release 2026-10; re-mapping them as bcbs shards 24-27 (wave 3), then wave 3 reduce and merge.
  Anthem: shards 1 and 2 (5 GB NY files) re-mapping after core memory fixes (run 40648979410).

## Requests
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
- 2026-10-28 04:55 CT [pipeline] BCBS 2026-10 merged (waves 1-3, 1,795 files incl. HCSC's own networks).
- 2026-10-28 01:45 CT [app] Anthem retry run 40639683209 succeeded (13 shards); shard 1 still needed the pipeline
  session's fix (see Claimed). The app session stopped watching pipeline runs at 02:30 CT.
- 2026-10-28 00:50 CT [app] BCBS of Tennessee's own networks mapped as bcbs shards 20-23 (run 40637222066).
- 2026-10-28 00:45 CT [app] consolidate.py and reduce.py stream list tables with pyarrow (Anthem, BCBS OOMs).
