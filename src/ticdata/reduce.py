"""Reduce stage: merge one payer-release's per-file map outputs into release tables.

Inputs (work bucket):  map/<release>/<payer>/<file key>/{meta.json, *.parquet, rate_fact/part-XX.parquet}
Outputs (local folder, then the payer's dataset repo under release=<release>/):

  source_file      one row per parsed file: name, url, size, tail fingerprint, header, counts, flags
  network          derived network = distinct file content (size + gzip tail); network_id
  rate_fact/part-XX  each distinct fact once, with its network set (ns_id), sorted by code
  network_set      ns_id -> sorted network_ids
  provider_group, provider_set, price_term, price_list, code   distinct by content ID

History: this first release writes facts with valid_from = release. Later releases write
fact_membership changes only (design: "an unchanged rate writes nothing").

ns_id is md5 over the sorted network IDs, computed inside DuckDB so it is deterministic
for any engine version (DuckDB's hash() is not stable across versions).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

DIMS = {
    "provider_group": "pg_id",
    "provider_set": "ps_id",
    "provider_list": "pli_id",
    "price_term": "pt_id",
    "price_list": "pl_id",
    "code": "code_id",
}


def _list(bucket: str, prefix: str, token) -> list[str]:
    from huggingface_hub import list_bucket_tree

    return [i.path for i in list_bucket_tree(bucket, prefix=prefix, recursive=True, token=token)
            if getattr(i, "type", "file") == "file"]


def _fetch(bucket: str, paths: list[str], dest: str, prefix: str, token) -> list[str]:
    from huggingface_hub import download_bucket_files

    files = [(p, os.path.join(dest, os.path.relpath(p, prefix))) for p in paths]
    for _, local in files:
        os.makedirs(os.path.dirname(local), exist_ok=True)
    for i in range(0, len(files), 200):
        for attempt in range(4):  # transient CAS/xet errors ("error decoding response body") happen
            try:
                download_bucket_files(bucket, files=files[i:i + 200], token=token)
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(15 * (attempt + 1))
    return [local for _, local in files]


def _metas(local_root: str) -> list[tuple[str, dict]]:
    """(file key, meta) for every mapped file: per-file folders (<file key>/meta.json) or
    consolidated chunk folders (<chunk>/metas.json)."""
    from .pipeline import file_key

    out = [(p.parent.name, json.loads(p.read_text())) for p in sorted(Path(local_root).glob("*/meta.json"))]
    for p in sorted(Path(local_root).glob("*/metas.json")):
        out += [(file_key((m.get("source") or {}).get("name") or ""), m) for m in json.loads(p.read_text())]
    return out


def networks(local_root: str, payer: str) -> list[dict]:
    """One row per file: its derived network ID is the content identity of the file."""
    import xxhash

    rows = []
    for key, m in _metas(local_root):
        src = m.get("source") or {}
        content = f"{payer}|{m.get('local_bytes')}|{m.get('tail_crc32')}|{m.get('tail_isize')}"
        rows.append({
            "file_key": key, "name": src.get("name"), "url": src.get("url"),
            "bytes": m.get("local_bytes"), "tail_crc32": m.get("tail_crc32"), "tail_isize": m.get("tail_isize"),
            "network_id": xxhash.xxh3_128_digest(b"net" + content.encode()),
            "header": json.dumps(m.get("header"), sort_keys=True), "counts": json.dumps(m.get("counts")),
            "flags": json.dumps(m.get("flags")), "layout": json.dumps(m.get("layout")),
        })
    return rows


def in_shards(path: str, shards: tuple[int, int] | None) -> bool:
    """True when `shards` is None or the path is in a chunk folder shard-NNN-CC with a <= NNN <= b."""
    if shards is None:
        return True
    import re

    m = re.search(r"/shard-(\d+)-\d+/", path)
    return bool(m) and shards[0] <= int(m.group(1)) <= shards[1]


def reduce_part(payer: str, release: str, part: int, bucket: str, out: str, token=None,
                workdir: str = "/tmp/reduce", shards: tuple[int, int] | None = None, keys: bool = False) -> dict:
    """Merge rate_fact part `part` across every file of the release (or of a wave of shards)."""
    t0 = time.time()
    prefix = f"map/{release}/{payer}/"
    allp = [p for p in _list(bucket, prefix, token) if in_shards(p, shards)]
    want = [p for p in allp if p.endswith("/meta.json") or p.endswith("/metas.json")
            or p.endswith("/file_block.parquet") or p.endswith(f"/rate_fact/part-{part:02d}.parquet")]
    local = os.path.join(workdir, f"p{part:02d}")
    _fetch(bucket, want, local, prefix, token)
    res = reduce_part_local(local, payer, release, part, out, keys=keys, delete_inputs=True)
    res["download_seconds"] = round(time.time() - t0, 1) - res["seconds"]
    return res


def _log(msg: str) -> None:
    """Progress with RSS on stderr, so a job killed for memory still shows its last step."""
    import resource
    import sys

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    print(f"[reduce {time.strftime('%H:%M:%S')}] {msg} (peak rss {rss} MB)", file=sys.stderr, flush=True)


def _duck(workdir: str):
    """A DuckDB on disk with spilling, sized for a 16 GB / 4 vCPU runner."""
    import duckdb

    os.makedirs(f"{workdir}/duck_tmp", exist_ok=True)
    path = f"{workdir}/duck-{time.time_ns()}.db"  # a fresh database per call (connections may linger)
    if os.path.exists(path):
        os.remove(path)
    con = duckdb.connect(path)
    con.execute(f"SET temp_directory = '{workdir}/duck_tmp'")
    # GitHub kills a runner that nears its 16 GB, and DuckDB's limit does not count everything
    # (Parquet readers, list states), so stay well under it and spill instead
    con.execute(f"SET memory_limit = '{os.environ.get('RC_DUCK_MEMORY', '7GB')}'")
    con.execute(f"SET threads = {int(os.environ.get('RC_DUCK_THREADS', '2'))}")
    con.execute("SET preserve_insertion_order = false")
    return con


NS_SQL = "unhex(md5(array_to_string(list_transform(network_ids, lambda x: hex(x)), '')))"
FACT_COLS = "fact_id, code_id, ps_id, pl_id, billing_code_type, billing_code"
ANY_COLS = ", ".join(f"any_value({c}) {c}" for c in FACT_COLS.split(", ")[1:])


def _nets_table(con, nets: list[dict]) -> dict:
    """Register `nets` (net, network_id, h1, h2): one small integer and two 64-bit halves per network.

    A network set is grouped by (bit_xor(h1), bit_xor(h2), count) over its distinct members: fixed-size,
    order-free aggregate states that spill cheaply. ns_id itself stays md5 over the sorted network IDs.
    Returns file_key -> net.
    """
    import pyarrow as pa

    ids = sorted({n["network_id"] for n in nets})
    idx = {nid: i for i, nid in enumerate(ids)}
    con.register("nets", pa.table({
        "net": pa.array(range(len(ids)), pa.int32()),
        "network_id": pa.array(ids, pa.binary(16)),
        "h1": pa.array([int.from_bytes(i[:8], "big") for i in ids], pa.uint64()),
        "h2": pa.array([int.from_bytes(i[8:], "big") for i in ids], pa.uint64()),
    }))
    return {n["file_key"]: idx[n["network_id"]] for n in nets}


def _ns_map(con, keyed: str, members: str, name: str) -> int:
    """Turn set keys into ns_ids. `keyed` has (x1, x2, n_net, rep); `members` has (rep, net) for those reps.

    Creates table `name` (x1, x2, n_net, ns_id, network_ids) and checks every set has n_net members.
    """
    con.execute(f"""
        CREATE OR REPLACE TABLE {name} AS
        WITH k AS ({keyed}),
             m AS (SELECT mm.rep, list(n.network_id ORDER BY n.network_id) network_ids
                   FROM ({members}) mm JOIN nets n USING (net)
                   WHERE mm.rep IN (SELECT rep FROM k) GROUP BY mm.rep)
        SELECT k.x1, k.x2, k.n_net, {NS_SQL} AS ns_id, m.network_ids
        FROM k JOIN m USING (rep)
    """)
    bad = con.execute(f"SELECT count(*) FROM {name} WHERE len(network_ids) <> n_net").fetchone()[0]
    if bad:
        raise RuntimeError(f"{bad} network sets disagree with their keys")
    return con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]


def reduce_part_local(local: str, payer: str, release: str, part: int, out: str, keys: bool = False,
                      delete_inputs: bool = False) -> dict:
    """Distinct facts of one partition, each with the set of networks (derived from files) it appears in.

    Memory stays flat: no list aggregates over the big input, only fixed-size group states.
    """
    import pyarrow.parquet as pq

    t0 = time.time()
    nets = networks(local, payer)
    files = sorted(str(p) for p in Path(local).glob(f"*/rate_fact/part-{part:02d}.parquet"))
    os.makedirs(f"{out}/rate_fact", exist_ok=True)
    os.makedirs(f"{out}/network_set", exist_ok=True)
    res = {"part": part, "files": len(files), "networks": len({n["network_id"] for n in nets}), "seconds": 0.0}
    if not files:
        return res
    res["rows_in"] = sum(pq.ParquetFile(f).metadata.num_rows for f in files)
    _log(f"part {part}: {len(files)} fact files, {res['rows_in']:,} rows, "
         f"{sum(os.path.getsize(f) for f in files) / 1e9:.1f} GB")
    raw_con = _duck(local)
    _ex = raw_con.execute

    class _Logged:  # log every statement's duration
        def __getattr__(self, n):
            return getattr(raw_con, n)

        def execute(self, sql, *a):
            t = time.time()
            r = _ex(sql, *a)
            _log(f"{' '.join(sql.split())[:90]} ... {time.time() - t:.0f}s")
            return r
    con = _Logged()
    net_of = _nets_table(con, nets)
    key = lambda p: Path(p).parts[-3]  # <file key>/rate_fact/part-XX.parquet
    tmp = f"{local}/facts_tmp.parquet"
    fbs = sorted(str(p) for p in Path(local).glob("*/file_block.parquet"))
    if fbs:
        # block membership: a fact's networks are the union over the blocks (billing-code records) it
        # appears in; the map wrote each block's facts once per shard and every file's block list
        res["mode"] = "blocks"
        os.makedirs(f"{out}/block", exist_ok=True)
        import pyarrow as pa
        import pyarrow.parquet as pq

        con.register("netmap", pa.table({"file_key": list(net_of), "net": pa.array(list(net_of.values()), pa.int32())}))
        chunked = [f for f in fbs if "file_key" in pq.read_schema(f).names]
        per_file = [f for f in fbs if f not in chunked]
        selects = [f"SELECT block_id, code_id, n_rates, {net_of[Path(f).parent.name]} AS net FROM read_parquet('{f}') "
                   f"WHERE part = {part}" for f in per_file]
        if chunked:
            selects.append(f"SELECT fb.block_id, fb.code_id, fb.n_rates, m.net FROM read_parquet({chunked!r}) fb "
                           f"JOIN netmap m USING (file_key) WHERE fb.part = {part}")
        con.execute(f"CREATE TABLE fbr AS {' UNION ALL '.join(selects)}")
        missing = con.execute(f"""SELECT count(*) FROM read_parquet({chunked!r}) WHERE file_key NOT IN
                                  (SELECT file_key FROM netmap)""").fetchone()[0] if chunked else 0
        if missing:
            raise RuntimeError(f"{missing} file_block rows name a file without meta")
        con.execute("CREATE TABLE bnet AS SELECT DISTINCT block_id, net FROM fbr")
        con.execute("""CREATE TABLE bn AS
                       SELECT b.block_id, bit_xor(n.h1) x1, bit_xor(n.h2) x2, count(*)::INTEGER n_net
                       FROM bnet b JOIN nets n USING (net) GROUP BY b.block_id""")
        # facts are grouped in slices by hash(fact_id): BLOB/VARCHAR aggregate states do not spill,
        # so each slice must fit in memory (about 15 million input rows per slice)
        k = max(1, res["rows_in"] // int(os.environ.get("RC_SLICE_ROWS", "15000000")) + 1)
        res["slices"] = k
        os.makedirs(f"{local}/facts_tmp", exist_ok=True)
        multi_n = 0
        split = f"{local}/fact_split-{part:02d}"
        if k > 1:  # one streaming pass splits the input by slice, so each slice reads only its rows
            con.execute(f"""COPY (SELECT *, (hash(fact_id) % {k})::INTEGER AS _slice FROM read_parquet({files!r}))
                            TO '{split}' (FORMAT parquet, PARTITION_BY (_slice), OVERWRITE_OR_IGNORE true)""")
            if delete_inputs:  # the split copy replaces the downloaded input on disk
                for f in files:
                    os.remove(f)
        for i in range(k):
            src_i = (f"(SELECT * EXCLUDE (_slice) FROM read_parquet('{split}/_slice={i}/*.parquet'))"
                     if k > 1 else f"read_parquet({files!r})")
            if k > 1 and not os.path.isdir(f"{split}/_slice={i}"):
                continue
            con.execute(f"""
                COPY (SELECT fact_id, {ANY_COLS}, min(block_id) b_min, max(block_id) b_max
                      FROM {src_i} GROUP BY fact_id)
                TO '{local}/fx.parquet' (FORMAT parquet, COMPRESSION zstd)""")
            fx = f"read_parquet('{local}/fx.parquet')"
            con.execute(f"""CREATE OR REPLACE TABLE multi AS
                            SELECT DISTINCT r.fact_id, b.net
                            FROM (SELECT fact_id, block_id FROM {src_i}) r
                            JOIN bnet b USING (block_id)
                            WHERE r.fact_id IN (SELECT fact_id FROM {fx} WHERE b_min <> b_max)""")
            con.execute(f"""
                COPY (
                  SELECT f.{FACT_COLS.replace(', ', ', f.')}, bn.x1, bn.x2, bn.n_net
                  FROM {fx} f JOIN bn ON bn.block_id = f.b_min WHERE f.b_min = f.b_max
                  UNION ALL
                  SELECT f.{FACT_COLS.replace(', ', ', f.')}, u.x1, u.x2, u.n_net
                  FROM {fx} f JOIN (SELECT m.fact_id, bit_xor(n.h1) x1, bit_xor(n.h2) x2, count(*)::INTEGER n_net
                                    FROM multi m JOIN nets n USING (net) GROUP BY m.fact_id) u USING (fact_id)
                ) TO '{local}/facts_tmp/slice-{i:04d}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
            multi_n += con.execute("SELECT count(DISTINCT fact_id) FROM multi").fetchone()[0]
        tmp = f"{local}/facts_tmp/*.parquet"
        res["multi_block_facts"] = multi_n
        res["block_sets"] = _ns_map(con, "SELECT x1, x2, n_net, any_value(block_id) rep FROM bn GROUP BY ALL",
                                    "SELECT block_id rep, net FROM bnet", "bns")
        con.execute(f"""
            COPY (SELECT a.block_id, a.code_id, a.n_rates, a.n_files, s.ns_id
                  FROM (SELECT block_id, any_value(code_id) code_id, any_value(n_rates) n_rates,
                               count(*)::INTEGER n_files FROM fbr GROUP BY block_id) a
                  JOIN bn USING (block_id) JOIN bns s USING (x1, x2, n_net))
            TO '{out}/block/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
        res["blocks"] = con.execute("SELECT count(*) FROM bn").fetchone()[0]
        all_src = f"read_parquet('{split}/*/*.parquet')" if k > 1 else f"read_parquet({files!r})"
        members = f"""SELECT DISTINCT r.fact_id rep, b.net FROM {all_src} r
                      JOIN bnet b USING (block_id) WHERE r.fact_id IN (SELECT fact_id FROM reps)"""
    else:
        # older map output without blocks: membership is the file each fact came from. Read one file
        # per network (identical files are one network) so each (fact, network) pair counts once.
        res["mode"] = "files"
        rep_files: dict[int, str] = {}
        for f in files:
            rep_files.setdefault(net_of[key(f)], f)
        per_net = " UNION ALL ".join(
            f"SELECT DISTINCT {FACT_COLS}, {i} AS net FROM read_parquet('{f}')" for i, f in rep_files.items())
        con.execute(f"""
            COPY (SELECT fact_id, {ANY_COLS}, bit_xor(n.h1) x1, bit_xor(n.h2) x2, count(*)::INTEGER n_net
                  FROM ({per_net}) r JOIN nets n USING (net) GROUP BY fact_id)
            TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)""")
        members = " UNION ALL ".join(
            f"SELECT DISTINCT fact_id rep, {i} AS net FROM read_parquet('{f}') "
            "WHERE fact_id IN (SELECT fact_id FROM reps)" for i, f in rep_files.items())
    t = f"read_parquet('{tmp}')"
    con.execute(f"CREATE TABLE reps AS SELECT x1, x2, n_net, any_value(fact_id) fact_id FROM {t} GROUP BY ALL")
    res["network_sets"] = _ns_map(con, "SELECT x1, x2, n_net, fact_id rep FROM reps", members, "fns")
    con.execute(f"""
        COPY (SELECT f.{FACT_COLS.replace(', ', ', f.')}, s.ns_id, '{release}' AS valid_from
                     {", f.x1, f.x2, f.n_net" if keys else ""}
              FROM {t} f JOIN fns s USING (x1, x2, n_net)
              ORDER BY f.billing_code_type, f.billing_code, f.ps_id)
        TO '{out}/rate_fact/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)""")
    kc = ", x1, x2, n_net" if keys else ""  # wave outputs keep set keys for the cross-wave merge
    extra = f"UNION SELECT ns_id, network_ids{kc} FROM bns" if fbs else ""
    con.execute(f"""COPY (SELECT ns_id, network_ids{kc} FROM fns {extra})
                    TO '{out}/network_set/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    res["facts"] = con.execute(f"SELECT count(*) FROM read_parquet('{out}/rate_fact/part-{part:02d}.parquet')").fetchone()[0]
    if res["facts"] != con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]:
        raise RuntimeError("facts lost joining to their network sets")
    if "*" in tmp:
        import shutil

        shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
        shutil.rmtree(f"{local}/fact_split-{part:02d}", ignore_errors=True)
    else:
        os.remove(tmp)
    res["seconds"] = round(time.time() - t0, 1)
    return res


def merge_part_local(local: str, release: str, part: int, out: str) -> dict:
    """Merge the wave outputs of one fact part (local/<wave>/rate_fact|network_set/part-XX).

    Waves hold disjoint sets of files, hence disjoint networks, so a fact's full set key is the
    XOR of its per-wave keys and the member count is their sum; members of each final set are
    the union of the wave sets of one representative fact."""
    t0 = time.time()
    facts = sorted(str(p) for p in Path(local).glob(f"*/rate_fact/part-{part:02d}.parquet"))
    sets = sorted(str(p) for p in Path(local).glob(f"*/network_set/part-{part:02d}.parquet"))
    os.makedirs(f"{out}/rate_fact", exist_ok=True)
    os.makedirs(f"{out}/network_set", exist_ok=True)
    res = {"part": part, "waves": len(facts), "seconds": 0.0}
    if not facts:
        return res
    con = _duck(local)
    tmp = f"{local}/merged_tmp.parquet"
    res["rows_in"] = con.execute(f"SELECT count(*) FROM read_parquet({facts!r})").fetchone()[0]
    con.execute(f"""COPY (SELECT fact_id, {ANY_COLS}, bit_xor(x1) x1, bit_xor(x2) x2, sum(n_net)::INTEGER n_net
                          FROM read_parquet({facts!r}) GROUP BY fact_id) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)""")
    t = f"read_parquet('{tmp}')"
    con.execute(f"CREATE TABLE wsets AS SELECT DISTINCT x1, x2, n_net, network_ids FROM read_parquet({sets!r})")
    con.execute(f"CREATE TABLE reps AS SELECT x1, x2, n_net, any_value(fact_id) fact_id FROM {t} GROUP BY ALL")
    con.execute(f"""
        CREATE TABLE fns AS
        WITH m AS (SELECT r.x1, r.x2, r.n_net, list_sort(list_distinct(flatten(list(w.network_ids)))) network_ids
                   FROM reps r JOIN read_parquet({facts!r}) f ON f.fact_id = r.fact_id
                   JOIN wsets w ON w.x1 = f.x1 AND w.x2 = f.x2 AND w.n_net = f.n_net
                   GROUP BY r.x1, r.x2, r.n_net)
        SELECT x1, x2, n_net, {NS_SQL} AS ns_id, network_ids FROM m""")
    bad = con.execute("SELECT count(*) FROM fns WHERE len(network_ids) <> n_net").fetchone()[0]
    if bad or con.execute("SELECT count(*) FROM fns").fetchone()[0] != con.execute("SELECT count(*) FROM reps").fetchone()[0]:
        raise RuntimeError(f"{bad} merged network sets disagree with their keys")
    con.execute(f"""
        COPY (SELECT f.{FACT_COLS.replace(', ', ', f.')}, s.ns_id, '{release}' AS valid_from
              FROM {t} f JOIN fns s USING (x1, x2, n_net)
              ORDER BY f.billing_code_type, f.billing_code, f.ps_id)
        TO '{out}/rate_fact/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)""")
    con.execute(f"""COPY (SELECT ns_id, network_ids FROM fns UNION
                          SELECT DISTINCT ns_id, network_ids FROM read_parquet({sets!r}))
                    TO '{out}/network_set/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    res["facts"] = con.execute(f"SELECT count(*) FROM read_parquet('{out}/rate_fact/part-{part:02d}.parquet')").fetchone()[0]
    res["network_sets"] = con.execute("SELECT count(*) FROM fns").fetchone()[0]
    os.remove(tmp)
    res["seconds"] = round(time.time() - t0, 1)
    return res


DIM_SLICES = {"price_list": 8, "price_term": 4, "provider_set": 4, "provider_list": 4}


def restricted_dir(out: str) -> str:
    """Private outputs of a reduce live beside, never inside, the folder that gets published."""
    return out.rstrip("/") + ".restricted"


def reduce_dims(payer: str, release: str, bucket: str, out: str, token=None, workdir: str = "/tmp/reduce",
                table: str = "all", shards: tuple[int, int] | None = None) -> dict:
    """Distinct dimension rows across all files (one table, or 'meta' for source_file/network)."""
    t0 = time.time()
    prefix = f"map/{release}/{payer}/"
    allp = [p for p in _list(bucket, prefix, token) if in_shards(p, shards)]
    is_meta = lambda p: p.endswith("/meta.json") or p.endswith("/metas.json")  # noqa: E731
    if table == "meta":
        want = [p for p in allp if is_meta(p)]
    elif table == "all":
        want = [p for p in allp if "/rate_fact" not in p]
    else:
        want = [p for p in allp if p.endswith(f"/{table}.parquet") or is_meta(p)]
    local = os.path.join(workdir, f"dims-{table}")
    presplit = None
    if table in DIM_SLICES:  # big list tables: download and split in batches so disk holds ~one copy
        presplit = _fetch_split(bucket, [p for p in want if not is_meta(p)], local, prefix, token, table)
        want = [p for p in want if is_meta(p)]
    _fetch(bucket, want, local, prefix, token)
    res = reduce_dims_local(local, payer, out, table, delete_inputs=True, presplit=presplit)
    res["download_seconds"] = round(time.time() - t0, 1) - res["seconds"]
    return res


def _fetch_split(bucket: str, paths: list[str], local: str, prefix: str, token, name: str) -> int:
    """Download one table's inputs a batch at a time, append each batch to a hash-sliced copy, delete the batch.
    Returns the slice count. Peak disk is the sliced copy plus one batch (the whole input at once ran a
    runner with 105 GB free out of space on Aetna wave 6)."""
    from huggingface_hub import list_bucket_tree

    size = {i.path: getattr(i, "size", 0) or 0 for i in list_bucket_tree(bucket, prefix=prefix, recursive=True, token=token)
            if getattr(i, "type", "file") == "file"}
    total = sum(size.get(p, 0) for p in paths)
    k = max(DIM_SLICES.get(name, 1), total // int(os.environ.get("RC_DIM_SLICE_BYTES", 300 << 20)) + 1)
    cap = int(os.environ.get("RC_SPLIT_BATCH_BYTES", 12 << 30))
    batches, cur, cb = [], [], 0
    for p in paths:
        cur.append(p)
        cb += size.get(p, 0)
        if cb >= cap:
            batches.append(cur)
            cur, cb = [], 0
    if cur:
        batches.append(cur)
    split = f"{local}/split-{name}"
    for n, b in enumerate(batches):
        if token:  # tokens from GitHub's OIDC exchange last an hour; this loop can run longer
            from .hfio import bucket as bk, oidc_available, token_for

            if oidc_available():
                token = token_for(bk(bucket))
        files = _fetch(bucket, b, f"{local}/batch", prefix, token)
        split_stream(files, split, DIMS[name], k, tag=f"b{n}")
        import shutil

        shutil.rmtree(f"{local}/batch", ignore_errors=True)
        print(f"split batch {n + 1}/{len(batches)}: {len(b)} files", flush=True)
    return k


STREAM_ROWS = int(os.environ.get("RC_STREAM_ROWS", 500))
_HASH_CON = None  # a BCBS provider_set row can hold ~4,000 list ids


def _slice_of(keys, k: int):
    """Slice number per key: DuckDB's hash(key) % k, computed on one small column at a time."""
    import duckdb
    import pyarrow as pa

    global _HASH_CON
    if _HASH_CON is None:
        _HASH_CON = duckdb.connect()
        _HASH_CON.execute("SET threads = 1")
    _HASH_CON.register("t", pa.table({"key": keys}))
    r = _HASH_CON.execute(f"SELECT (hash(key) % {k})::INTEGER AS s FROM t").arrow()
    s = (r.read_all() if hasattr(r, "read_all") else r).column("s")  # reader or table, by DuckDB version
    _HASH_CON.unregister("t")
    return s


def split_stream(files: list[str], split: str, key: str, k: int, tag: str = "b0") -> None:
    """Hash-slice Parquet files by `key` into {split}/_slice=<i>/<tag>_f<j>.parquet, a few hundred rows at a time
    (pyarrow). A DuckDB COPY of BCBS provider sets and lists (rows of thousands of ids) ran out of 6.5 GB."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    for j, f in enumerate(files):  # pyarrow only: numpy is not installed on the runners
        pf = pq.ParquetFile(f, buffer_size=1 << 20, pre_buffer=False)
        writers: dict = {}
        for b in pf.iter_batches(batch_size=STREAM_ROWS, use_threads=False):
            if "_slice" in b.schema.names:
                b = b.drop_columns(["_slice"])
            sl = _slice_of(b.column(key), k)
            for i in pc.unique(sl).to_pylist():
                piece = pa.Table.from_batches([b]).filter(pc.equal(sl, i))
                if int(i) not in writers:
                    os.makedirs(f"{split}/_slice={int(i)}", exist_ok=True)
                    writers[int(i)] = pq.ParquetWriter(f"{split}/_slice={int(i)}/{tag}_f{j}.parquet", piece.schema,
                                                       compression="zstd", use_dictionary=False, write_statistics=False)
                writers[int(i)].write_table(piece, row_group_size=STREAM_ROWS)
            del b
            pa.default_memory_pool().release_unused()
        for w in writers.values():
            w.close()


def _plain_binary(t):
    """fixed_size_binary (the Rust core's IDs) -> binary (parse.py's and DuckDB's), also inside lists."""
    import pyarrow as pa

    if pa.types.is_fixed_size_binary(t):
        return pa.binary()
    if pa.types.is_list(t) or pa.types.is_large_list(t):
        return pa.list_(_plain_binary(t.value_type))
    return t


def dedup_stream(files: list[str], dest: str, key: str) -> int:
    """First row per key across files (same as DISTINCT ON (key) for content-hash IDs, whose rows are identical),
    streamed: memory is the slice's set of keys plus one batch. Schemas are unified by name, IDs as binary
    (files from the Rust core hold fixed_size_binary[16], files from parse.py binary)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.unify_schemas([pa.schema([f.with_type(_plain_binary(f.type)) for f in pq.ParquetFile(x).schema_arrow])
                               for x in files])
    seen: set = set()
    n = 0
    with pq.ParquetWriter(dest, schema, compression="zstd", use_dictionary=False) as w:
        for f in files:
            pf = pq.ParquetFile(f, buffer_size=1 << 20, pre_buffer=False)
            for b in pf.iter_batches(batch_size=STREAM_ROWS, use_threads=False):
                keep = []
                for x in b.column(key).to_pylist():
                    keep.append(x not in seen)
                    seen.add(x)
                t = pa.Table.from_batches([b]).filter(pa.array(keep))
                if t.num_rows:
                    for name in schema.names:
                        if name not in t.column_names:
                            t = t.append_column(name, pa.nulls(t.num_rows, schema.field(name).type))
                    w.write_table(t.select(schema.names).cast(schema), row_group_size=50000)
                    n += t.num_rows
                del t, b
                pa.default_memory_pool().release_unused()
    return n


def reduce_dims_local(local: str, payer: str, out: str, table: str = "all", delete_inputs: bool = False,
                      presplit: int | None = None) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    res: dict = {"tables": {}}
    nets = networks(local, payer)
    res["files"] = len(nets)
    if table in ("all", "meta"):
        pq.write_table(pa.Table.from_pylist(nets), f"{out}/source_file.parquet", compression="zstd")
        uniq: dict = {}
        for n in nets:
            uniq.setdefault(n["network_id"], []).append(n["name"])
        pq.write_table(pa.Table.from_pylist([{"network_id": k, "example_file": v[0], "files": len(v)}
                                             for k, v in uniq.items()]), f"{out}/network.parquet",
                       compression="zstd")
        res["networks"] = len(uniq)
    tables = DIMS if table == "all" else ({table: DIMS[table]} if table in DIMS else {})
    if not tables:
        res["seconds"] = round(time.time() - t0, 1)
        return res
    con = _duck(local)
    for name, key in tables.items():
        files = sorted(str(p) for p in Path(local).glob(f"*/{name}.parquet")) + \
            sorted(str(p) for p in Path(local).glob(f"*/{name}/*.parquet"))  # wave outputs are sliced
        if presplit:
            files = sorted(str(p) for p in Path(f"{local}/split-{name}").glob("*/*.parquet"))
        if not files:
            continue
        if presplit and name in DIM_SLICES:  # sliced by split_stream: dedup each slice with pyarrow, never DuckDB
            import shutil

            import pyarrow.parquet as pq

            split = f"{local}/split-{name}"
            os.makedirs(f"{out}/{name}", exist_ok=True)
            width = 2 if presplit < 100 else 3
            n_in = sum(pq.ParquetFile(f).metadata.num_rows for f in files)
            n_out = 0
            for i in range(presplit):
                fs = sorted(str(p) for p in Path(f"{split}/_slice={i}").glob("*.parquet"))
                if fs:
                    n_out += dedup_stream(fs, f"{out}/{name}/part-{i:0{width}d}.parquet", key)
                    shutil.rmtree(f"{split}/_slice={i}", ignore_errors=True)
            shutil.rmtree(split, ignore_errors=True)
            res["tables"][name] = {"rows_in": n_in, "rows_out": n_out}
            continue
        src = f"read_parquet({files!r}, union_by_name = true)"
        if presplit:
            src = f"(SELECT * EXCLUDE (_slice) FROM {src})"
        cols = {d[0] for d in con.execute(f"SELECT * FROM {src} LIMIT 0").description}
        n_in = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        tin = ("list_distinct(flatten(list(coalesce(tin_raws, [tin_raw]))))" if "tin_raws" in cols and "tin_raw" in cols
               else "list_distinct(flatten(list(tin_raws)))" if "tin_raws" in cols else "list(DISTINCT tin_raw)")

        def dedup(source: str) -> str:
            if name == "provider_group":
                return f"""SELECT pg_id, any_value(tin_type) tin_type, any_value(tin_value) tin_value, {tin} tin_raws,
                                  any_value(npis) npis, any_value(npi_count) npi_count, any_value(tin_wide) tin_wide,
                                  list_distinct(flatten(list(business_names))) business_names
                           FROM {source} GROUP BY pg_id"""
            return f"SELECT DISTINCT ON ({key}) * FROM {source}"

        # list columns and list aggregates do not spill well: about 300 MB of compressed input per slice
        k = presplit or max(DIM_SLICES.get(name, 1),
                            sum(os.path.getsize(f) for f in files) // int(os.environ.get("RC_DIM_SLICE_BYTES", 300 << 20)) + 1)
        single = name not in DIM_SLICES  # published as one file
        if k == 1:
            dest = f"{out}/{name}.parquet" if single else f"{out}/{name}/part-00.parquet"
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            con.execute(f"COPY ({dedup(src)}) TO '{dest}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)")
            n_out = con.execute(f"SELECT count(*) FROM read_parquet('{dest}')").fetchone()[0]
        else:
            import shutil

            # one streaming pass splits the input by slice; then each slice is deduplicated alone
            split = f"{local}/split-{name}"
            if not presplit:
                con.execute(f"""COPY (SELECT *, (hash({key}) % {k})::INTEGER AS _slice FROM {src})
                                TO '{split}' (FORMAT parquet, PARTITION_BY (_slice), OVERWRITE_OR_IGNORE true)""")
            if delete_inputs and not presplit:  # the split copy replaces the downloaded input on disk
                for f in files:
                    os.remove(f)
            parts_dir = f"{local}/parts-{name}" if single else f"{out}/{name}"
            os.makedirs(parts_dir, exist_ok=True)
            width = 2 if k < 100 else 3
            n_out = 0
            for i in range(k):
                if not os.path.isdir(f"{split}/_slice={i}"):
                    continue
                dest = f"{parts_dir}/part-{i:0{width}d}.parquet"
                piece = f"(SELECT * EXCLUDE (_slice) FROM read_parquet('{split}/_slice={i}/*.parquet', union_by_name = true))"
                con.execute(f"COPY ({dedup(piece)}) TO '{dest}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)")
                n_out += con.execute(f"SELECT count(*) FROM read_parquet('{dest}')").fetchone()[0]
            shutil.rmtree(split, ignore_errors=True)
            if single:  # streamed with pyarrow: a DuckDB COPY of BCBS wave 3's provider groups ran out of 6.5 GB
                from .consolidate import concat_parquet

                concat_parquet(sorted(str(p) for p in Path(parts_dir).glob("*.parquet")), f"{out}/{name}.parquet",
                               batch_rows=20000)
                shutil.rmtree(parts_dir, ignore_errors=True)
        res["tables"][name] = {"rows_in": n_in, "rows_out": n_out}
        if name == "code":  # never publish licensed descriptor text (licensing.py); keep it privately
            from .licensing import redact_code_file

            os.makedirs(restricted_dir(out), exist_ok=True)
            res["tables"][name]["text"] = redact_code_file(f"{out}/code.parquet",
                                                           f"{restricted_dir(out)}/code_text.parquet")
    res["seconds"] = round(time.time() - t0, 1)
    return res
