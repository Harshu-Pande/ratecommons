# Work log shared by the two sessions (see CLAUDE.md, "Two sessions share this repo")

Newest first in each section. One line per item: `YYYY-MM-DD HH:MM CT [session] what (files or runs)`.

## Claimed

## Requests
- 2026-10-28 01:00 CT [app -> pipeline] Take over the pipeline lane: keep BCBS, Anthem, Aetna and UHC moving
  through `ops/waves.txt` (state at the top of docs/HANDOFF.md). In flight at handoff: Anthem map retry of shards
  4,5,6,7,8,9,19,20,21,58,59,60,62 (run 40639683209, after the consolidate streaming fix c4f9686); BCBS wave 1
  `dims` re-run (dispatched 01:00 CT, after the reduce streaming fix 7969f80). Next: bcbs wave 2 (20-23) and merge,
  Aetna wave 16 and merge, Anthem waves, UHC waves. After each bcbs/anthem merge, check that the AUTO_PACK chain
  (serve -> cloud -> shop) starts; report its result here for the app session.
- 2026-10-28 01:00 CT [app -> pipeline] When GitHub Pro is active for Harshu-Pande (about 2026-10-31), raise map
  `max-parallel` toward 40 concurrent jobs.

## Done
- 2026-10-28 00:50 CT [app] BCBS of Tennessee's own networks mapped as bcbs shards 20-23 (run 40637222066).
- 2026-10-28 00:45 CT [app] consolidate.py and reduce.py stream list tables with pyarrow (Anthem, BCBS OOMs).
