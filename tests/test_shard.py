"""A whole shard end to end: download, parse (Rust if built, else Python), chunk, reduce."""
import copy
import functools
import gzip
import http.server
import json
import os
import threading

import pyarrow.parquet as pq
import pytest

from tests.test_parse import DOC, _fact_sets


def _serve(folder):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.parametrize("rust", [False, True])
def test_shard_chunks_reduce_like_per_file_outputs(tmp_path, rust, monkeypatch):
    from ticdata.pipeline import run_shard
    from ticdata.reduce import reduce_dims_local, reduce_part_local

    core = os.path.join(os.path.dirname(__file__), "..", "core/target/release/ticcore")
    if rust and not os.path.exists(core):
        pytest.skip("Rust core not built")
    monkeypatch.setenv("TIC_CORE", os.path.abspath(core) if rust else "")
    web = tmp_path / "web"
    web.mkdir()
    doc_b = copy.deepcopy(DOC)
    doc_b["in_network"][0]["negotiated_rates"][0]["negotiated_prices"][0]["negotiated_rate"] = 80.0
    (web / "2026-10-01_a.json.gz").write_bytes(gzip.compress(json.dumps(DOC).encode()))
    (web / "2026-10-01_b.json.gz").write_bytes(gzip.compress(json.dumps(doc_b).encode()))
    (web / "2026-10-01_c.json.gz").write_bytes(gzip.compress(json.dumps(DOC).encode()))  # same bytes as a
    srv = _serve(web)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    names = ["2026-10-01_a.json.gz", "2026-10-01_b.json.gz", "2026-10-01_c.json.gz"]
    plan = {"payer": "test", "shards": [{"shard": 0, "files": [{"name": n, "url": f"{base}/{n}"} for n in names]}]}
    res = run_shard(plan, 0, workdir=str(tmp_path / "work"), chunk_files=2, chunk_out=str(tmp_path / "map"))
    srv.shutdown()
    assert res["ok"] == 3 and len(res["chunks"]) == 2, res
    assert {r["parser"] for r in res["results"]} == {"rust" if rust else "python"}
    for k in range(16):
        reduce_part_local(str(tmp_path / "map"), "test", "2026-10", k, str(tmp_path / "out"))
    dims = reduce_dims_local(str(tmp_path / "map"), "test", str(tmp_path / "out"))
    assert dims["files"] == 3 and dims["networks"] == 2
    sizes = sorted(len(s) for s in _fact_sets(tmp_path / "out").values())
    assert sizes == [1, 1, 2, 2, 2]
    blocks = pq.read_table(tmp_path / "out/block").to_pylist()
    assert sum(b["n_files"] for b in blocks) == 9  # 3 records in each of 3 files
    code = pq.read_table(tmp_path / "out/code.parquet").to_pylist()
    assert all(c["name"] is None for c in code if c["billing_code_type"] in ("CPT", "RC"))
