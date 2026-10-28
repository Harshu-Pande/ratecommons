"""The Rust core must produce the same tables and IDs as parse.py (skipped if not built)."""
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ticdata.parse import parse_file

BIN = Path(__file__).resolve().parents[1] / "core/target/release/ticcore"
KEYS = {"provider_group": "pg_id", "provider_set": "ps_id", "provider_list": "pli_id", "price_term": "pt_id", "price_list": "pl_id",
        "code": "code_id", "provider_reference": "provider_group_id"}


def rows(folder, table):
    p = Path(folder) / (table if table == "rate_fact" else f"{table}.parquet")
    return pq.read_table(p).to_pylist() if p.exists() else []


def compare(py_dir: str, rs_dir: str) -> dict:
    """Differences between the two outputs; empty dict means identical content."""
    diffs = {}
    for table, key in KEYS.items():
        a = {r[key]: r for r in rows(py_dir, table)}
        b = {r[key]: r for r in rows(rs_dir, table)}
        if set(a) != set(b):
            diffs[table] = {"only_python": len(set(a) - set(b)), "only_rust": len(set(b) - set(a))}
            continue
        for k, ra in a.items():
            rb = b[k]
            for col in ra:
                va, vb = ra[col], rb[col]
                if col in ("business_names",):
                    va, vb = sorted(va or []), sorted(vb or [])
                if va != vb:
                    diffs.setdefault(table, []).append({"key": str(k), "col": col, "python": va, "rust": vb})
                    break
            if len(diffs.get(table, [])) >= 5:
                break
    fa = Counter(tuple(r.values()) for r in rows(py_dir, "rate_fact"))
    fb = Counter(tuple(r.values()) for r in rows(rs_dir, "rate_fact"))
    if fa != fb:
        diffs["rate_fact"] = {"python": sum(fa.values()), "rust": sum(fb.values()), "distinct_diff": len(set(fa) ^ set(fb))}
    ba = Counter(tuple(r.values()) for r in rows(py_dir, "file_block"))
    bb = Counter(tuple(r.values()) for r in rows(rs_dir, "file_block"))
    if ba != bb:
        diffs["file_block"] = {"python": sum(ba.values()), "rust": sum(bb.values())}
    ma = json.loads((Path(py_dir) / "meta.json").read_text())
    mb = json.loads((Path(rs_dir) / "meta.json").read_text())
    for k in ("header", "top_level_keys", "layout", "tail_crc32", "tail_isize"):
        if ma.get(k) != mb.get(k):
            diffs[f"meta.{k}"] = {"python": ma.get(k), "rust": mb.get(k)}
    for k in ("in_network_items", "negotiated_rates", "provider_references", "blocks_new", "blocks_repeated"):
        if ma["counts"].get(k) != mb["counts"].get(k):
            diffs[f"counts.{k}"] = {"python": ma["counts"].get(k), "rust": mb["counts"].get(k)}
    return diffs


def run_both(src: str, tmp: Path, threads: int = 2):
    parse_file(src, str(tmp / "py"))
    out = subprocess.run([str(BIN), "map", src, str(tmp / "rs"), str(threads)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-2000:]
    return compare(str(tmp / "py"), str(tmp / "rs"))


@pytest.mark.skipif(not BIN.exists(), reason="Rust core not built")
def test_rust_matches_python_on_rule_cases(tmp_path):
    from tests.test_parse import _write_two_member_gzip

    src = tmp_path / "f.json.gz"
    _write_two_member_gzip(src)
    assert run_both(str(src), tmp_path) == {}


@pytest.mark.skipif(not BIN.exists() or not os.environ.get("TIC_PARITY_FILES"), reason="no real files given")
def test_rust_matches_python_on_real_files(tmp_path):
    for i, f in enumerate(os.environ["TIC_PARITY_FILES"].split(",")):
        d = run_both(f, tmp_path / str(i), threads=3)
        assert d == {}, (f, d)


@pytest.mark.skipif(not BIN.exists(), reason="Rust core not built")
def test_rust_matches_python_with_wide_references_in_small_batches(tmp_path):
    """Provider lists of the reference pass flush by id count (Anthem NY: ~25k groups per reference)."""
    import gzip

    groups = [{"npi": [1000000000 + i], "tin": {"type": "ein", "value": f"{100000000 + i // 7}"}} for i in range(300)]
    refs = [{"provider_group_id": r, "provider_groups": groups[r % 50:r % 50 + 120 + r]} for r in range(40)]
    items = [{"negotiation_arrangement": "ffs", "name": "x", "billing_code_type": "CPT", "billing_code_type_version": "2026",
              "billing_code": f"{99200 + c}", "description": "d",
              "negotiated_rates": [{"provider_references": [c, c + 1, 39 - c],
                                    "negotiated_prices": [{"negotiated_type": "negotiated", "negotiated_rate": 10.5 + c,
                                                           "expiration_date": "9999-12-31", "billing_class": "professional"}]}]}
             for c in range(20)]
    doc = {"reporting_entity_name": "t", "reporting_entity_type": "payer", "last_updated_on": "2026-10-01", "version": "1.0.0",
           "provider_references": refs, "in_network": items}
    src = tmp_path / "wide.json.gz"
    with gzip.open(src, "wt") as f:
        json.dump(doc, f)
    os.environ["TIC_PLI_BATCH_IDS"] = "500"
    try:
        assert run_both(str(src), tmp_path) == {}
    finally:
        del os.environ["TIC_PLI_BATCH_IDS"]
    assert json.loads((tmp_path / "rs/meta.json").read_text())["counts"]["ref_pli_batches"] >= 2
