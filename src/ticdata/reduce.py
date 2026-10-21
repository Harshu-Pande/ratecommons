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
        download_bucket_files(bucket, files=files[i:i + 200], token=token)
    return [local for _, local in files]


def networks(local_root: str, payer: str) -> list[dict]:
    """One row per file: its derived network ID is the content identity of the file."""
    import xxhash

    rows = []
    for meta_path in sorted(Path(local_root).glob("*/meta.json")):
        m = json.loads(meta_path.read_text())
        src = m.get("source") or {}
        content = f"{payer}|{m.get('local_bytes')}|{m.get('tail_crc32')}|{m.get('tail_isize')}"
        rows.append({
            "file_key": meta_path.parent.name, "name": src.get("name"), "url": src.get("url"),
            "bytes": m.get("local_bytes"), "tail_crc32": m.get("tail_crc32"), "tail_isize": m.get("tail_isize"),
            "network_id": xxhash.xxh3_128_digest(b"net" + content.encode()),
            "header": json.dumps(m.get("header"), sort_keys=True), "counts": json.dumps(m.get("counts")),
            "flags": json.dumps(m.get("flags")), "layout": json.dumps(m.get("layout")),
        })
    return rows


def reduce_part(payer: str, release: str, part: int, bucket: str, out: str, token=None,
                workdir: str = "/tmp/reduce") -> dict:
    """Merge rate_fact part `part` across every file of the release."""
    t0 = time.time()
    prefix = f"map/{release}/{payer}/"
    allp = _list(bucket, prefix, token)
    want = [p for p in allp if p.endswith("/meta.json") or p.endswith("/file_block.parquet")
            or p.endswith(f"/rate_fact/part-{part:02d}.parquet")]
    local = os.path.join(workdir, f"p{part:02d}")
    _fetch(bucket, want, local, prefix, token)
    res = reduce_part_local(local, payer, release, part, out)
    res["download_seconds"] = round(time.time() - t0, 1) - res["seconds"]
    return res


def _duck(workdir: str):
    """A DuckDB on disk with spilling, sized for a 16 GB / 4 vCPU runner."""
    import duckdb

    os.makedirs(f"{workdir}/duck_tmp", exist_ok=True)
    path = f"{workdir}/duck.db"
    if os.path.exists(path):
        os.remove(path)
    con = duckdb.connect(path)
    con.execute(f"SET temp_directory = '{workdir}/duck_tmp'")
    con.execute(f"SET memory_limit = '{os.environ.get('RC_DUCK_MEMORY', '11GB')}'")
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


