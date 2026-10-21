"""Map stage orchestration: plan shards for one payer, then parse each shard's files.

plan:  discover the payer's in-network files, size them, and assign files to N shards
       (largest first, each to the least-loaded shard) so runners finish together.
shard: for each assigned file, download it whole to local disk, parse it, upload the
       per-file tables to the work bucket under map/<release>/<payer>/<file key>/,
       and delete the local copies.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import discover
from .identity import _fetch as fetch_to_file
from .net import new_session, resolve

PAYERS = {"cigna": discover.cigna, "uhc": discover.uhc, "aetna": discover.aetna}


def file_key(name: str) -> str:
    base = re.sub(r"(\.json)?(\.gz|\.zip)?$", "", name.rsplit("/", 1)[-1])
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:200]


def release_of(name: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-\d{2}", name.rsplit("/", 1)[-1])
    return f"{m.group(1)}-{m.group(2)}" if m else time.strftime("%Y-%m")


def plan(payer: str, shards: int, kind: str = "in_network", limit: int | None = None) -> dict:
    s = new_session(pool=32)
    _, entries = PAYERS[payer](s)
    files = sorted((e for e in entries if e["kind"] == kind), key=lambda e: e["name"])
    seen, uniq = set(), []
    for e in files:  # the same URL can be listed under many plans
        k = e["url"].split("?", 1)[0]
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    if limit:
        uniq = uniq[:limit]

    def size_of(e):
        if e.get("size"):
            return e
        try:
            r = resolve(e["url"], s)
            e = {**e, "size": r.size, "url": r.url}
        except Exception as ex:
            e = {**e, "size": 0, "resolve_error": repr(ex)[:200]}
        return e

    with ThreadPoolExecutor(8) as ex:
        uniq = list(ex.map(size_of, uniq))
    load = [0] * shards
    assign: list[list[dict]] = [[] for _ in range(shards)]
    for e in sorted(uniq, key=lambda e: -(e["size"] or 0)):
        i = load.index(min(load))
        assign[i].append({k: e.get(k) for k in ("name", "url", "size", "kind")})
        load[i] += e["size"] or 0
    return {"payer": payer, "kind": kind, "files": len(uniq), "bytes": sum(load),
            "shards": [{"shard": i, "bytes": load[i], "files": a} for i, a in enumerate(assign)]}


def run_shard(plan_doc: dict, shard: int, workdir: str = "/tmp/tic", upload_bucket: str | None = None,
              token=None) -> dict:
    from .parse import parse_file

    payer = plan_doc["payer"]
    files = plan_doc["shards"][shard]["files"]
    s = new_session()
    os.makedirs(workdir, exist_ok=True)
    results = []
    for e in files:
        key, rel = file_key(e["name"]), release_of(e["name"])
        local = os.path.join(workdir, "in.bin")
        outdir = os.path.join(workdir, key)
        rec = {"name": e["name"], "key": key, "release": rel, "size": e.get("size")}
        t0 = time.time()
        try:
            rec["download"] = fetch_to_file(e["url"], local, s)
            meta = parse_file(local, outdir, source={"payer": payer, "name": e["name"],
                                                     "url": e["url"].split("?", 1)[0], "size": e.get("size")})
            rec.update({k: meta[k] for k in ("counts", "flags", "tables", "seconds", "layout",
                                             "tail_crc32", "tail_isize", "header")})
            if upload_bucket:
                from huggingface_hub import batch_bucket_files

                prefix = f"map/{rel}/{payer}/{key}"
                adds = [(os.path.join(root, f), f"{prefix}/{os.path.relpath(os.path.join(root, f), outdir)}")
                        for root, _, fs in os.walk(outdir) for f in sorted(fs)]
                batch_bucket_files(upload_bucket, add=adds, token=token() if callable(token) else token)
                rec["uploaded"] = prefix
            rec["ok"] = True
        except Exception as ex:
            rec["ok"] = False
            rec["error"] = repr(ex)[:1000]
            rec["traceback"] = traceback.format_exc()[-3000:]
        finally:
            rec["wall_seconds"] = round(time.time() - t0, 1)
            import resource

            rec["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
            if os.path.exists(local):
                os.remove(local)
            shutil.rmtree(outdir, ignore_errors=True)
        results.append(rec)
        print(json.dumps({k: rec.get(k) for k in ("name", "ok", "wall_seconds", "error")}), flush=True)
    return {"payer": payer, "shard": shard, "files": len(files), "ok": sum(r["ok"] for r in results),
            "results": results}
