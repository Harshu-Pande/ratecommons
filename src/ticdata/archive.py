"""Archive each payer's raw indexes as served, every day, keeping only changes.

Payers keep no history and CMS requires no retention, so these raw manifests are
the provenance for every fact we publish. Layout in the dataset repo:
  manifests/YYYY-MM-DD/<payer>/<file>.gz   raw bytes, gzip-wrapped
  entries/YYYY-MM-DD/<payer>.jsonl.gz      normalized file list
  checks/YYYY-MM-DD.json                   counts + sha256, written every run
  state/sha256.json                        last archived sha256 per source
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path

from . import discover
from .net import new_session


def collect(out: Path, payers: list[str]) -> dict:
    day = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    s = new_session()
    summary = {"date": day, "payers": {}, "sha256": {}}
    for p in payers:
        try:
            raw, entries = discover.PAYERS[p](s)
        except Exception as ex:
            summary["payers"][p] = {"error": repr(ex)[:300]}
            continue
        for name, data in raw.items():
            path = out / "manifests" / day / (name + ".gz")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(data, 6))
            summary["sha256"][name] = hashlib.sha256(data).hexdigest()
        ep = out / "entries" / day / f"{p}.jsonl.gz"
        ep.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(ep, "wt") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        kinds: dict = {}
        for e in entries:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        summary["payers"][p] = {"files_listed": kinds, "raw_bytes": sum(len(v) for v in raw.values())}
    (out / "checks").mkdir(parents=True, exist_ok=True)
    (out / "checks" / f"{day}.json").write_text(json.dumps(summary, indent=2))
    return summary


def upload(out: Path, summary: dict, repo_id: str) -> dict:
    """Upload only sources whose bytes changed since the last archived run."""
    from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

    from .hfio import dataset, token_for

    token = token_for(dataset(repo_id))
    api = HfApi(token=token)
    try:
        prev = json.loads(Path(hf_hub_download(repo_id, "state/sha256.json", repo_type="dataset",
                                               token=token)).read_text())
    except Exception:
        prev = {}
    day = summary["date"]
    changed = [n for n, h in summary["sha256"].items() if prev.get(n) != h]
    ops = [CommitOperationAdd(f"checks/{day}.json", str(out / "checks" / f"{day}.json"))]
    payers_changed = {n.split("/")[0] for n in changed}
    for n in changed:
        ops.append(CommitOperationAdd(f"manifests/{day}/{n}.gz", str(out / "manifests" / day / (n + ".gz"))))
    for p in payers_changed:
        f = out / "entries" / day / f"{p}.jsonl.gz"
        if f.exists():
            ops.append(CommitOperationAdd(f"entries/{day}/{p}.jsonl.gz", str(f)))
    state = {**prev, **summary["sha256"]}
    state_path = out / "sha256.json"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    ops.append(CommitOperationAdd("state/sha256.json", str(state_path)))
    api.create_commit(repo_id, operations=ops, repo_type="dataset",
                      commit_message=f"manifests {day}: {len(changed)} changed source(s)")
    return {"changed": changed, "files_committed": len(ops)}
