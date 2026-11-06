#!/usr/bin/env python3
"""Builds one AI item's prompt for worker-ai.yml: workers/ai-preamble.md plus the item's task from the board.
Usage: ai_task.py <owner> <item id>. Writes the prompt to $RUNNER_TEMP/prompt.md (or stdout) and model/turns to
$GITHUB_OUTPUT."""
from __future__ import annotations

import os
import sys
import urllib.request

import yaml

BUDGET = {"small": 25, "medium": 60, "large": 120}
MODEL = "claude-sonnet-5-5"


def main(owner: str, iid: str) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.environ.get("RC_BOARD")
    if path:
        b = yaml.safe_load(open(path)) or {}
    else:
        up = os.environ.get("RC_UPSTREAM", "Harshu-Pande/ratecommons")
        with urllib.request.urlopen(f"https://raw.githubusercontent.com/{up}/main/workers/{owner.lower()}.yml",
                                    timeout=30) as r:
            b = yaml.safe_load(r.read()) or {}
    item = next((x for x in (b.get("ai") or []) if isinstance(x, dict) and str(x.get("id")) == iid), None)
    if not item:
        print(f"no ai item {iid} on the board (removed?)", file=sys.stderr)
        return 1
    turns = int(item.get("turns") or BUDGET.get(str(item.get("budget", "small")), BUDGET["small"]))
    model = str(item.get("model") or MODEL)
    prompt = (open(os.path.join(here, "ai-preamble.md")).read().strip()
              + f"\n\nTask id: {iid}\nTurn budget: {turns}\n\n" + str(item["task"]).strip() + "\n")
    out = os.path.join(os.environ.get("RUNNER_TEMP", "."), "prompt.md")
    open(out, "w").write(prompt)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"turns={min(turns, 200)}\nmodel={model}\nprompt_file={out}\n")
    else:
        print(prompt)
        print(f"turns={turns} model={model}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
