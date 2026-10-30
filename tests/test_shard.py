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


def test_wave_reduce_then_merge_equals_one_reduce(tmp_path):
    """Two waves reduced separately and merged give the same facts and network sets as one reduce."""
    import shutil

    from ticdata.pipeline import run_shard
    from ticdata.reduce import merge_part_local, reduce_dims_local, reduce_part_local

    web = tmp_path / "web"
    web.mkdir()
    doc_b = copy.deepcopy(DOC)
    doc_b["in_network"][0]["negotiated_rates"][0]["negotiated_prices"][0]["negotiated_rate"] = 80.0
    docs = {"2026-10-01_a.json.gz": DOC, "2026-10-01_b.json.gz": doc_b, "2026-10-01_c.json.gz": doc_b}
    docs["2026-10-01_c.json.gz"] = copy.deepcopy(doc_b)
    docs["2026-10-01_c.json.gz"]["in_network"][1]["negotiated_rates"][0]["negotiated_prices"][0]["negotiated_rate"] = 99
    for n, d in docs.items():
        (web / n).write_bytes(gzip.compress(json.dumps(d).encode()))
    srv = _serve(web)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    f = lambda n: {"name": n, "url": f"{base}/{n}"}  # noqa: E731
    plan = {"payer": "test", "shards": [{"shard": 0, "files": [f("2026-10-01_a.json.gz"), f("2026-10-01_b.json.gz")]},
                                        {"shard": 1, "files": [f("2026-10-01_c.json.gz")]}]}
    for sh in (0, 1):
        run_shard(plan, sh, workdir=str(tmp_path / "work"), chunk_out=str(tmp_path / "map"))
    srv.shutdown()
    for k in range(16):
        reduce_part_local(str(tmp_path / "map"), "test", "2026-10", k, str(tmp_path / "one"))
    for w, sh in ((1, "shard-000-00"), (2, "shard-001-00")):
        (tmp_path / f"w{w}").mkdir()
        shutil.copytree(tmp_path / "map" / sh, tmp_path / f"w{w}" / sh)
        for k in range(16):
            reduce_part_local(str(tmp_path / f"w{w}"), "test", "2026-10", k, str(tmp_path / "waves" / f"wave-{w}"),
                              keys=True)
        reduce_dims_local(str(tmp_path / f"w{w}"), "test", str(tmp_path / "waves" / f"wave-{w}"), "provider_group")
    for k in range(16):
        merge_part_local(str(tmp_path / "waves"), "2026-10", k, str(tmp_path / "merged"))
    one, merged = _fact_sets(tmp_path / "one"), _fact_sets(tmp_path / "merged")
    assert one == merged and sorted(len(s) for s in one.values()).count(3) >= 1
    dims = reduce_dims_local(str(tmp_path / "waves"), "test", str(tmp_path / "mdims"), "provider_group")
    single = reduce_dims_local(str(tmp_path / "map"), "test", str(tmp_path / "sdims"), "provider_group")
    assert dims["tables"]["provider_group"]["rows_out"] == single["tables"]["provider_group"]["rows_out"] == 4
    a = pq.read_table(tmp_path / "mdims/provider_group.parquet").sort_by("pg_id").to_pylist()
    b = pq.read_table(tmp_path / "sdims/provider_group.parquet").sort_by("pg_id").to_pylist()
    assert [sorted(r["tin_raws"]) for r in a] == [sorted(r["tin_raws"]) for r in b]


def test_shard_status_lists_failed_files(tmp_path, monkeypatch):
    """A shard uploads what parsed and says which files failed, so the orchestrator waits for a retry."""
    from ticdata.pipeline import run_shard

    monkeypatch.setenv("TIC_CORE", "")
    web = tmp_path / "web"
    web.mkdir()
    (web / "2026-10-01_a.json.gz").write_bytes(gzip.compress(json.dumps(DOC).encode()))
    srv = _serve(web)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    names = ["2026-10-01_a.json.gz", "2026-10-01_gone.json.gz"]
    plan = {"payer": "test", "shards": [{"shard": 0, "files": [{"name": n, "url": f"{base}/{n}"} for n in names]}]}
    res = run_shard(plan, 0, workdir=str(tmp_path / "work"), chunk_out=str(tmp_path / "map"))
    srv.shutdown()
    assert res["ok"] == 1
    status = json.loads((tmp_path / "map/shard-000-status.json").read_text())
    assert status == {"shard": 0, "files": 2, "failed": ["2026-10-01_gone.json.gz"]}


