# RateCommons: working rules for Claude sessions

## The forest (read before starting any track)
- Blueprint: the design doc, https://claude.ai/artifact/7d81McCZzQwiNqL6i28pNK. A full markdown
  copy is in the claude.ai Project "Price Transparency Project" at `claude/ratecommons-design-full.md`
  (use `project_search` for a section instead of reading all of it).
- Where reality changed the blueprint: `docs/DECISIONS.md` (newest first). Plan: `docs/NEXT.md`.
- Infrastructure facts: Project doc `claude/ratecommons-infra.md`.
- Before building a component, re-read its tab: Parser rules, Rates and codes, Duplicate files,
  Provider identity, Downloading reliably, Payer playbooks, and the main tab's data model.

## Invariants from the design
- Discard no data: keep every raw value as published; normalize beside it; record deviations as flags,
  never fail a file for them.
- IDs are content hashes (xxh3-128 of a canonical encoding), so any worker computes the same ID.
- Amounts are integers in ten-thousandths of a dollar, plus the raw string.
- Provider group = TIN + sorted NPI list. `npi: [0]` means the whole TIN. Never trust names
  (network_name, business_name) for identity.
- A missing rate means "no published rate", never "out of network".
- History is stored as changes (valid_from / valid_to); an unchanged fact writes nothing.

## How to work
- Never wait on a running job: start long jobs first, then write code for another track.
- GitHub Actions is the orchestrator. Start runs by committing an edit to `ops/*-request.txt`;
  read results from `datasets/ratecommons/ops` on Hugging Face. `gh api` reaches the Actions API from
  Claude sessions too (seen 2026-10-27): list runs, read logs (`gh run view --log`), dispatch workflows.
- GitHub writes to Hugging Face through Trusted Publishers; a new dataset or bucket needs the
  repo added as a trusted publisher in its settings (browser pane is signed in to HF and GitHub).
- Kaggle exit region varies per session: workers probe which payers they can reach first.
- Never put tokens in code, docs, commits or memory.
- In writing, call the user's older pipeline "our in-house pipeline", never by its product name.
- Record each lesson in `docs/DECISIONS.md` the moment it is learned.
