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
    r = session.get(url, headers={"Range": f"bytes=-{n}"}, timeout=300)
    b = r.content
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