def reduce_part_local(local: str, payer: str, release: str, part: int, out: str) -> dict:
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
    con = _duck(local)
    net_of = _nets_table(con, nets)
    key = lambda p: Path(p).parts[-3]  # <file key>/rate_fact/part-XX.parquet
    tmp = f"{local}/facts_tmp.parquet"
    fbs = sorted(str(p) for p in Path(local).glob("*/file_block.parquet"))
    if fbs:
        # block membership: a fact's networks are the union over the blocks (billing-code records) it
        # appears in; the map wrote each block's facts once per shard and every file's block list
        res["mode"] = "blocks"
        os.makedirs(f"{out}/block", exist_ok=True)
        fb_union = " UNION ALL ".join(
            f"SELECT block_id, code_id, n_rates, {net_of[Path(f).parent.name]} AS net FROM read_parquet('{f}') "
            f"WHERE part = {part}" for f in fbs)
        con.execute(f"CREATE TABLE fbr AS {fb_union}")
        con.execute("CREATE TABLE bnet AS SELECT DISTINCT block_id, net FROM fbr")
        con.execute("""CREATE TABLE bn AS
                       SELECT b.block_id, bit_xor(n.h1) x1, bit_xor(n.h2) x2, count(*)::INTEGER n_net
                       FROM bnet b JOIN nets n USING (net) GROUP BY b.block_id""")
        con.execute(f"""
            COPY (SELECT fact_id, {ANY_COLS}, min(block_id) b_min, max(block_id) b_max
                  FROM read_parquet({files!r}) GROUP BY fact_id)
            TO '{local}/fx.parquet' (FORMAT parquet, COMPRESSION zstd)""")
        fx = f"read_parquet('{local}/fx.parquet')"
        con.execute(f"""CREATE TABLE multi AS
                        SELECT DISTINCT r.fact_id, b.net
                        FROM read_parquet({files!r}) r JOIN bnet b USING (block_id)
                        WHERE r.fact_id IN (SELECT fact_id FROM {fx} WHERE b_min <> b_max)""")
        con.execute(f"""
            COPY (
              SELECT f.{FACT_COLS.replace(', ', ', f.')}, bn.x1, bn.x2, bn.n_net
              FROM {fx} f JOIN bn ON bn.block_id = f.b_min WHERE f.b_min = f.b_max
              UNION ALL
              SELECT f.{FACT_COLS.replace(', ', ', f.')}, u.x1, u.x2, u.n_net
              FROM {fx} f JOIN (SELECT m.fact_id, bit_xor(n.h1) x1, bit_xor(n.h2) x2, count(*)::INTEGER n_net
                                FROM multi m JOIN nets n USING (net) GROUP BY m.fact_id) u USING (fact_id)
            ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)""")
        res["multi_block_facts"] = con.execute("SELECT count(DISTINCT fact_id) FROM multi").fetchone()[0]
        res["block_sets"] = _ns_map(con, "SELECT x1, x2, n_net, any_value(block_id) rep FROM bn GROUP BY ALL",
                                    "SELECT block_id rep, net FROM bnet", "bns")
        con.execute(f"""
            COPY (SELECT a.block_id, a.code_id, a.n_rates, a.n_files, s.ns_id
                  FROM (SELECT block_id, any_value(code_id) code_id, any_value(n_rates) n_rates,
                               count(*)::INTEGER n_files FROM fbr GROUP BY block_id) a
                  JOIN bn USING (block_id) JOIN bns s USING (x1, x2, n_net))
            TO '{out}/block/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
        res["blocks"] = con.execute("SELECT count(*) FROM bn").fetchone()[0]
        members = f"""SELECT DISTINCT r.fact_id rep, b.net FROM read_parquet({files!r}) r
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
              FROM {t} f JOIN fns s USING (x1, x2, n_net)
              ORDER BY f.billing_code_type, f.billing_code, f.ps_id)
        TO '{out}/rate_fact/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)""")
    extra = "UNION SELECT ns_id, network_ids FROM bns" if fbs else ""
    con.execute(f"""COPY (SELECT ns_id, network_ids FROM fns {extra})
                    TO '{out}/network_set/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    res["facts"] = con.execute(f"SELECT count(*) FROM read_parquet('{out}/rate_fact/part-{part:02d}.parquet')").fetchone()[0]
    if res["facts"] != con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]:
        raise RuntimeError("facts lost joining to their network sets")
    os.remove(tmp)
    res["seconds"] = round(time.time() - t0, 1)
    return res


DIM_SLICES = {"price_list": 8, "price_term": 4, "provider_set": 4}


def restricted_dir(out: str) -> str:
    """Private outputs of a reduce live beside, never inside, the folder that gets published."""
    return out.rstrip("/") + ".restricted"


def reduce_dims(payer: str, release: str, bucket: str, out: str, token=None, workdir: str = "/tmp/reduce",
                table: str = "all") -> dict:
    """Distinct dimension rows across all files (one table, or 'meta' for source_file/network)."""
    t0 = time.time()
    prefix = f"map/{release}/{payer}/"
    allp = _list(bucket, prefix, token)
    if table == "meta":
        want = [p for p in allp if p.endswith("/meta.json")]
    elif table == "all":
        want = [p for p in allp if "/rate_fact" not in p]
    else:
        want = [p for p in allp if p.endswith(f"/{table}.parquet") or p.endswith("/meta.json")]
    local = os.path.join(workdir, f"dims-{table}")
    _fetch(bucket, want, local, prefix, token)
    res = reduce_dims_local(local, payer, out, table)
    res["download_seconds"] = round(time.time() - t0, 1) - res["seconds"]
    return res


def reduce_dims_local(local: str, payer: str, out: str, table: str = "all") -> dict:
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
        files = sorted(str(p) for p in Path(local).glob(f"*/{name}.parquet"))
        if not files:
            continue
        src = f"read_parquet({files!r}, union_by_name = true)"
        n_in = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        if name == "provider_group":
            sel = f"""SELECT pg_id, any_value(tin_type) tin_type, any_value(tin_value) tin_value,
                             list(DISTINCT tin_raw) tin_raws, any_value(npis) npis, any_value(npi_count) npi_count,
                             any_value(tin_wide) tin_wide, list_distinct(flatten(list(business_names))) business_names
                      FROM {src} GROUP BY pg_id"""
            con.execute(f"COPY ({sel}) TO '{out}/{name}.parquet' (FORMAT parquet, COMPRESSION zstd)")
            n_out = con.execute(f"SELECT count(*) FROM read_parquet('{out}/{name}.parquet')").fetchone()[0]
        elif name in DIM_SLICES:
            k = DIM_SLICES[name]
            os.makedirs(f"{out}/{name}", exist_ok=True)
            n_out = 0
            for i in range(k):
                dest = f"{out}/{name}/part-{i:02d}.parquet"
                con.execute(f"""COPY (SELECT DISTINCT ON ({key}) * FROM {src} WHERE hash({key}) % {k} = {i})
                                TO '{dest}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)""")
                n_out += con.execute(f"SELECT count(*) FROM read_parquet('{dest}')").fetchone()[0]
        else:
            con.execute(f"COPY (SELECT DISTINCT ON ({key}) * FROM {src}) TO '{out}/{name}.parquet' "
                        "(FORMAT parquet, COMPRESSION zstd)")
            n_out = con.execute(f"SELECT count(*) FROM read_parquet('{out}/{name}.parquet')").fetchone()[0]
        res["tables"][name] = {"rows_in": n_in, "rows_out": n_out}
        if name == "code":  # never publish licensed descriptor text (licensing.py); keep it privately
            from .licensing import redact_code_file

            os.makedirs(restricted_dir(out), exist_ok=True)
            res["tables"][name]["text"] = redact_code_file(f"{out}/code.parquet",
                                                           f"{restricted_dir(out)}/code_text.parquet")
    res["seconds"] = round(time.time() - t0, 1)
    return res