def test_orchestrator_skips_shards_with_failed_files(monkeypatch):
    import sys
    from types import SimpleNamespace

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
    import orchestrate
    import huggingface_hub

    pre = "map/2026-10/p/"
    paths = [f"{pre}shard-000-00/metas.json", f"{pre}shard-001-00/metas.json", f"{pre}shard-002-00/metas.json",
             f"{pre}shard-001-status.json", f"{pre}shard-002-status.json"]
    texts = {f"buckets/{orchestrate.BUCKET}/{pre}shard-001-status.json": '{"failed": ["x.json.gz"]}',
             f"buckets/{orchestrate.BUCKET}/{pre}shard-002-status.json": '{"failed": []}'}
    monkeypatch.setattr(orchestrate, "list_bucket_tree", lambda *a, **k: [SimpleNamespace(path=p) for p in paths])
    monkeypatch.setattr(huggingface_hub, "HfFileSystem", lambda: SimpleNamespace(read_text=texts.__getitem__))
    assert orchestrate.mapped_shards("p", "2026-10") == {0, 2}


def test_packs_follow_the_newest_successful_merge(monkeypatch):
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
    import orchestrate

    runs = {"reduce.yml": [{"id": 9, "display_title": "reduce p 2026-10 all merge", "status": "completed",
                            "conclusion": "success", "created_at": "2026-10-28T09:00:00Z", "updated_at": "T10"}],
            "serve.yml": [{"id": 5, "display_title": "serve p:dataset", "status": "completed", "conclusion": "success",
                           "created_at": "2026-10-28T07:35:00Z", "updated_at": "2026-10-28T08:00:00Z"}]}
    calls = []
    monkeypatch.setattr(orchestrate, "AUTO_PACK", ["p"])
    monkeypatch.setattr(orchestrate, "merge_done", lambda *a: True)
    monkeypatch.setattr(orchestrate, "gh", lambda path: {"workflow_runs": runs[path.split("/workflows/")[1].split("/")[0]]})
    monkeypatch.setattr(orchestrate.subprocess, "check_call", lambda cmd: calls.append(cmd))
    orchestrate.packs([["p", "2026-10", "merge"]])
    assert len(calls) == 1 and "serve.yml" in calls[0][4]  # the serve run predates the re-merge: pack again
    runs["reduce.yml"][0].update(status="in_progress", conclusion=None)
    calls.clear()
    orchestrate.packs([["p", "2026-10", "merge"]])
    assert calls == []  # a merge still running (not this run) is not packed
    monkeypatch.setenv("SELF_RUN_ID", "9")
    orchestrate.packs([["p", "2026-10", "merge"]])
    assert len(calls) == 1


