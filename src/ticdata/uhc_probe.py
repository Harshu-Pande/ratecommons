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
        for chunk in r.iter_content(8 << 20):
            comp_n += len(chunk)
            out = d.decompress(chunk)
            if start is None:
                head += out
                pos = [(head.find(k), k) for k in KEYS if head.find(k) >= 0]
                if pos:
                    p, first_key = min(pos)
                    start = p
                    out = head[p:]
                    header = head[:p]
                else:
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
        try:
            r = body_hash(e["url"], head_mb << 20, s)
        except Exception as ex:
            r = {"error": repr(ex)[:300]}
        return {"group": g, "name": e["name"], "size": e["size"], **r}
    with ThreadPoolExecutor(8) as ex:
        res["results"] = list(ex.map(one, picks))
    # whole-body proof on pairs from the biggest head-hash cluster
    from collections import defaultdict

    cl = defaultdict(list)
    for r in res["results"]:
        if r.get("body_sha256"):
            cl[r["body_sha256"]].append(r)
    res["head_clusters"] = sorted((len(v) for v in cl.values()), reverse=True)
    pair = max(cl.values(), key=len)[:full] if cl else []
    byname = {e["name"]: e for _, e in picks}
    with ThreadPoolExecutor(2) as ex:
        res["full"] = list(ex.map(lambda r: {"name": r["name"], **body_hash(byname[r["name"]]["url"], None, s)}, pair))
    return res
