#!/usr/bin/env python3
"""What a helper's fork is doing: python workers/status.py <github user> [--fetch <item id>]

Lists the fork's worker-job and worker-ai runs (item id, state, link). --fetch downloads an AI item's `handoff`
artifact (patch + summary) into workers/handoff/<item id>/ for review; apply with `git am`."""
from __future__ import annotations

import json
import subprocess
import sys


def gh(*a: str) -> str:
    return subprocess.run(["gh", *a], check=True, capture_output=True, text=True).stdout


def main(argv: list[str]) -> int:
    user = argv[1]
    repo = f"{user}/ratecommons"
    if len(argv) > 3 and argv[2] == "--fetch":
        iid = argv[3]
        rs = json.loads(gh("run", "list", "-R", repo, "-w", "worker-ai.yml", "-L", "200",
                           "--json", "databaseId,displayTitle,conclusion"))
        r = next((x for x in rs if x["displayTitle"] == iid), None)
        if not r:
            print(f"no worker-ai run named {iid}")
            return 1
        dest = f"workers/handoff/{iid}"
        gh("run", "download", str(r["databaseId"]), "-R", repo, "-n", "handoff", "-D", dest)
        print(f"{dest}: " + ", ".join(subprocess.run(["ls", dest], capture_output=True, text=True).stdout.split()))
        return 0
    for wf in ("worker.yml", "worker-job.yml", "worker-ai.yml"):
        try:
            rs = json.loads(gh("run", "list", "-R", repo, "-w", wf, "-L", "1" if wf == "worker.yml" else "30",
                               "--json", "databaseId,displayTitle,status,conclusion,createdAt,url"))
        except subprocess.CalledProcessError:
            print(f"{wf}: no runs (workflow missing or never run)")
            continue
        print(f"== {wf}")
        for r in rs:
            st = r["conclusion"] or r["status"]
            print(f"  {r['createdAt'][:16]}  {st:11s} {r['displayTitle'][:50]:50s} {r['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
