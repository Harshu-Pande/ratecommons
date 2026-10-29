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
from pathlib import Path

from . import discover
from .identity import _fetch as fetch_to_file
from .net import new_session, resolve

PAYERS = {"cigna": discover.cigna, "uhc": discover.uhc, "aetna": discover.aetna, "bcbs": discover.bcbs, "anthem": discover.anthem}


def file_key(name: str) -> str:
    base = re.sub(r"(\.json)?(\.gz|\.zip)?$", "", name.rsplit("/", 1)[-1])
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:200]


# payers whose shards count as mapped only once their run has written shard-NNN-status.json with no failures:
# each chunk of a running shard uploads its own metas.json, so "has a metas.json" let the orchestrator reduce
# UHC wave 3 while its shards were still parsing (2026-10-28)
STATUS_REQUIRED = {"uhc", "bcbs"}  # bcbs: shards 24+ have status files; waves added later have several chunks per shard


def shard_status(bucket: str, release: str, payer: str) -> dict[int, list[str]]:
    """{shard: failed file names} from the shard status files in the work bucket."""
    import json as _json
    import re as _re

    from huggingface_hub import HfFileSystem, list_bucket_tree

    fs, out = HfFileSystem(), {}
    for i in list_bucket_tree(bucket, prefix=f"map/{release}/{payer}/", recursive=False):
        m = _re.search(r"/shard-(\d+)-status\.json$", i.path)
        if m:
            out[int(m.group(1))] = _json.loads(fs.read_text(f"buckets/{bucket}/{i.path}"))["failed"]
    return out


def wave_ready(bucket: str, release: str, payer: str, shards: tuple[int, int]) -> list[str]:
    """Reasons a wave's shards are not ready to reduce (empty when ready)."""
    if payer not in STATUS_REQUIRED:
        return []
    st = shard_status(bucket, release, payer)
    why = []
    for sh in range(shards[0], shards[1] + 1):
        if sh not in st:
            why.append(f"shard {sh}: no status file (still mapping, or mapped before status files)")
        elif st[sh]:
            why.append(f"shard {sh}: {len(st[sh])} failed file(s), e.g. {st[sh][0]}")
    return why


def release_of(name: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-\d{2}", name.rsplit("/", 1)[-1])
    return f"{m.group(1)}-{m.group(2)}" if m else time.strftime("%Y-%m")


def plan(payer: str, shards: int, kind: str = "in_network", limit: int | None = None,
         match: list[str] | None = None, first_shard: int = 0) -> dict:
    """first_shard: number the shards from N (empty shards 0..N-1 keep plan["shards"][n] indexable), so files added
    to a payer after its map (a `match=` plan) land in new shard folders next to the existing ones."""
    s = new_session(pool=32)
    _, entries = PAYERS[payer](s)
    files = sorted((e for e in entries if e["kind"] == kind), key=lambda e: e["name"])
    seen, uniq = set(), []
    for e in files:  # the same URL can be listed under many plans
        k = e["url"].split("?", 1)[0]
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    if match:  # a hand-picked subset of files: names containing any of these substrings, or "by:<company>" for every
        # file a company's index lists (bcbs: listed_by)
        uniq = [e for e in uniq if any(e.get("listed_by") == m[3:] if m.startswith("by:") else m in e["name"] for m in match)]
    # Whole-file duplicates (same gzip trailer CRC32 + ISIZE, i.e. same decompressed content, from `uhc-tails`): parse one, record
    # the rest as duplicates of it so their plan/network membership can be attached at merge (nothing is dropped).
    duplicates = {}
    tails = os.environ.get("TIC_DUP_TAILS")
    if tails:
        from huggingface_hub import hf_hub_download

        rows = json.load(open(hf_hub_download("ratecommons/ops", tails, repo_type="dataset")))["rows"]
        key = {r["name"]: (r["crc32"], r["isize"]) for r in rows if "crc32" in r}  # same content, any compression
        rep, keep = {}, []
        for e in uniq:
            k = key.get(e["name"])
            if k is None:
                keep.append(e)
            elif k in rep:
                duplicates[e["name"]] = rep[k]
            else:
                rep[k] = e["name"]
                keep.append(e)
        uniq = keep
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
    # Contiguous runs in size order: near-duplicate files (same network family, sizes within a
    # few KB) land in the same shard, where the shared seen-blocks set writes their facts once.
    total = sum(e["size"] or 0 for e in uniq)
    target = total / max(shards, 1)
    load = [0] * shards
    assign: list[list[dict]] = [[] for _ in range(shards)]
    i = 0
    for e in sorted(uniq, key=lambda e: (-(e["size"] or 0), e["name"])):
        if load[i] >= target and i < shards - 1:
            i += 1
        assign[i].append({k: e.get(k) for k in ("name", "url", "size", "kind")})
        load[i] += e["size"] or 0
    return {"payer": payer, "kind": kind, "files": len(uniq), "bytes": sum(load), "duplicates": duplicates,
            "shards": [{"shard": i, "bytes": 0, "files": []} for i in range(first_shard)] +
                      [{"shard": first_shard + i, "bytes": load[i], "files": a} for i, a in enumerate(assign)]}


CHUNK_FILES = int(os.environ.get("TIC_CHUNK_FILES", "25"))
CHUNK_BYTES = int(os.environ.get("TIC_CHUNK_GB", "12")) << 30  # staged output per chunk, for runner disk


def _run_streaming(cmd: list[str], env: dict | None = None):
    """Run a command, echo its stderr live (progress shows in the job log even if the job is
    killed) and return a CompletedProcess with stdout and the last 20 kB of stderr."""
    import subprocess
    import sys
    import threading

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         env={**os.environ, **(env or {})})
    tail: list[str] = []

    def pump():
        for line in p.stderr:
            sys.stderr.write(line)
            sys.stderr.flush()
            tail.append(line)
            if len(tail) > 400:
                del tail[:200]

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    out = p.stdout.read()
    p.wait()
    t.join(timeout=10)
    return subprocess.CompletedProcess(cmd, p.returncode, out, "".join(tail)[-20000:])


