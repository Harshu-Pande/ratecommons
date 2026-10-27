"""Are UHC's 15 GB files near-copies? Hash each file's body (everything after the plan header), either the first
N decompressed bytes (cheap) or the whole stream (proof). Files whose whole bodies hash the same carry the
same rates and providers; only the header (plan name, sponsor) differs.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
import zlib
from concurrent.futures import ThreadPoolExecutor

KEYS = (b'"provider_references"', b'"in_network"')


def body_hash(url: str, limit: int | None, session) -> dict:
    t0 = time.time()
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    h = hashlib.sha256()
    head = b""
    start = None
    raw_n = comp_n = 0
    first_key = None
    with session.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        def pieces():
            nonlocal comp_n, d
            for chunk in r.iter_content(1 << 20):
                comp_n += len(chunk)
                buf = chunk
                while buf:  # bounded output: JSON can inflate 50-100x
                    yield d.decompress(buf, 32 << 20)
                    buf = d.unconsumed_tail
                    if d.eof:  # multi-member gzip (UHC's are): the next member starts in unused_data
                        buf = d.unused_data + buf
                        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        for out in pieces():
            if start is None:
                head += out
                pos = [(head.find(k), k) for k in KEYS if head.find(k) >= 0]
                if pos:
                    p, first_key = min(pos)
                    start = p
                    out = head[p:]
                    header = head[:p]
                else:
                    if len(head) > (64 << 20):
                        raise ValueError("no provider_references/in_network key in the first 64 MB")
                    continue
            if limit is not None and raw_n + len(out) > limit:
                out = out[:limit - raw_n]
            h.update(out)
            raw_n += len(out)
            if limit is not None and raw_n >= limit:
                break
    hdr = header.decode("utf-8", "replace")
    plan = re.findall(r'"(plan_name|plan_sponsor_name|reporting_entity_name)"\s*:\s*"([^"]*)"', hdr)
    return {"body_sha256": h.hexdigest(), "body_bytes": raw_n, "compressed_read": comp_n,
            "first_key": first_key.decode() if first_key else None, "header_bytes": len(header),
            "header": dict(plan), "seconds": round(time.time() - t0, 1), "complete": limit is None}


def tail_info(url: str, session, n: int = 8 << 20) -> dict:
    """Last n compressed bytes by HTTP Range: gzip member starts in them and hashes of the last 1 MB and of the
    bytes after the last member start. Identical bodies split into independently compressed members end in
    byte-identical members, so equal tails are a cheap duplicate test that needs no download."""
    t0 = time.time()
    with session.get(url, headers={"Range": f"bytes=-{n}"}, timeout=300, stream=True) as r:
        if r.status_code != 206:  # Range ignored: the body is the whole 15 GB file, do not read it
            return {"tail_status": r.status_code, "tail_headers": dict(r.headers), "_tail": b""}
        b = b"".join(r.iter_content(1 << 20))[-n:]
    starts = [m.start() for m in re.finditer(b"\x1f\x8b\x08", b)]
    last = b[starts[-1]:] if starts else b""
    return {"tail_status": r.status_code, "tail_bytes": len(b), "tail_members": len(starts),
            "tail_sha_1mb": hashlib.sha256(b[-(1 << 20):]).hexdigest(),
            "tail_last_member_sha": hashlib.sha256(last).hexdigest() if last else None,
            "tail_last_member_bytes": len(last), "tail_seconds": round(time.time() - t0, 1), "_tail": b}


def common_suffix(a: bytes, b: bytes) -> int:
    n, m = 0, min(len(a), len(b))
    while n < m and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def probe(head_mb: int = 256, full: int = 2, sample: int = 40, seed: int = 7) -> dict:
    from .discover import uhc
    from .net import new_session

    s = new_session(pool=16)
    _, entries = uhc(s)
    inn = [e for e in entries if e["kind"] == "in_network" and (e.get("size") or 0) > 1e9]
    code = lambda n: re.sub(r"_in-network-rates.*$", "", n).split("_")[-1]
    rnd = random.Random(seed)
    groups = {"0L": [e for e in inn if code(e["name"]) == "0L"],
              "UMR-14.9GB": [e for e in inn if "UMR" in e["name"] and abs(e["size"] - 14.88e9) < 0.03e9],
              "C2": [e for e in inn if code(e["name"]) == "C2"],
              "any": inn}
    picks = []
    for g, es in groups.items():
        for e in rnd.sample(es, min(len(es), sample // 4)):
            picks.append((g, e))
    res: dict = {"files": len(inn), "head_mb": head_mb, "results": []}

    def one(ge):
        g, e = ge
        out = {"group": g, "name": e["name"], "size": e["size"]}
        try:
            out.update(tail_info(e["url"], s))
        except Exception as ex:
            out["tail_error"] = repr(ex)[:300]
        try:
            out.update(body_hash(e["url"], head_mb << 20, s))
        except Exception as ex:
            out["error"] = repr(ex)[:300]
        print(json.dumps({k: v for k, v in out.items() if k != "_tail"})[:500], flush=True)
        return out
    with ThreadPoolExecutor(4) as ex:
        res["results"] = list(ex.map(one, picks))
    # how much of the compressed tail two files share, within each group (first file vs the others)
    res["tail_common_suffix"] = {}
    for g in groups:
        rs = [r for r in res["results"] if r["group"] == g and r.get("_tail")]
        if len(rs) > 1:
            res["tail_common_suffix"][g] = [common_suffix(rs[0]["_tail"], r["_tail"]) for r in rs[1:]]
    for r in res["results"]:
        r.pop("_tail", None)
    print(json.dumps({"tail_common_suffix": res["tail_common_suffix"]}), flush=True)
    # whole-body proof on pairs from the biggest head-hash cluster
    from collections import defaultdict

    cl = defaultdict(list)
    for r in res["results"]:
        if r.get("body_sha256"):
            cl[r["body_sha256"]].append(r)
    res["head_clusters"] = sorted((len(v) for v in cl.values()), reverse=True)
    pair = max(cl.values(), key=len)[:full] if cl and full else []
    byname = {e["name"]: e for _, e in picks}
    with ThreadPoolExecutor(2) as ex:
        res["full"] = list(ex.map(lambda r: {"name": r["name"], **body_hash(byname[r["name"]]["url"], None, s)}, pair))
    return res


def head_bytes(url: str, limit: int, session) -> bytes:
    """First `limit` decompressed bytes of a (multi-member) gzip file."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = []
    n = 0
    with session.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        for chunk in r.iter_content(1 << 20):
            buf = chunk
            while buf and n < limit:
                o = d.decompress(buf, 32 << 20)
                out.append(o)
                n += len(o)
                buf = d.unconsumed_tail
                if d.eof:
                    buf = d.unused_data + buf
                    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            if n >= limit:
                break
    return b"".join(out)[:limit]


