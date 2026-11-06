#!/usr/bin/env python3
"""Poller for a helper's fork (.github/workflows/worker.yml, every 15 minutes; uses no AI).

Reads workers/<fork owner>.yml from Harshu-Pande/ratecommons main, then for each item: starts it once as a run in
the fork (worker-job for compute, worker-ai for AI), retries a failed one up to `retries` times, and cancels running
compute that is no longer on the board (or when the board is paused). A run's name is the item id, so the fork's own
run list is the only state. Env: GITHUB_REPOSITORY (the fork), GH_TOKEN; RC_DRY_RUN=1 prints instead of acting;
RC_BOARD=path reads a local board (tests)."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

import yaml

UPSTREAM = os.environ.get("RC_UPSTREAM", "Harshu-Pande/ratecommons")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
OWNER = REPO.split("/")[0].lower()
DRY = os.environ.get("RC_DRY_RUN") == "1"
ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
KIND = re.compile(r"^[a-z0-9-]{1,40}$")


def board() -> dict | None:
    if os.environ.get("RC_BOARD"):
        return yaml.safe_load(open(os.environ["RC_BOARD"])) or {}
    url = f"https://raw.githubusercontent.com/{UPSTREAM}/main/workers/{OWNER}.yml"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return yaml.safe_load(r.read()) or {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def gh(*args: str) -> str:
    if DRY and args[0] in ("workflow", "run") and args[1] in ("run", "cancel"):
        print("DRY:", "gh", *args)
        return ""
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def runs(workflow: str) -> list[dict]:
    if os.environ.get("RC_RUNS"):  # tests: a JSON file of {workflow: [runs]}
        return json.load(open(os.environ["RC_RUNS"])).get(workflow, [])
    try:
        out = gh("run", "list", "-R", REPO, "-w", workflow, "-L", "300",
                 "--json", "databaseId,displayTitle,status,conclusion,createdAt")
    except subprocess.CalledProcessError:
        return []  # the workflow has never run
    return json.loads(out or "[]")


def state(rs: list[dict], item_id: str) -> tuple[str, int, list[dict]]:
    mine = [r for r in rs if r.get("displayTitle") == item_id]
    live = [r for r in mine if r.get("status") != "completed"]
    if live:
        return "running", len(mine), live
    if any(r.get("conclusion") == "success" for r in mine):
        return "done", len(mine), []
    return ("failed" if mine else "new"), len(mine), []


def main() -> int:
    if not REPO or REPO.lower() == UPSTREAM.lower():
        print("worker: runs only in a helper's fork")
        return 0
    b = board()
    if b is None:
        print(f"worker: no board workers/{OWNER}.yml on {UPSTREAM} main; nothing to do")
        return 0
    paused = bool(b.get("paused"))
    retries = int(b.get("retries", 1))
    max_running = int(b.get("max_running", 2))
    ai_per_day = int(b.get("ai_per_day", 2))
    report = []

    # compute
    jobs = runs("worker-job.yml")
    items = [x for x in (b.get("compute") or []) if isinstance(x, dict)]
    wanted = {str(x.get("id")) for x in items} if not paused else set()
    for r in jobs:  # cancel what left the board (or everything when paused)
        if r.get("status") != "completed" and r.get("displayTitle") not in wanted:
            gh("run", "cancel", str(r["databaseId"]), "-R", REPO)
            report.append((r.get("displayTitle"), "compute", "cancelled (no longer on the board)"))
    running = sum(1 for r in jobs if r.get("status") != "completed" and r.get("displayTitle") in wanted)
    for x in items:
        iid, kind = str(x.get("id", "")), str(x.get("kind", ""))
        if not ID.match(iid) or not KIND.match(kind):
            report.append((iid, "compute", "skipped: bad id or kind"))
            continue
        st, n, _ = state(jobs, iid)
        if paused or st in ("running", "done") or (st == "failed" and n > retries):
            report.append((iid, "compute", "paused" if paused and st not in ("running", "done") else st))
            continue
        if running >= max_running:
            report.append((iid, "compute", f"waiting (max_running {max_running})"))
            continue
        parallel = max(1, min(int(x.get("parallel", 1)), 40))
        gh("workflow", "run", "worker-job.yml", "-R", REPO, "-f", f"id={iid}", "-f", f"kind={kind}",
           "-f", f"request={x.get('request', '')}", "-f", f"parallel={parallel}")
        running += 1
        report.append((iid, "compute", f"started ({kind}, {parallel} runner(s))" + (" again" if st == "failed" else "")))

    # ai
    ais = runs("worker-ai.yml")
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    started = sum(1 for r in ais if dt.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) > since)
    for x in [x for x in (b.get("ai") or []) if isinstance(x, dict)]:
        iid = str(x.get("id", ""))
        if not ID.match(iid) or not str(x.get("task", "")).strip():
            report.append((iid, "ai", "skipped: bad id or empty task"))
            continue
        st, n, _ = state(ais, iid)
        if paused or st in ("running", "done") or (st == "failed" and n > retries):
            report.append((iid, "ai", "paused" if paused and st not in ("running", "done") else st))
            continue
        if started >= ai_per_day:
            report.append((iid, "ai", f"waiting (ai_per_day {ai_per_day})"))
            continue
        gh("workflow", "run", "worker-ai.yml", "-R", REPO, "-f", f"id={iid}")
        started += 1
        report.append((iid, "ai", "started" + (" again" if st == "failed" else "")))

    lines = ["| item | type | state |", "|---|---|---|"] + [f"| {a} | {t} | {s} |" for a, t, s in report]
    print("\n".join(lines))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"Board `workers/{OWNER}.yml`{' (paused)' if paused else ''}\n\n" + "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