def run_shard(plan_doc: dict, shard: int, workdir: str = "/tmp/tic", upload_bucket: str | None = None,
              token=None, restricted_bucket: str | None = None, restricted_token=None,
              chunk_files: int = CHUNK_FILES, chunk_out: str | None = None) -> dict:
    """Parse each file of one shard, then upload the outputs in chunks of `chunk_files` files,
    each chunk merged into one set of tables (consolidate.py) under
    map/<release>/<payer>/shard-<NNN>-<CC>/.

    The shard shares one seen-blocks set and one record cache across its files, so near-duplicate
    files write their facts once and skip byte-identical records. Code text we may not republish
    (licensing.py) is split off before anything is uploaded: the public work bucket gets the
    redacted code tables, the private restricted bucket gets the raw text.
    """
    from .consolidate import consolidate
    from .licensing import redact_code_file
    from .parse import parse_file

    if upload_bucket and not restricted_bucket:
        raise ValueError("uploading map outputs needs the restricted bucket for withheld code text")

    payer = plan_doc["payer"]
    files = plan_doc["shards"][shard]["files"]
    s = new_session()
    if os.path.exists(workdir):
        shutil.rmtree(workdir)
    os.makedirs(workdir)
    seen_path = os.path.join(workdir, "seen_blocks.bin")  # blocks already written by this shard
    rcache_path = os.path.join(workdir, "record_cache.bin")  # records already parsed by this shard
    stage = os.path.join(workdir, "stage")  # per-file outputs waiting for their chunk upload
    os.makedirs(stage)
    results: list[dict] = []
    staged: list[tuple[str, str, str]] = []  # (file key, output folder, release)
    chunks: list[dict] = []

    def flush():
        if not staged:
            return
        rel = staged[0][2]
        cdir = os.path.join(workdir, "chunk")
        shutil.rmtree(cdir, ignore_errors=True)
        info = {"chunk": len(chunks), "release": rel, "files": [k for k, _, _ in staged]}
        t0 = time.time()
        info["tables"] = consolidate([(k, d) for k, d, _ in staged], cdir)["tables"]
        texts = [(k, f"{d}.code_text.parquet") for k, d, _ in staged if os.path.exists(f"{d}.code_text.parquet")]
        prefix = f"map/{rel}/{payer}/shard-{shard:03d}-{len(chunks):02d}"
        if upload_bucket:
            from huggingface_hub import batch_bucket_files

            if texts:  # private first: never publish without keeping the raw text
                import pyarrow as pa
                import pyarrow.parquet as pq

                tables = [pq.read_table(t).append_column("file_key", pa.array([k] * pq.ParquetFile(t).metadata.num_rows))
                          for k, t in texts]
                pq.write_table(pa.concat_tables(tables), f"{cdir}.code_text.parquet", compression="zstd")
                batch_bucket_files(restricted_bucket, add=[(f"{cdir}.code_text.parquet", f"{prefix}/code_text.parquet")],
                                   token=restricted_token() if callable(restricted_token) else restricted_token)
            adds = [(os.path.join(root, f), f"{prefix}/{os.path.relpath(os.path.join(root, f), cdir)}")
                    for root, _, fs in os.walk(cdir) for f in sorted(fs)]
            batch_bucket_files(upload_bucket, add=adds, token=token() if callable(token) else token)
            info["uploaded"] = prefix
        if chunk_out:  # keep the chunk locally (tests, local runs)
            dest = os.path.join(chunk_out, os.path.basename(prefix))
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(cdir, dest)
        info["seconds"] = round(time.time() - t0, 1)
        chunks.append(info)
        print(json.dumps({"chunk": info["chunk"], "files": len(info["files"]), "seconds": info["seconds"]}), flush=True)
        for _, d, _ in staged:
            shutil.rmtree(d, ignore_errors=True)
            if os.path.exists(f"{d}.code_text.parquet"):
                os.remove(f"{d}.code_text.parquet")
        staged.clear()
        shutil.rmtree(cdir, ignore_errors=True)

    for e in files:
        key, rel = file_key(e["name"]), e.get("release") or release_of(e["name"])
        staged_bytes = sum(f.stat().st_size for _, d, _ in staged for f in __import__("pathlib").Path(d).rglob("*")
                           if f.is_file())
        if staged and (staged[0][2] != rel or len(staged) >= chunk_files or staged_bytes >= CHUNK_BYTES):
            flush()
        local = os.path.join(workdir, "in.bin")
        outdir = os.path.join(stage, key)
        rec = {"name": e["name"], "key": key, "release": rel, "size": e.get("size")}
        t0 = time.time()
        try:
            rec["download"] = fetch_to_file(e["url"], local, s)
            source = {"payer": payer, "name": e["name"], "url": e["url"].split("?", 1)[0], "size": e.get("size")}
            meta = None
            core = os.environ.get("TIC_CORE")
            if core and os.path.exists(core):
                import subprocess

                threads = os.environ.get("TIC_CORE_THREADS", str(max(1, (os.cpu_count() or 2) - 2)))
                cp = _run_streaming([core, "map", local, outdir, threads, json.dumps(source),
                                     "--seen-blocks", seen_path, "--record-cache", rcache_path],
                                    env={"TIC_SEEN_DIMS": os.path.join(workdir, "seen_dims")})
                if cp.returncode == 0 and "provider_references_after_in_network_unsupported_in_rust" in \
                        json.loads(cp.stdout).get("flags", {}):
                    rec["rust_error"] = "provider_references after in_network: parsed with Python instead"
                    shutil.rmtree(outdir, ignore_errors=True)
                elif cp.returncode == 0:
                    meta = json.loads(cp.stdout)
                    rec["parser"] = "rust"
                else:  # zip input (exit 3) or a failure: fall back to the Python parser
                    rec["rust_exit"] = cp.returncode  # negative: killed by that signal (-9: out of memory)
                    rec["rust_error"] = (cp.stderr or "")[-1500:]
                    shutil.rmtree(outdir, ignore_errors=True)
                    # the Python parser is ~10x slower and holds more in memory: on a big file after a Rust
                    # failure it took the runner down (BCBS, Oct 2026). Fail the file instead; it is retried later.
                    if cp.returncode != 3 and os.path.getsize(local) > (2 << 30):
                        raise RuntimeError("Rust parser failed on a large file; not falling back to Python")
            if meta is None:
                seen = set()
                if os.path.exists(seen_path):
                    b = open(seen_path, "rb").read()
                    seen = {b[i:i + 16] for i in range(0, len(b), 16)}
                meta = parse_file(local, outdir, source=source, seen_blocks=seen)
                with open(seen_path, "wb") as fh:
                    fh.write(b"".join(seen))
                rec["parser"] = "python"
            rec.update({k: meta.get(k) for k in ("counts", "flags", "tables", "seconds", "layout",
                                                 "tail_crc32", "tail_isize", "header", "json_bytes", "refs_hash")})
            if os.path.exists(os.path.join(outdir, "code.parquet")):
                rec["code_text"] = redact_code_file(os.path.join(outdir, "code.parquet"), f"{outdir}.code_text.parquet")
            staged.append((key, outdir, rel))
            rec["ok"] = True
        except Exception as ex:
            rec["ok"] = False
            rec["error"] = repr(ex)[:1000]
            rec["traceback"] = traceback.format_exc()[-3000:]
            shutil.rmtree(outdir, ignore_errors=True)
        finally:
            rec["wall_seconds"] = round(time.time() - t0, 1)
            import resource

            rec["max_rss_mb"] = round(max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                                          resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) / 1024)
            if os.path.exists(local):
                os.remove(local)
        results.append(rec)
        print(json.dumps({k: rec.get(k) for k in ("name", "ok", "wall_seconds", "error")}), flush=True)
    flush()
    # a shard whose chunks are uploaded can still have failed files: the status file says which, so the
    # orchestrator does not reduce a wave without them (it is rewritten by every run of the shard)
    rel_of = lambda e: e.get("release") or release_of(e["name"])  # noqa: E731
    for rel in sorted({rel_of(e) for e in files}):
        status = {"shard": shard, "files": sum(1 for e in files if rel_of(e) == rel),
                  "failed": [r["name"] for r in results if not r["ok"] and r["release"] == rel]}
        name = f"shard-{shard:03d}-status.json"
        path = os.path.join(workdir, name)
        Path(path).write_text(json.dumps(status))
        if upload_bucket:
            from huggingface_hub import batch_bucket_files

            batch_bucket_files(upload_bucket, add=[(path, f"map/{rel}/{payer}/{name}")],
                               token=token() if callable(token) else token)
        if chunk_out:
            os.makedirs(chunk_out, exist_ok=True)
            shutil.copy(path, os.path.join(chunk_out, name))
    return {"payer": payer, "shard": shard, "files": len(files), "ok": sum(r["ok"] for r in results),
            "chunks": chunks, "results": results}
