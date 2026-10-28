"""Merge the per-file map outputs of a chunk of one shard into one set of tables.

Few, large files: the reduce of a big payer would otherwise fetch tens of thousands of small
objects per job (the design's Hugging Face rate-limit warning). A chunk folder holds:

  metas.json                      list of every file's meta.json (source, size, fingerprint, counts...)
  file_block.parquet              + file_key: which file each block (billing-code record) came from
  provider_reference.parquet      + file_key: provider_group_id is local to its file
  rate_fact/part-XX.parquet       facts, already written once per block per shard
  price_term, price_list, provider_set, provider_list, code   concatenated; the shard's files share
                                  seen-sets, so IDs repeat only if a set overflowed (reduce dedups)
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
    con.execute("SET memory_limit = '8GB'")  # the runner also holds the shard's seen-sets on disk/cache
    con.execute("SET threads = 2")  # Anthem chunks: wide provider_group/npi lists ran a 4-thread copy out of 5.5 GB
    con.execute(f"SET temp_directory = '{dest}/.duck_tmp'")
    out: dict = {"files": len(items), "tables": {}}
    metas = [json.loads((Path(d) / "meta.json").read_text()) for _, d in items]
    (Path(dest) / "metas.json").write_text(json.dumps(metas))

    def have(table: str) -> list[tuple[str, str]]:
        return [(k, f"{d}/{table}.parquet") for k, d in items if os.path.exists(f"{d}/{table}.parquet")]

    def copy(sql: str, path: str, name: str):
        con.execute(f"COPY ({sql}) TO '{path}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 250000)")
        out["tables"][name] = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]

    for table in ("file_block", "provider_reference"):
        fs = have(table)
        if fs:  # streamed: Anthem provider references carry huge NPI lists (a DuckDB UNION ran out of 7.4 GB)
            out["tables"][table] = concat_parquet([f for _, f in fs], f"{dest}/{table}.parquet",
                                                  consts=[{"file_key": k} for k, _ in fs])
    for table, key in KEYED.items():
        fs = [f for _, f in have(table)]
        if fs:  # the shard's files share seen-sets for dims, so a plain concatenation
            out["tables"][table] = concat_parquet(fs, f"{dest}/{table}.parquet")
    fs = [f for _, f in have("provider_group")]
    if fs:
        try:
            copy(f"SELECT DISTINCT * FROM read_parquet({fs!r}, union_by_name = true)", f"{dest}/provider_group.parquet",
                 "provider_group")
        except Exception as e:  # out of memory on huge groups: keep duplicates, the reduce dedups them anyway
            if "Out of Memory" not in str(e):
                raise
            out["tables"]["provider_group"] = concat_parquet(fs, f"{dest}/provider_group.parquet")
            out["provider_group_not_deduped"] = True
    parts = sorted({p.name for _, d in items for p in Path(d).glob("rate_fact/part-*.parquet")})
    n = 0
    for part in parts:
        fs = [f"{d}/rate_fact/{part}" for _, d in items if os.path.exists(f"{d}/rate_fact/{part}")]
        con.execute(f"COPY (SELECT * FROM read_parquet({fs!r}, union_by_name = true)) TO '{dest}/rate_fact/{part}' "
                    "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 250000)")
        n += con.execute(f"SELECT count(*) FROM read_parquet('{dest}/rate_fact/{part}')").fetchone()[0]
    out["tables"]["rate_fact"] = n
    con.close()
    import shutil

    shutil.rmtree(f"{dest}/.duck_tmp", ignore_errors=True)
    return out

def concat_parquet(files: list[str], dest: str, batch_rows: int = 2000, consts: list[dict] | None = None) -> int:
    """Concatenate Parquet files batch by batch with pyarrow (bounded memory). Provider sets can be huge lists:
    one BCBS North Carolina BlueCard file has 100k sets averaging 4,232 provider lists (6.8 GB of ids), which a
    DuckDB COPY could not hold in 8 GB. A single input is copied as is. consts: per input file, constant string
    columns to add (file_key), appended after the file's own columns."""
    import shutil

    import pyarrow as pa
    import pyarrow.parquet as pq

    if len(files) == 1 and not consts:
        shutil.copyfile(files[0], dest)
        return pq.ParquetFile(dest).metadata.num_rows
    schema = pa.unify_schemas([pq.ParquetFile(f).schema_arrow for f in files])
    for name in (consts or [{}])[0]:
        if name not in schema.names:
            schema = schema.append(pa.field(name, pa.string()))
    n = 0
    with pq.ParquetWriter(dest, schema, compression="zstd", use_dictionary=False, write_statistics=False) as w:
        for i, f in enumerate(files):
            pf = pq.ParquetFile(f, buffer_size=1 << 20, pre_buffer=False)  # stream column chunks: 1.4 GB, not 5.8
            for b in pf.iter_batches(batch_size=batch_rows, use_threads=False):
                t = pa.Table.from_batches([b])
                for name, v in (consts[i] if consts else {}).items():
                    t = t.append_column(name, pa.array([v] * t.num_rows, pa.string()))
                for name in schema.names:  # union by name: add missing columns as nulls
                    if name not in t.column_names:
                        t = t.append_column(name, pa.nulls(t.num_rows, schema.field(name).type))
                w.write_table(t.select(schema.names).cast(schema), row_group_size=batch_rows)
                n += t.num_rows
                del t, b
                pa.default_memory_pool().release_unused()  # else the allocator keeps every batch's pages
    return n
