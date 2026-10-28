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


def test_streamed_merge_of_wave_outputs_matches_duckdb(tmp_path):
    """Merging sliced wave outputs through split_stream + dedup_stream gives DuckDB's DISTINCT ON rows."""
    import shutil

    ids = [bytes([i]) * 16 for i in range(12)]
    for w, rng in ((1, range(0, 8)), (2, range(4, 12))):
        d = tmp_path / "waves" / f"wave-{w}" / "provider_set"
        d.mkdir(parents=True)
        t = pa.table({"ps_id": pa.array([ids[i] for i in rng], pa.binary(16)),
                      "pli_ids": pa.array([[ids[i], ids[(i + 1) % 12]] for i in rng], pa.list_(pa.binary(16)))})
        pq.write_table(t, d / "part-00.parquet")
    duck = reduce.reduce_dims_local(str(tmp_path / "waves"), "p", str(tmp_path / "duck"), "provider_set")
    files = sorted(str(p) for p in (tmp_path / "waves").glob("*/provider_set/*.parquet"))
    shutil.copytree(tmp_path / "waves", tmp_path / "waves2")
    files = [f.replace("/waves/", "/waves2/") for f in files]
    reduce.split_stream(files, str(tmp_path / "waves2/split-provider_set"), "ps_id", 4)
    for f in files:
        Path(f).unlink()
    streamed = reduce.reduce_dims_local(str(tmp_path / "waves2"), "p", str(tmp_path / "stream"), "provider_set",
                                        presplit=4)
    assert duck["tables"]["provider_set"]["rows_out"] == streamed["tables"]["provider_set"]["rows_out"] == 12
    rows = lambda d: sorted((r["ps_id"], tuple(r["pli_ids"])) for r in pq.read_table(d).to_pylist())  # noqa: E731
    assert rows(tmp_path / "duck/provider_set") == rows(tmp_path / "stream/provider_set")


def test_sliced_single_table_is_concatenated_whole(tmp_path, monkeypatch):
    """provider_group is deduplicated in slices, then written as one file (streamed concat)."""
    monkeypatch.setenv("RC_DIM_SLICE_BYTES", "1")  # force several slices
    rows = [{"pg_id": bytes([i]) * 16, "tin_type": "ein", "tin_value": f"{i:09d}", "tin_raw": f"{i:09d}",
             "npis": [1000000000 + i], "npi_count": 1, "tin_wide": False, "business_names": [f"n{i}"]} for i in range(30)]
    for j, part in enumerate((rows[:20], rows[10:])):
        d = tmp_path / "map" / f"shard-00{j}-00"
        d.mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(part), d / "provider_group.parquet")
    res = reduce.reduce_dims_local(str(tmp_path / "map"), "p", str(tmp_path / "out"), "provider_group")
    t = pq.read_table(tmp_path / "out/provider_group.parquet")
    assert res["tables"]["provider_group"]["rows_out"] == t.num_rows == 30
    assert sorted(t.column("pg_id").to_pylist()) == sorted(r["pg_id"] for r in rows)


def test_fetch_takes_a_fresh_oidc_token(tmp_path, monkeypatch):
    import huggingface_hub

    from ticdata import hfio

    seen = []
    monkeypatch.setattr(hfio, "oidc_available", lambda: True)
    monkeypatch.setattr(hfio, "token_for", lambda resource: f"fresh:{resource}")
    monkeypatch.setattr(huggingface_hub, "download_bucket_files", lambda b, files, token: seen.append(token))
    reduce._fetch("org/work", ["pre/a.json"], str(tmp_path), "pre/", "stale")
    assert seen == ["fresh:buckets/org/work"]
