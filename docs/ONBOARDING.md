# Helping run RateCommons from your own accounts

For a second person (first: Seyun) who lends RateCommons their GitHub Actions runners, and optionally a little of
their Claude subscription. Setup takes about 15 minutes, once. After that **you do nothing**: Harshu assigns work
by editing a file in his repository, and your fork picks it up on its own within 15 minutes.

**Why your own accounts.** GitHub lets each account run a limited number of jobs at once (20 on a free account, 40
with GitHub Pro from the Student Developer Pack). Runs in your fork use your account's slots, so the project gets
twice the runners. Public repositories pay nothing for Actions minutes.

**What it costs you.**
- Compute work (processing insurer files, the bulk of it) uses **no AI at all**: plain GitHub Actions in your fork.
- AI work (a website fix, finding an insurer's files) runs Claude Code in your fork **on your Claude subscription**,
  only when Harshu assigns an AI item, with a turn cap, the Sonnet model, and at most 2 items a day (Harshu can lower
  that). Skip step 4 below and your Claude is never used.
- Your fork is never synced or edited by hand; every run uses the newest code from Harshu's repository.

---

## Paste this into your AI (optional)

> I'm lending my GitHub Actions runners to my friend Harshu's project RateCommons
> (github.com/Harshu-Pande/ratecommons). Read `docs/ONBOARDING.md` there and walk me through the setup steps one
> at a time. Never ask me to paste a token or password into this chat; tokens go only into GitHub's secret settings.

## Setup (you, once)

1. **GitHub.** Sign in (or create a free account). Worth it: the GitHub Student Developer Pack
   (education.github.com/pack) includes GitHub Pro, which doubles your runners. If Harshu added you as a
   collaborator, accept the invitation from your email; it isn't needed for the steps below.
2. **Fork.** Open github.com/Harshu-Pande/ratecommons, click **Fork**, keep "Copy the main branch only", create it.
3. **Turn on the worker.** In your fork open **Actions** and click **"I understand my workflows, go ahead and
   enable them"**. Then click **worker** in the left list and **Enable workflow** (GitHub keeps scheduled
   workflows off in forks until you do this). That is the only workflow you turn on; it starts everything else.
4. **Optional: let AI items use your Claude.** On a computer with Node.js, run
   `npm install -g @anthropic-ai/claude-code`, then `claude setup-token`, and sign in when asked. It prints a token.
   In your fork: **Settings -> Secrets and variables -> Actions -> New repository secret**, name
   `CLAUDE_CODE_OAUTH_TOKEN`, paste the token, save. Paste it nowhere else. (To stop at any time, delete the secret.)
5. **Tell Harshu your GitHub username** (and your Hugging Face username if you have one; no token needed). He
   creates your board, `workers/<your username>.yml`, and adds your fork as a trusted publisher on the project's
   Hugging Face storage so your runs can save results without any token.

Later, only if Harshu asks: a Kaggle account (free; verify your phone in Kaggle settings) and its API token as a
fork secret named `KAGGLE_API_TOKEN`, for files too big for GitHub's runners.

## What happens after setup

- Every 15 minutes the **worker** workflow in your fork reads your board from Harshu's repository (it uses no AI)
  and starts any new item:
  - a **compute** item runs as **worker-job** on 1 to 40 of your runners;
  - an **AI** item runs as **worker-ai**: Claude Code works on a fresh copy of the code and hands its changes back
    as a patch that Harshu's sessions review. It never pushes, merges or starts anything.
- Harshu changes your work by editing the board: removing an item stops it, pausing stops everything new.
- You can watch it all in your fork's **Actions** tab, and you can turn it off there (disable **worker**) at any
  time.

## For the AI walking someone through this

Do only the steps above, in order, and let the person click; never ask for a token in chat. Do not run, dispatch,
sync or edit anything in the fork or in Harshu's repository. When step 5 is done, the setup is finished; the
person does not need to keep you open. The design is in `workers/README.md`.
