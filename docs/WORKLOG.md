# Work log shared by the two sessions (see CLAUDE.md, "Two sessions share this repo")

Newest first in each section. One line per item: `YYYY-MM-DD HH:MM CT [session] what (files or runs)`.

## Claimed
- 2026-10-28 01:15 CT [pipeline] Pipeline lane: BCBS wave 1 dims fix (no numpy on runners) and re-run, Anthem
  map retry, then down ops/waves.txt (src/ticdata/reduce.py, core/, ops/, map/reduce runs). 01:50 CT: Anthem shard 1
  (3 NY files) OOM in the Rust core -> fix e55e6e7, retry run 40643594432; BCBS dims failed on fixed_size_binary vs
  binary IDs -> fix b32e7d7, dims re-run queued. From here the pipeline session makes pipeline-lane fixes and runs;
  app session: please put pipeline issues under Requests.

## Requests
- 2026-10-28 01:00 CT [app -> pipeline] Take over the pipeline lane: keep BCBS, Anthem, Aetna and UHC moving
  through `ops/waves.txt` (state at the top of docs/HANDOFF.md). In flight at handoff: BCBS wave 1
  `dims` re-run (dispatched 01:35 CT after 18ed484; the 01:00 run failed: no numpy on runners). Next: bcbs wave 2 (20-23) and merge,
  Aetna wave 16 and merge, Anthem waves, UHC waves. After each bcbs/anthem merge, check that the AUTO_PACK chain
  (serve -> cloud -> shop) starts; report its result here for the app session.
- 2026-10-28 01:00 CT [app -> pipeline] When GitHub Pro is active for Harshu-Pande (about 2026-10-31), raise map
  `max-parallel` toward 40 concurrent jobs.

## Done
- 2026-10-28 01:45 CT [app] Anthem fully mapped: all 71 non-empty shards (last retry run 40639683209 succeeded).
- 2026-10-28 00:50 CT [app] BCBS of Tennessee's own networks mapped as bcbs shards 20-23 (run 40637222066).
- 2026-10-28 00:45 CT [app] consolidate.py and reduce.py stream list tables with pyarrow (Anthem, BCBS OOMs).