def diff(match: str = "_0L_", n: int = 4, head_mb: int = 256) -> dict:
    """How near-copies differ: first differing offset with context, and overlap of provider_references records
    with and without their provider_group_id numbers."""
    from .discover import uhc
    from .net import new_session

    s = new_session(pool=8)
    _, entries = uhc(s)
    es = [e for e in entries if e["kind"] == "in_network" and match in e["name"]][:n]
    with ThreadPoolExecutor(4) as ex:
        heads = list(ex.map(lambda e: head_bytes(e["url"], head_mb << 20, s), es))
    res = {"files": [e["name"] for e in es], "pairs": []}
    recs = []
    for h in heads:
        parts = re.split(rb'\{\s*"provider_groups"\s*:', h)[1:-1]  # the last one may be cut off
        ids = [hashlib.md5(p).hexdigest() for p in parts]
        # without the per-file fields: the group number and the network (plan) label
        noid = [hashlib.md5(re.sub(rb'"network_name"\s*:\s*\[[^\]]*\]', b"",
                                   re.sub(rb'"provider_group_id"\s*:\s*\d+', b"", p))).hexdigest() for p in parts]
        recs.append((ids, noid, len(parts)))
    for i in range(1, len(heads)):
        a, b = heads[0], heads[i]
        k = next((j for j in range(min(len(a), len(b))) if a[j] != b[j]), None)
        sa, sb = set(recs[0][0]), set(recs[i][0])
        na, nb = set(recs[0][1]), set(recs[i][1])
        res["pairs"].append({
            "file": es[i]["name"], "first_diff": k,
            "a_context": a[max(0, (k or 0) - 300):(k or 0) + 300].decode("utf-8", "replace") if k is not None else None,
            "b_context": b[max(0, (k or 0) - 300):(k or 0) + 300].decode("utf-8", "replace") if k is not None else None,
            "records": [recs[0][2], recs[i][2]],
            "same_records_with_ids": len(sa & sb), "same_records_without_ids": len(na & nb),
            "union_without_ids": len(na | nb),
            "network_names": [sorted(set(re.findall(rb'"network_name"\s*:\s*\[([^\]]*)\]', heads[0][:50_000_000])))[:3],
                              sorted(set(re.findall(rb'"network_name"\s*:\s*\[([^\]]*)\]', heads[i][:50_000_000])))[:3]]})
        res["pairs"][-1]["network_names"] = [[x.decode("utf-8", "replace") for x in y] for y in res["pairs"][-1]["network_names"]]
        print(json.dumps(res["pairs"][-1])[:3000], flush=True)
    return res


