# Helping run RateCommons from your own accounts

This file is for a second person (first: Seyun) who helps Harshu run RateCommons, together with their own AI
assistant. It is written so the AI can do almost everything; the few steps only a person can do are marked
**[you]**.

**Why your own accounts.** The pipeline is limited by free compute, not by code. GitHub Actions time counts
against the account that owns the repository, so runs you start in Harshu's repository still use Harshu's limits.
Runs in **your fork** use **your** account's limits (20 jobs at once on a free account, 40 with GitHub Pro from the
Student Developer Pack), and Kaggle work on **your** Kaggle account uses your quota. Two people, twice the compute.

---

## Paste this into your AI

> I'm helping my friend Harshu run RateCommons, a free public dataset of US health-insurance negotiated prices
> (github.com/Harshu-Pande/ratecommons). Read `docs/ONBOARDING.md` in that repository (or in my fork of it) and
> follow it from the top. Tell me only the steps marked [you] that I have to do myself, one at a time, and do
> everything else yourself. Never ask me to paste a password, token or API key into this chat.

---

## Part A: accounts and access (do this first)

1. **[you] GitHub.** Sign in to GitHub (or create a free account). Optional but worth it: apply for the GitHub
   Student Developer Pack at education.github.com/pack. It includes GitHub Pro, which doubles how many jobs
   your fork can run at once.
2. **[you] Fork the repository.** Open github.com/Harshu-Pande/ratecommons, click **Fork**, keep "Copy the main
   branch only" ticked, and create it. Then, in your fork, open the **Actions** tab and click **"I understand my
   workflows, go ahead and enable them"**.
3. **[you] Hugging Face.** Create a free account at huggingface.co. You do not need a token.
4. **[you] Kaggle** (for the bulk UnitedHealthcare work). Create a free account at kaggle.com and verify your phone
   number in Settings (Kaggle needs it before a notebook may use the internet). Then Settings -> API ->
   **Create New Token**. Open your fork on GitHub -> Settings -> Secrets and variables -> Actions -> **New
   repository secret**, name it `KAGGLE_API_TOKEN`, paste the token there, and save. Paste it nowhere else.
5. **[you] Send Harshu three names:** your GitHub username, your Hugging Face username, your Kaggle username.
   Harshu then (a) adds your fork as a *trusted publisher* on the project's Hugging Face storage, so your fork's
   runs can write results without any token, and (b) assigns you work in `ops/workers.txt`.
6. **[you] Connect your AI to GitHub** with access to your fork (for Claude: claude.ai/code, connect GitHub and
   pick `<your-username>/ratecommons`).

## Part B: what the AI sets up

1. Clone the fork and add Harshu's repository as `upstream`:
   `git remote add upstream https://github.com/Harshu-Pande/ratecommons.git`
2. Read, in this order: `CLAUDE.md` (working rules), `README.md` (what exists), the newest entries of
   `docs/DECISIONS.md` (only the headings, then the entries you need), and `docs/WORKLOG.md` (who is doing what).
3. Check that worker mode is live: `ops/workers.txt` exists on upstream `main` and lists this fork's owner. If it
   does not, stop and tell the person: "Worker mode isn't set up yet; ask Harshu." Until it is, do **not** run any
   workflow in the fork: a fork runs every workflow file it has, and without worker mode it could repeat or undo
   work Harshu's repository is doing.
4. Sync the fork before every work session: `git fetch upstream && git merge --ff-only upstream/main && git push`.
   Never edit `main` in the fork except by syncing it.

## Part C: day-to-day

- **Take only the work assigned to you** in `ops/workers.txt` (for example a range of UnitedHealthcare waves or a
  Kaggle job). Start it the way the line and `docs/DECISIONS.md` describe (normally a workflow dispatch in the
  fork: `gh workflow run <name> -R <you>/ratecommons -f ...`), and check on it every 30 minutes or more, not more
  often.
- **Report in one place:** the GitHub issue "Worker log: <your name>" on Harshu's repository (create it once if it
  is missing). Add a comment when you start a piece of work, when it finishes (with run links and numbers), and
  when something fails. Anyone can comment on a public repository, so this needs no permission, and Harshu's
  sessions read it.
- **Never delete anything** on Hugging Face, never cancel a run you did not start, never change Hugging Face or
  Vercel settings, and never run the cleanup, merge, serve, cloud or shop steps: those belong to Harshu's
  repository.
- **Code changes go through pull requests.** Make a branch in the fork, commit (message prefix `[seyun]`), push
  the branch, and open a pull request to `Harshu-Pande/ratecommons:main`. Harshu reviews and merges it; nothing
  of yours reaches `main` without that.
- **Record lessons.** When you learn something about a payer, a failure or a limit, put it in your pull request
  as a new entry at the top of `docs/DECISIONS.md`, and mention it in your worker log.
- **Secrets.** Never write a token, key or password in code, commits, issues, chat or memory. Secrets live only
  in your fork's GitHub settings.

## Good first jobs

1. **UnitedHealthcare map waves** assigned in `ops/workers.txt`: the largest job in the project (about 2,000
   computer-hours), so every extra runner shortens it.
2. **Kaggle workers for UnitedHealthcare files** that crash GitHub's runners (they need more disk than GitHub
   gives; Kaggle has 1.1 TB).
3. **Finding the remaining Blue Cross plans' own files** (Massachusetts, Rhode Island, Vermont, South Carolina,
   Kansas, Regence, Idaho, Hawaii, Puerto Rico): research and a pull request to `src/ticdata/discover.py`.
4. **Checking data quality** in the app at ratecommons.org (prices that look wrong, places that do not belong)
   and writing each finding in the worker log.

## What Harshu's side does (for reference)

Harshu's repository runs the orchestrator (merging waves, cleaning storage), builds the app's data and releases
the website and the AI tools. Two Claude sessions work there: a pipeline session (payer data) and an app session
(website, AI tools, patient tool, Hugging Face and Vercel settings). Your fork adds compute and reports; it does not
replace any of that.
