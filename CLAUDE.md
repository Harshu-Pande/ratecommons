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

## Two sessions share this repo (from 2026-10-28)
Two Claude sessions work here at once. Each owns a lane and changes only its own files and runs.
- **Pipeline session** (Claude Code, claude.ai/code): getting payer data parsed, merged and published.
  Owns `src/ticdata/` except `shop.py`/`shopcatalog.py`/`serving.py`; `core/`; `ops/` (waves, request files,
  `orchestrate.py`); workflows `map`, `reduce`, `orchestrate`, `core`, `kaggle`, `run`, `smoke`, `archive-manifests`.
  It is the only session that dispatches or cancels map/reduce runs.
- **App session** (Claude chat with the browser, Vercel and the Project): `carecompass/`, `cloud/`, `gateway/`,
  `space/`, `shop.py`, `shopcatalog.py`, `serving.py`; workflows `shop`, `cloud`, `serve`; Vercel, domains,
  Hugging Face settings, Project docs.
- **Shared, append-only:** `docs/DECISIONS.md` (newest first), `docs/HANDOFF.md`, `docs/WORKLOG.md`, `CLAUDE.md`.

Rules for both:
1. `git pull --rebase` before editing and before pushing. Never force-push, amend or rebase pushed commits, or
   revert the other session's commits. Start commit messages with `[pipeline]` or `[app]`.
2. Before a task, add a line under "Claimed" in `docs/WORKLOG.md` (time, session, task, files); move it to "Done"
   with the result when finished. Don't touch files the other session has claimed.
3. Need something in the other lane? Write it under "Requests" in `docs/WORKLOG.md` instead of doing it.
4. A dispatched map run cancels the running one in the same payer lane (`cancel-in-progress`). Check
   `gh api repos/Harshu-Pande/ratecommons/actions/runs?status=in_progress` before dispatching; never cancel a run
   you did not start.
5. Never delete anything in Hugging Face buckets or datasets by hand; the orchestrator's `clean()` is the only deleter.
6. Save usage: wait in the background instead of polling often (2+ minutes between checks), grep logs instead of
   printing them, and don't re-read large files.
