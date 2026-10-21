"""Merge the per-file map outputs of a chunk of one shard into one set of tables.

Few, large files: the reduce of a big payer would otherwise fetch tens of thousands of small
objects per job (the design's Hugging Face rate-limit warning). A chunk folder holds:

  metas.json                      list of every file's meta.json (source, size, fingerprint, counts...)
  file_block.parquet              + file_key: which file each block (billing-code record) came from
  provider_reference.parquet      + file_key: provider_group_id is local to its file
  rate_fact/part-XX.parquet       facts, already written once per block per shard
  price_term, price_list, provider_set, code   distinct by ID across the chunk
  provider_group                  distinct rows (reduce merges names per pg_id)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

KEYED = {"price_term": "pt_id", "price_list": "pl_id", "provider_set": "ps_id", "provider_list": "pli_id",
         "code": "code_id"}


def consolidate(items: list[tuple[str, str]], dest: str) -> dict:
    """items: (file_key, per-file output folder). Writes the chunk tables into `dest`."""
    import duckdb

    os.makedirs(f"{dest}/rate_fact", exist_ok=True)
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    con.execute(f"SET temp_directory = '{dest}/.duck_tmp'")
    out: dict = {"files": len(items), "tables": {}}
    metas = [json.loads((Path(d) / "meta.json").read_text()) for _, d in items]
    (Path(dest) / "metas.json").write_text(json.dumps(metas))

    def have(table: str) -> list[tuple[str, str]]:
        return [(k, f"{d}/{table}.parquet") for k, d in items if os.path.exists(f"{d}/{table}.parquet")]

    def copy(sql: str, path: str, name: str):
        con.execute(f"COPY ({sql}) TO '{path}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)")
        out["tables"][name] = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]

    for table in ("file_block", "provider_reference"):
        fs = have(table)
        if fs:
            sql = " UNION ALL ".join(f"SELECT *, '{k}' AS file_key FROM read_parquet('{f}')" for k, f in fs)
            copy(sql, f"{dest}/{table}.parquet", table)
    for table, key in KEYED.items():
        fs = [f for _, f in have(table)]
        if fs:
            copy(f"SELECT DISTINCT ON ({key}) * FROM read_parquet({fs!r}, union_by_name = true)",
                 f"{dest}/{table}.parquet", table)
    fs = [f for _, f in have("provider_group")]
    if fs:
        copy(f"SELECT DISTINCT * FROM read_parquet({fs!r}, union_by_name = true)", f"{dest}/provider_group.parquet",
             "provider_group")
    parts = sorted({p.name for _, d in items for p in Path(d).glob("rate_fact/part-*.parquet")})
    n = 0
    for part in parts:
        fs = [f"{d}/rate_fact/{part}" for _, d in items if os.path.exists(f"{d}/rate_fact/{part}")]
        con.execute(f"COPY (SELECT * FROM read_parquet({fs!r}, union_by_name = true)) TO '{dest}/rate_fact/{part}' "
                    "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)")
        n += con.execute(f"SELECT count(*) FROM read_parquet('{dest}/rate_fact/{part}')").fetchone()[0]
    out["tables"]["rate_fact"] = n
    con.close()
    import shutil

    shutil.rmtree(f"{dest}/.duck_tmp", ignore_errors=True)
    return out