def tails(threads: int = 16, n: int = 1 << 20, match: str = "") -> dict:
    """Last n compressed bytes of every UHC in-network file (guarded range reads): the last gzip member's
    CRC32/ISIZE, how many members start in the window and a hash of the last member. Files with identical
    rates end in identical members whatever their headers say."""
    from .discover import uhc
    from .net import fetch_range, new_session

    s = new_session(pool=threads * 2)
    _, entries = uhc(s)
    es = [e for e in entries if e["kind"] == "in_network" and (e.get("size") or 0) > n and match in e["name"]]
    t0 = time.time()

    def one(e):
        try:
            b = fetch_range(e["url"], e["size"] - n, e["size"] - 1, s, total=e["size"])
            starts = [m.start() for m in re.finditer(b"\x1f\x8b\x08", b)]
            last = b[starts[-1]:] if starts else b""
            return {"name": e["name"], "size": e["size"], "crc32": b[-8:-4].hex(), "isize": int.from_bytes(b[-4:], "little"),
                    "members_in_window": len(starts), "last_member_bytes": len(last),
                    "last_member_sha": hashlib.sha256(last).hexdigest()[:24] if last else None,
                    "window_sha": hashlib.sha256(b).hexdigest()[:24]}
        except Exception as ex:
            return {"name": e["name"], "size": e["size"], "error": repr(ex)[:200]}
    with ThreadPoolExecutor(threads) as ex:
        rows = list(ex.map(one, es))
    from collections import Counter

    c = Counter((r.get("crc32"), r.get("isize")) for r in rows if "crc32" in r)
    print(json.dumps({"files": len(rows), "errors": sum("error" in r for r in rows), "distinct_tails": len(c),
                      "biggest": c.most_common(10), "seconds": round(time.time() - t0)}, default=str), flush=True)
    return {"files": len(rows), "distinct_tails": len(c), "rows": rows}


def compare_mapped(shards: str = "0,1,2", release: str = "2026-10", payer: str = "uhc") -> dict:
    """Overlap of the parsed content of mapped files (content-hashed ids, so equal content = equal rows):
    rate facts (code, provider set, price list), provider sets and price lists, first shard vs each other."""
    import duckdb

    from .reduce import _fetch, _list
    from .config import load
    from .hfio import bucket as bk, token_for

    b = load().work_bucket
    tok = token_for(bk(b))
    nums = [int(x) for x in shards.split(",")]
    prefix = f"map/{release}/{payer}/"
    allp = _list(b, prefix, tok)
    local = "/tmp/uhc-compare"
    want = [p for p in allp if any(f"/shard-{n:03d}-" in p for n in nums)
            and (p.endswith(("provider_set.parquet", "price_list.parquet", "metas.json")) or "/rate_fact/" in p)]
    _fetch(b, want, local, prefix, tok)
    con = duckdb.connect()
    con.execute("SET memory_limit = '12GB'; SET threads = 4; SET preserve_insertion_order = false")
    con.execute(f"SET temp_directory = '{local}/tmp'")
    import glob
    import os

    dirs = sorted(d for d in glob.glob(f"{local}/shard-*") if os.path.isdir(d))
    res = {"files": [], "pairs": []}
    for d in dirs:
        metas = json.load(open(f"{d}/metas.json"))
        res["files"].append([(m.get("source") or {}).get("name") for m in metas])
    # rate facts are partitioned by code hash, so part k of one file only meets part k of another:
    # compare part by part to stay inside memory and disk
    tot = [dict(first=0, this=0, both=0, only_this_same_code_ps=0) for _ in dirs[1:]]
    for k in range(16):
        con.execute(f"CREATE OR REPLACE TABLE f0 AS SELECT DISTINCT code_id, ps_id, pl_id FROM read_parquet('{dirs[0]}/rate_fact/part-{k:02d}.parquet')")
        for i, d in enumerate(dirs[1:]):
            con.execute(f"CREATE OR REPLACE TABLE fi AS SELECT DISTINCT code_id, ps_id, pl_id FROM read_parquet('{d}/rate_fact/part-{k:02d}.parquet')")
            t = tot[i]
            t["first"] += con.execute("SELECT count(*) FROM f0").fetchone()[0]
            t["this"] += con.execute("SELECT count(*) FROM fi").fetchone()[0]
            t["both"] += con.execute("SELECT count(*) FROM (SELECT * FROM f0 INTERSECT SELECT * FROM fi)").fetchone()[0]
            t["only_this_same_code_ps"] += con.execute(
                "SELECT count(*) FROM (SELECT * FROM fi EXCEPT SELECT * FROM f0) x SEMI JOIN f0 USING (code_id, ps_id)").fetchone()[0]
        print(json.dumps({"part": k, "so_far": tot}), flush=True)
    for i, d in enumerate(dirs[1:]):
        row = {"file": res["files"][i + 1], "rate_facts": tot[i]}
        for t, f, col in (("provider_sets", "provider_set", "ps_id"), ("price_lists", "price_list", "pl_id")):
            a = con.execute(f"SELECT count(DISTINCT {col}) FROM read_parquet('{dirs[0]}/{f}.parquet')").fetchone()[0]
            b = con.execute(f"SELECT count(DISTINCT {col}) FROM read_parquet('{d}/{f}.parquet')").fetchone()[0]
            both = con.execute(f"SELECT count(*) FROM (SELECT {col} FROM read_parquet('{dirs[0]}/{f}.parquet') "
                               f"INTERSECT SELECT {col} FROM read_parquet('{d}/{f}.parquet'))").fetchone()[0]
            row[t] = {"first": a, "this": b, "both": both}
        res["pairs"].append(row)
        print(json.dumps(row, default=str), flush=True)
    return res