def test_sliced_merge_equals_unsliced(tmp_path, monkeypatch):
    """merge_part_local cut into fact_id hash slices gives the same facts and network sets."""
    import shutil

    from ticdata.pipeline import run_shard
    from ticdata.reduce import merge_part_local, reduce_part_local

    web = tmp_path / "web"
    web.mkdir()
    docs = {}
    for i in range(4):
        d = copy.deepcopy(DOC)
        d["in_network"][0]["negotiated_rates"][0]["negotiated_prices"][0]["negotiated_rate"] = 50.0 + (i % 2)
        d["last_updated_on"] = f"2026-10-0{i + 1}"  # distinct files (a network is a file's content identity)
        docs[f"2026-10-01_{i}.json.gz"] = d
    for n, d in docs.items():
        (web / n).write_bytes(gzip.compress(json.dumps(d).encode()))
    srv = _serve(web)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    plan = {"payer": "test", "shards": [{"shard": i, "files": [{"name": n, "url": f"{base}/{n}"}]}
                                        for i, n in enumerate(docs)]}
    for sh in range(4):
        run_shard(plan, sh, workdir=str(tmp_path / "work"), chunk_out=str(tmp_path / "map"))
    srv.shutdown()
    for w in range(4):
        (tmp_path / f"w{w}").mkdir()
        shutil.copytree(tmp_path / "map" / f"shard-00{w}-00", tmp_path / f"w{w}" / f"shard-00{w}-00")
        for k in range(16):
            reduce_part_local(str(tmp_path / f"w{w}"), "test", "2026-10", k, str(tmp_path / "waves" / f"wave-{w}"),
                              keys=True)
    shutil.copytree(tmp_path / "waves", tmp_path / "waves2")
    for k in range(16):
        merge_part_local(str(tmp_path / "waves"), "2026-10", k, str(tmp_path / "one"))
    monkeypatch.setenv("RC_MERGE_SLICE_BYTES", "1")
    monkeypatch.setenv("RC_SET_SLICE_ROWS", "1")
    for k in range(16):
        merge_part_local(str(tmp_path / "waves2"), "2026-10", k, str(tmp_path / "sliced"))
    assert _fact_sets(tmp_path / "one") == _fact_sets(tmp_path / "sliced")
    ns = lambda d: sorted((r["ns_id"], tuple(r["network_ids"])) for r in pq.read_table(d / "network_set").to_pylist())  # noqa: E731
    assert ns(tmp_path / "one") == ns(tmp_path / "sliced")


def test_uhc_shards_are_mapped_only_after_their_status_file(monkeypatch):
    import sys
    from types import SimpleNamespace

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
    import orchestrate
    import huggingface_hub

    pre = "map/2026-10/uhc/"
    paths = [f"{pre}shard-024-00/metas.json", f"{pre}shard-025-00/metas.json", f"{pre}shard-025-status.json"]
    texts = {f"buckets/{orchestrate.BUCKET}/{pre}shard-025-status.json": '{"failed": []}'}
    monkeypatch.setattr(orchestrate, "list_bucket_tree", lambda *a, **k: [SimpleNamespace(path=p) for p in paths])
    monkeypatch.setattr(huggingface_hub, "HfFileSystem", lambda: SimpleNamespace(read_text=texts.__getitem__))
    assert orchestrate.mapped_shards("uhc", "2026-10") == {25}  # 24 is still mapping (a chunk is in, no status)
    from ticdata import pipeline

    monkeypatch.setattr(huggingface_hub, "list_bucket_tree", lambda *a, **k: [SimpleNamespace(path=p) for p in paths])
    assert pipeline.wave_ready("ratecommons/work", "2026-10", "uhc", (25, 25)) == []
    assert pipeline.wave_ready("ratecommons/work", "2026-10", "uhc", (24, 25))[0].startswith("shard 24")
    assert pipeline.wave_ready("ratecommons/work", "2026-10", "aetna", (0, 7)) == []


def test_start_maps_reruns_only_missing_shards(monkeypatch):
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
    import orchestrate

    calls = []
    monkeypatch.setattr(orchestrate, "gh", lambda path: {"workflow_runs": []})
    monkeypatch.setattr(orchestrate, "mapped_shards", lambda p, r: set(range(24, 36)) - {32})
    monkeypatch.setattr(orchestrate, "wave_done", lambda p, r, w: w in ("1", "2"))
    monkeypatch.setattr(orchestrate.subprocess, "check_call", lambda cmd: calls.append(cmd))
    waves = [["uhc", "2026-10", "1", "0-11"], ["uhc", "2026-10", "2", "12-23"], ["uhc", "2026-10", "3", "24-35"]]
    orchestrate.start_maps(waves)
    assert calls and calls[0][-1] == "inputs[range]=32"


