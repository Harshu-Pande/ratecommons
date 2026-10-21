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


def reduce_part_local(local: str, payer: str, release: str, part: int, out: str) -> dict:
    import pyarrow as pa

    t0 = time.time()
    nets = networks(local, payer)
    files = sorted(str(p) for p in Path(local).glob(f"*/rate_fact/part-{part:02d}.parquet"))
    os.makedirs(f"{out}/rate_fact", exist_ok=True)
    os.makedirs(f"{out}/network_set", exist_ok=True)
    res = {"part": part, "files": len(files), "networks": len(nets), "seconds": 0.0}
    if not files:
        return res
    con = _duck(local)
    con.register("nets", pa.Table.from_pylist([{"file_key": n["file_key"], "network_id": n["network_id"]}
                                               for n in nets]))
    tmp = f"{local}/facts_tmp.parquet"
    con.execute(f"""
        COPY (
          SELECT r.fact_id, any_value(r.code_id) code_id, any_value(r.ps_id) ps_id, any_value(r.pl_id) pl_id,
                 any_value(r.billing_code_type) billing_code_type, any_value(r.billing_code) billing_code,
                 list(DISTINCT n.network_id ORDER BY n.network_id) network_ids, count(*) n_in
          FROM read_parquet({files!r}, filename = true) r
          JOIN nets n ON n.file_key = split_part(r.filename, '/', -3)
          GROUP BY r.fact_id
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)
    """)
    ns = "unhex(md5(array_to_string(list_transform(network_ids, x -> hex(x)), '')))"
    con.execute(f"""
        COPY (SELECT fact_id, code_id, ps_id, pl_id, billing_code_type, billing_code, {ns} AS ns_id,
                     '{release}' AS valid_from
              FROM read_parquet('{tmp}') ORDER BY billing_code_type, billing_code, ps_id)
        TO '{out}/rate_fact/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)
    """)
    con.execute(f"""
        COPY (SELECT DISTINCT {ns} AS ns_id, network_ids FROM read_parquet('{tmp}'))
        TO '{out}/network_set/part-{part:02d}.parquet' (FORMAT parquet, COMPRESSION zstd)
    """)
    res["rows_in"], res["facts"] = con.execute(f"SELECT sum(n_in), count(*) FROM read_parquet('{tmp}')").fetchone()
    res["network_sets"] = con.execute(
        f"SELECT count(*) FROM read_parquet('{out}/network_set/part-{part:02d}.parquet')").fetchone()[0]
    os.remove(tmp)
    res["seconds"] = round(time.time() - t0, 1)
    return res


DIM_SLICES = {"price_list": 8, "price_term": 4, "provider_set": 4}


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
    res["seconds"] = round(time.time() - t0, 1)
    return res
