# Worker boards: giving a helper's fork work without asking the helper

A helper (first: Seyun) forks this repository once. From then on Harshu, or a Claude session on Harshu's behalf,
assigns work by editing `workers/<helper's GitHub username>.yml` on `main`. Nobody needs to message the helper.

```
Harshu edits workers/<user>.yml ──► the fork's "worker" workflow (every 15 min, no AI) reads it from main
                                      ├─ compute item ──► worker-job run in the fork: workers/kinds/<kind>.sh
                                      │                   on 1-40 of the fork's runners (the helper's limits)
                                      └─ ai item ───────► worker-ai run in the fork: Claude Code on the
                                                          helper's subscription, capped turns, Sonnet;
                                                          the result is a patch artifact, never a push
```

## Why it is cheap for the helper

- **Compute uses no Claude at all.** The poller and the job runner are plain GitHub Actions. Public repositories get
  Actions minutes free; what a second account adds is a second set of concurrent runners (20 on a free account, 40
  with GitHub Pro from the Student Developer Pack).
- **Claude runs only for an `ai` item,** once per item, with a turn cap and at most `ai_per_day` starts a day. A board
  with only compute items never touches the helper's Claude usage. The helper's own chats are unaffected otherwise.
- **The fork never needs syncing.** Every run checks out `Harshu-Pande/ratecommons` `main`, so new kinds, fixes and
  instructions reach the helper's runners the moment they land on `main`. The fork only keeps three small workflow
  files (`worker.yml`, `worker-job.yml`, `worker-ai.yml`).

## The board (`TEMPLATE.yml`)

| Field | Meaning |
|---|---|
| `paused` | `true` starts nothing new and cancels running compute |
| `compute[]` | `id`, `kind` (a script in `workers/kinds/`), `request` (text for the script), `parallel` (runners) |
| `ai[]` | `id`, `task` (plain-language instructions), `budget` (`small` / `medium` / `large`) or `turns` and `model` |
| `max_running`, `ai_per_day`, `retries` | limits; see the template |

An item is identified by its `id`: a run named with that id that is running or succeeded means it is not started
again. To run the same thing again, add a new item with a new id. Removing a compute item cancels its running run.

## Kinds (`workers/kinds/<kind>.sh`)

A kind is a bash script run from a fresh checkout of `main` on a fork runner. It gets `RC_REQUEST`, `RC_PART`,
`RC_PARTS`, `RC_ID` and `RC_WORKER` (the helper's username), has `id-token: write` for Hugging Face trusted
publishing (once the fork is added as a trusted publisher), and runs up to 355 minutes.

| Kind | Owner | What it does |
|---|---|---|
| `smoke` | app | Checks the plumbing: prints the inputs, installs the package, tests which payer hosts the runner reaches |
| `map`, `reduce`, `kaggle` | pipeline | Not written yet (WORKLOG Requests): UnitedHealthcare waves and other payers |

Rules for kinds: never delete anything on Hugging Face, never run clean, merge, serve, cloud or shop, and write only
under a prefix that names the helper or the assigned waves, so the main orchestrator can tell whose work it is.

## AI items

`worker-ai` builds the prompt from `workers/ai-preamble.md` (the standing rules) plus the item's `task`, runs Claude
Code with the helper's `CLAUDE_CODE_OAUTH_TOKEN`, and uploads what Claude committed as a patch (`handoff` artifact)
with a summary in the run page. It never pushes, merges or dispatches. A Claude session in this repository picks the
patch up, reviews it, and lands it (`python workers/status.py <user>` lists the results and artifacts).

## Seeing what a helper's fork is doing

```
python workers/status.py <user>          # the fork's worker runs: item, state, link, artifacts
```

The fork is public, so this needs no token beyond a signed-in `gh`.