def test_batched_split_of_a_big_fact_part_gives_the_same_wave(tmp_path, monkeypatch):
    """reduce_part with facts downloaded and sliced batch by batch equals the one-download path."""
    import shutil
    from types import SimpleNamespace

    import huggingface_hub

    from ticdata import reduce as R
    from ticdata.pipeline import run_shard

    web = tmp_path / "web"
    web.mkdir()
    names = []
    for i in range(4):
        d = copy.deepcopy(DOC)
        d["in_network"][0]["negotiated_rates"][0]["negotiated_prices"][0]["negotiated_rate"] = 50.0 + (i % 2)
        d["last_updated_on"] = f"2026-10-0{i + 1}"
        n = f"2026-10-01_{i}.json.gz"
        (web / n).write_bytes(gzip.compress(json.dumps(d).encode()))
        names.append(n)
    srv = _serve(web)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    plan = {"payer": "test", "shards": [{"shard": i, "files": [{"name": n, "url": f"{base}/{n}"}]}
                                        for i, n in enumerate(names)]}
    remote = tmp_path / "remote" / "map/2026-10/test"
    for sh in range(4):
        run_shard(plan, sh, workdir=str(tmp_path / "work"), chunk_out=str(remote))
    srv.shutdown()
    root = tmp_path / "remote"
    paths = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]

    def fetch(bucket, ps, dest, prefix, token):
        out = []
        for p in ps:
            d = os.path.join(dest, os.path.relpath(p, prefix))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy(root / p, d)
            out.append(d)
        return out

    monkeypatch.setattr(R, "_list", lambda b, prefix, t: [p for p in paths if p.startswith(prefix)])
    monkeypatch.setattr(R, "_fetch", fetch)
    monkeypatch.setattr(huggingface_hub, "list_bucket_tree", lambda *a, **k: [
        SimpleNamespace(path=p, size=(root / p).stat().st_size) for p in paths])
    for label, limit in (("one", str(1 << 40)), ("batched", "0")):
        monkeypatch.setenv("RC_BATCH_SPLIT_BYTES", limit)
        monkeypatch.setenv("RC_SPLIT_BATCH_BYTES", "1")  # one file per batch
        for k in range(16):
            R.reduce_part("test", "2026-10", k, "b", str(tmp_path / label), workdir=str(tmp_path / f"w-{label}-{k}"),
                          shards=(0, 3), keys=True)
    assert _fact_sets(tmp_path / "one") == _fact_sets(tmp_path / "batched")


def test_a_payer_waiting_for_shards_does_not_stall_the_next(monkeypatch):
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
    import orchestrate

    waves = [["bcbs", "2026-10", "3", "24-27"], ["bcbs", "2026-10", "4", "28-33"], ["bcbs", "2026-10", "merge"],
             ["uhc", "2026-10", "4", "36-47"]]
    calls = []
    monkeypatch.setattr(orchestrate, "gh", lambda path: {"workflow_runs": []})
    for step in ("clean", "start_maps", "packs"):
        monkeypatch.setattr(orchestrate, step, lambda w: None)
    monkeypatch.setattr(orchestrate, "wave_done", lambda p, r, w: (p, w) == ("bcbs", "3"))
    monkeypatch.setattr(orchestrate, "merge_done", lambda *a: False)
    monkeypatch.setattr(orchestrate, "mapped_shards", lambda p, r: set(range(0, 28)) if p == "bcbs" else set(range(48)))
    monkeypatch.setattr(orchestrate.subprocess, "check_call", lambda cmd: calls.append(cmd))
    monkeypatch.setattr("builtins.open", lambda *a, **k: __import__("io").StringIO(
        "\n".join(" ".join(w) for w in waves)))
    orchestrate.main()
    assert calls and calls[0][-1] == "inputs[request]=uhc 2026-10 all wave=4 36-47"


