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
    want = [p for p in allp if p.endswith("/meta.json") or p.endswith(f"/rate_fact/part-{part:02d}.parquet")]
    local = os.path.join(workdir, f"p{part:02d}")
    _fetch(bucket, want, local, prefix, token)
    res = reduce_part_local(local, payer, release, part, out)
    res["download_seconds"] = round(time.time() - t0, 1) - res["seconds"]
    return res


def reduce_part_local(local: str, payer: str, release: str, part: int, out: str) -> dict:
    import duckdb
    import pyarrow as pa

    t0 = time.time()
    nets = networks(local, payer)
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    con.register("nets", pa.Table.from_pylist([{"file_key": n["file_key"], "network_id": n["network_id"]}
                                               for n in nets]))
    files = sorted(str(p) for p in Path(local).glob(f"*/rate_fact/part-{part:02d}.parquet"))
    os.makedirs(f"{out}/rate_fact", exist_ok=True)
    os.makedirs(f"{out}/network_set", exist_ok=True)
    res = {"part": part, "files": len(files), "networks": len(nets), "seconds": 0.0}
    if not files:
        return res
    con.execute(f"""
        CREATE TABLE f AS
        SELECT r.fact_id, r.code_id, r.ps_id, r.pl_id, r.billing_code_type, r.billing_code, n.network_id
        FROM read_parquet({files!r}, filename = true) r
        JOIN nets n ON n.file_key = split_part(r.filename, '/', -3)
    """)
    res["rows_in"] = con.execute("SELECT count(*) FROM f").fetchone()[0]
    con.execute("""
        CREATE TABLE g AS
        SELECT fact_id, any_value(code_id) code_id, any_value(ps_id) ps_id, any_value(pl_id) pl_id,
               any_value(billing_code_type) billing_code_type, any_value(billing_code) billing_code,
               list(DISTINCT network_id ORDER BY network_id) network_ids
        FROM f GROUP BY fact_id
    """)
    con.execute("""
        CREATE TABLE g2 AS
        SELECT *, unhex(md5(array_to_string(list_transform(network_ids, x -> hex(x)), ''))) ns_id FROM g
    """)
    res["facts"] = con.execute("SELECT count(*) FROM g2").fetchone()[0]
    con.execute(f"""
        COPY (SELECT fact_id, code_id, ps_id, pl_id, billing_code_type, billing_code, ns_id,
                     '{release}' AS valid_from
              FROM g2 ORDER BY billing_code_type, billing_code, ps_id)
        TO '{out}/rate_fact/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)
    """)
    con.execute(f"""
        COPY (SELECT DISTINCT ns_id, network_ids FROM g2)
        TO '{out}/network_set/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd)
    """)
    res["network_sets"] = con.execute("SELECT count(DISTINCT ns_id) FROM g2").fetchone()[0]
    res["seconds"] = round(time.time() - t0, 1)
    return res


def reduce_dims(payer: str, release: str, bucket: str, out: str, token=None, workdir: str = "/tmp/reduce") -> dict:
    """Distinct dimension rows across all files, plus source_file and network tables."""
    t0 = time.time()
    prefix = f"map/{release}/{payer}/"
    allp = _list(bucket, prefix, token)
    want = [p for p in allp if "/rate_fact/" not in p]
    local = os.path.join(workdir, "dims")
    _fetch(bucket, want, local, prefix, token)
    res = reduce_dims_local(local, payer, out)
    res["download_seconds"] = round(time.time() - t0, 1) - res["seconds"]
    return res


def reduce_dims_local(local: str, payer: str, out: str) -> dict:
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    nets = networks(local, payer)
    pq.write_table(pa.Table.from_pylist(nets), f"{out}/source_file.parquet", compression="zstd")
    uniq = {}
    for n in nets:
        uniq.setdefault(n["network_id"], n)
    pq.write_table(pa.Table.from_pylist([{"network_id": k, "example_file": v["name"],
                                          "files": sum(1 for x in nets if x["network_id"] == k)}
                                         for k, v in uniq.items()]), f"{out}/network.parquet", compression="zstd")
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    res = {"files": len(nets), "networks": len(uniq), "tables": {}}
    for table, key in DIMS.items():
        files = sorted(str(p) for p in Path(local).glob(f"*/{table}.parquet"))
        if not files:
            continue
        if table == "provider_group":
            sel = f"""SELECT pg_id, any_value(tin_type) tin_type, any_value(tin_value) tin_value,
                             list(DISTINCT tin_raw) tin_raws, any_value(npis) npis, any_value(npi_count) npi_count,
                             any_value(tin_wide) tin_wide, list_distinct(flatten(list(business_names))) business_names
                      FROM read_parquet({files!r}) GROUP BY pg_id"""
        else:
            sel = f"SELECT * FROM read_parquet({files!r}, union_by_name = true) QUALIFY row_number() OVER (PARTITION BY {key}) = 1"
        con.execute(f"COPY ({sel}) TO '{out}/{table}.parquet' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)")
        n_in = con.execute(f"SELECT count(*) FROM read_parquet({files!r})").fetchone()[0]
        n_out = con.execute(f"SELECT count(*) FROM read_parquet('{out}/{table}.parquet')").fetchone()[0]
        res["tables"][table] = {"rows_in": n_in, "rows_out": n_out}
    res["seconds"] = round(time.time() - t0, 1)
    return res