def sketch(shards: str, k: int = 20000, release: str = "2026-10", payer: str = "uhc") -> dict:
    """Bottom-k sketch of each mapped shard's distinct rate facts (hash of code, provider set, price list),
    one rate_fact part on disk at a time, then pairwise Jaccard and containment estimates."""
    import os
    import shutil

    import duckdb

    from .config import load
    from .hfio import bucket as bk, token_for
    from .reduce import _fetch, _list

    b = load().work_bucket
    prefix = f"map/{release}/{payer}/"
    allp = _list(b, prefix, token_for(bk(b)))
    con = duckdb.connect()
    con.execute("SET memory_limit = '12GB'; SET threads = 4; SET preserve_insertion_order = false")
    out = {"k": k, "files": {}}
    for n in [int(x) for x in shards.split(",")]:
        sp = [p for p in allp if f"/shard-{n:03d}-" in p]
        meta = [p for p in sp if p.endswith("metas.json")]
        if not meta:
            continue
        local = f"/tmp/uhc-sketch/{n}"
        _fetch(b, meta, local, prefix, token_for(bk(b)))
        name = [(m.get("source") or {}).get("name") for m in json.load(open(next(
            os.path.join(r, f) for r, _, fs in os.walk(local) for f in fs if f == "metas.json")))]
        hs, total = [], 0
        for part in sorted(p for p in sp if "/rate_fact/" in p):
            _fetch(b, [part], local, prefix, token_for(bk(b)))
            f = os.path.join(local, os.path.relpath(part, prefix))
            total += con.execute(f"SELECT count(DISTINCT hash(code_id, ps_id, pl_id)) FROM read_parquet('{f}')").fetchone()[0]
            hs += [r[0] for r in con.execute(f"SELECT DISTINCT hash(code_id, ps_id, pl_id) h FROM read_parquet('{f}') ORDER BY h LIMIT {k}").fetchall()]
            os.remove(f)
        shutil.rmtree(local, ignore_errors=True)
        out["files"][str(n)] = {"name": name, "facts": total, "sketch": sorted(hs)[:k]}
        print(json.dumps({"shard": n, "name": name, "facts": total}), flush=True)
    keys = sorted(out["files"])
    out["pairs"] = []
    for i, a in enumerate(keys):
        for bkey in keys[i + 1:]:
            A, B = out["files"][a], out["files"][bkey]
            sa, sb = set(A["sketch"]), set(B["sketch"])
            u = sorted(sa | sb)[:k]
            j = sum(1 for h in u if h in sa and h in sb) / max(1, len(u))
            inter = j / (1 + j) * (A["facts"] + B["facts"])
            row = {"a": A["name"], "b": B["name"], "jaccard": round(j, 4),
                   "a_in_b": round(inter / max(1, A["facts"]), 4), "b_in_a": round(inter / max(1, B["facts"]), 4)}
            out["pairs"].append(row)
            print(json.dumps(row), flush=True)
    return out