def _three_file_plan(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    names = []
    for i in range(3):
        d = copy.deepcopy(DOC)
        d["last_updated_on"] = f"2026-10-0{i + 1}"
        n = f"2026-10-01_r{i}.json.gz"
        (web / n).write_bytes(gzip.compress(json.dumps(d).encode()))
        names.append(n)
    srv = _serve(web)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    return srv, {"payer": "test", "shards": [{"shard": 0, "files": [{"name": n, "url": f"{base}/{n}"} for n in names]}]}


def test_shard_time_budget_then_resume(tmp_path, monkeypatch):
    """Out of time: unstarted files are listed as failed. A re-run skips files its chunks already hold and numbers new
    chunks after them."""
    import copy as _copy

    from ticdata.pipeline import run_shard

    monkeypatch.setenv("TIC_CORE", "")
    srv, plan = _three_file_plan(tmp_path)
    monkeypatch.setenv("TIC_SHARD_BUDGET_MIN", "0")
    res = run_shard(plan, 0, workdir=str(tmp_path / "work"), chunk_files=1, chunk_out=str(tmp_path / "map"))
    assert res["ok"] == 0 and len(json.loads((tmp_path / "map/shard-000-status.json").read_text())["failed"]) == 3
    monkeypatch.setenv("TIC_SHARD_BUDGET_MIN", "320")
    first = _copy.deepcopy(plan)
    first["shards"][0]["files"] = first["shards"][0]["files"][:1]  # an earlier run got through one file
    run_shard(first, 0, workdir=str(tmp_path / "work"), chunk_files=1, chunk_out=str(tmp_path / "map"))
    res = run_shard(plan, 0, workdir=str(tmp_path / "work"), chunk_files=1, chunk_out=str(tmp_path / "map"))
    srv.shutdown()
    assert res["ok"] == 3 and [r["name"] for r in res["results"] if r.get("resumed")] == ["2026-10-01_r0.json.gz"]
    assert sorted(p.name for p in (tmp_path / "map").glob("shard-000-*") if p.is_dir()) == \
        ["shard-000-00", "shard-000-01", "shard-000-02"]
    assert json.loads((tmp_path / "map/shard-000-status.json").read_text())["failed"] == []


def test_plan_spreads_many_small_files_with_a_per_file_cost(monkeypatch):
    from ticdata import pipeline

    es = [{"kind": "in_network", "name": "big.json.gz", "url": "https://h/big", "size": 100 << 20}] + \
         [{"kind": "in_network", "name": f"s{i:03d}.json.gz", "url": f"https://h/s{i}", "size": 1 << 20} for i in range(100)]
    monkeypatch.setitem(pipeline.PAYERS, "zz", lambda s: ({}, es))
    plain = pipeline.plan("zz", 2)
    weighted = pipeline.plan("zz", 2, file_bytes=10 << 20)
    assert [len(sh["files"]) for sh in plain["shards"]] == [1, 100]
    assert max(len(sh["files"]) for sh in weighted["shards"]) < 100


def test_listed_unavailable_files_do_not_block_a_wave(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
    import orchestrate
    import huggingface_hub
    from ticdata import pipeline

    listing = tmp_path / "unavailable.txt"
    listing.write_text("# payer name  # why\nbcbs gone.json.gz  # 404 at the publisher\nuhc other.json\n")
    assert pipeline.unavailable("bcbs", listing) == {"gone.json.gz"}
    monkeypatch.setattr(pipeline, "UNAVAILABLE", listing)
    pre = "map/2026-10/bcbs/"
    paths = [f"{pre}shard-033-00/metas.json", f"{pre}shard-033-status.json", f"{pre}shard-034-00/metas.json",
             f"{pre}shard-034-status.json"]
    texts = {f"buckets/{orchestrate.BUCKET}/{pre}shard-033-status.json": '{"failed": ["gone.json.gz"]}',
             f"buckets/{orchestrate.BUCKET}/{pre}shard-034-status.json": '{"failed": ["gone.json.gz", "bad.json"]}'}
    for mod in (orchestrate, huggingface_hub):
        monkeypatch.setattr(mod, "list_bucket_tree", lambda *a, **k: [SimpleNamespace(path=p) for p in paths])
    monkeypatch.setattr(huggingface_hub, "HfFileSystem", lambda: SimpleNamespace(read_text=texts.__getitem__))
    assert orchestrate.mapped_shards("bcbs", "2026-10") == {33}
    assert pipeline.wave_ready("ratecommons/work", "2026-10", "bcbs", (33, 33)) == []
    assert pipeline.wave_ready("ratecommons/work", "2026-10", "bcbs", (33, 34)) == ["shard 34: 1 failed file(s), e.g. bad.json"]
