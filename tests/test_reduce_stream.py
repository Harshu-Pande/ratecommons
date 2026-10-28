"""Streamed list-dimension reduce: split by key hash, then first row per key (reduce.split_stream / dedup_stream)."""
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ticdata import reduce


def test_split_and_dedup_mix_rust_and_python_id_types(tmp_path):
    ids = [bytes([i]) * 16 for i in range(9)]
    lists = [[bytes([i + 1]) * 16, bytes([i + 2]) * 16] for i in range(9)]
    rust = pa.table({"ps_id": pa.array(ids[:6], pa.binary(16)),
                     "pli_ids": pa.array(lists[:6], pa.list_(pa.binary(16)))})
    py = pa.table({"ps_id": pa.array(ids[3:], pa.binary()),
                   "pli_ids": pa.array(lists[3:], pa.list_(pa.binary()))})
    pq.write_table(rust, tmp_path / "a.parquet")
    pq.write_table(py, tmp_path / "b.parquet")
    split = tmp_path / "split"
    reduce.split_stream([str(tmp_path / "a.parquet"), str(tmp_path / "b.parquet")], str(split), "ps_id", 4)
    got = []
    for d in sorted(split.glob("_slice=*")):
        dest = tmp_path / f"out-{d.name}.parquet"
        reduce.dedup_stream(sorted(str(p) for p in d.glob("*.parquet")), str(dest), "ps_id")
        t = pq.read_table(dest)
        assert t.schema.field("ps_id").type == pa.binary()
        assert t.schema.field("pli_ids").type == pa.list_(pa.binary())
        got += t.to_pylist()
    assert sorted((r["ps_id"], tuple(r["pli_ids"])) for r in got) == sorted(zip(ids, map(tuple, lists)))
