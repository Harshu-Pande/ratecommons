"""Parser v0 against a small file that contains the deviations listed in the Parser rules tab."""
import gzip
import json

import pyarrow.parquet as pq

from ticdata.parse import h, parse_file

DOC = {
    "reporting_entity_name": "Test Insurer",
    "reporting_entity_type": "Health Insurance Issuer",
    "last_updated_on": "2026-10-01",
    "version": "V2.0.0",
    "provider_references": [
        # NPIs as strings, EIN missing a leading zero with trailing spaces
        {"provider_group_id": 0, "network_name": ["Behavior Health"],
         "provider_groups": [{"npi": ["1234567893", "1003000126"],
                              "tin": {"type": "ein", "value": "42774441  ", "business_name": "A Clinic"}}]},
        # the same group again under another id and name, plus a TIN-wide group
        {"provider_group_id": 161.0007115279, "network_name": ["X"],
         "provider_groups": [{"npi": [1003000126, 1234567893],
                              "tin": {"type": "ein", "value": "042774441", "business_name": "A Clinic LLC"}},
                             {"npi": [0], "tin": {"type": "ein", "value": "12-3456789", "business_name": "B"}}]},
        # a stray 0 mixed into real NPIs
        {"provider_group_id": 123456789012345678901234567890123456789,
         "provider_groups": [{"npi": [0, 1497758544], "tin": {"type": "npi", "value": "1497758544"}}]},
    ],
    "in_network": [
        {"negotiation_arrangement": "ffs", "name": "OFFICE VISIT", "billing_code_type": "CPT",
         "billing_code_type_version": "2026", "billing_code": "99213", "description": "Office visit",
         "negotiated_rates": [
             {"provider_references": [0, 161.0007115279],
              "negotiated_prices": [
                  {"negotiated_type": "negotiated", "negotiated_rate": 73.31, "expiration_date": "9999-12-31",
                   "service_code": ["11", "1"], "billing_class": "professional", "setting": "outpatient"},
                  {"negotiated_type": "negotiated", "negotiated_rate": 99.68, "expiration_date": "9999-12-31",
                   "service_code": ["11", "1"], "billing_class": "professional", "setting": "outpatient"}]},
             {"provider_references": [123456789012345678901234567890123456789, 999],
              "negotiated_prices": [
                  {"negotiated_type": "fee schedule", "negotiated_rate": 0.01, "expiration_date": "9999-12-31",
                   "billing_class": "institutional", "additional_information": "RC[0369-0369]"}]}]},
        {"negotiation_arrangement": "ffs", "name": "URGENT CARE", "billing_code_type": "CSTM-ALL",
         "billing_code": "URC", "description": "URGENT CARE",
         "negotiated_rates": [
             {"provider_groups": [{"npi": ["1234567893"], "tin": {"type": "ein", "value": "042774441"}}],
              "negotiated_prices": [{"negotiated_type": "per diem", "negotiated_rate": 255,
                                     "expiration_date": "9999-12-31", "billing_class": "institutional",
                                     "setting": "outpatient", "service_code": ["CSTM-00"]}]}]},
        {"negotiation_arrangement": "ffs", "name": "R", "billing_code_type": "RC", "billing_code": "918   ",
         "description": "rev", "negotiated_rates": [
             {"provider_references": [0], "negotiated_prices": [
                 {"negotiated_type": "percentage", "negotiated_rate": 63.7, "expiration_date": "9999-12-31",
                  "billing_class": "institutional", "setting": "both"}]}]},
    ],
}


def _write_two_member_gzip(path):
    raw = json.dumps(DOC).encode()
    cut = raw.index(b'"in_network"')
    with open(path, "wb") as f:  # UHC-style: several concatenated gzip members
        f.write(gzip.compress(raw[:cut]))
        f.write(gzip.compress(raw[cut:]))


def test_parse_file_normalizes_and_flags(tmp_path):
    src = tmp_path / "f.json.gz"
    _write_two_member_gzip(src)
    meta = parse_file(str(src), str(tmp_path / "out"))
    fl = meta["flags"]

    pg = pq.read_table(tmp_path / "out/provider_group.parquet").to_pylist()
    # the string-NPI group and the integer-NPI group collapse to one pg_id; both names kept
    clinic = [g for g in pg if g["tin_value"] == "042774441" and g["npi_count"] == 2]
    assert len(clinic) == 1 and set(clinic[0]["business_names"]) == {"A Clinic", "A Clinic LLC"}
    assert fl["ein_left_padded"] >= 1 and fl["npi_as_string"] >= 1 and fl["npi_zero_mixed_in"] == 1
    tin_wide = [g for g in pg if g["tin_value"] == "123456789"]
    assert tin_wide[0]["tin_wide"] and tin_wide[0]["npis"] == []

    refs = {r["provider_group_id"]: r for r in pq.read_table(tmp_path / "out/provider_reference.parquet").to_pylist()}
    assert "161.0007115279" in refs and "123456789012345678901234567890123456789" in refs
    assert fl["provider_reference_unresolved"] == 1  # id 999

    pt = pq.read_table(tmp_path / "out/price_term.parquet").to_pylist()
    rates = sorted(p["rate_e4"] for p in pt)
    assert rates == [100, 637000, 733100, 996800, 2550000]
    assert any("placeholder_amount" in p["flags"] for p in pt)
    assert any(p["applies_to_revenue_codes"] == ["0369-0369"] for p in pt)
    assert all(p["service_code"] in ([], ["01", "11"], ["CSTM-00"]) for p in pt)
    assert fl["price_list_multiple_amounts"] == 1

    codes = {c["billing_code"]: c for c in pq.read_table(tmp_path / "out/code.parquet").to_pylist()}
    assert "0918" in codes and codes["0918"]["billing_code_raw"] == "918   "

    facts = pq.read_table(tmp_path / "out/rate_fact").to_pylist()
    assert len(facts) == 4 and meta["counts"]["negotiated_rates"] == 4
    assert set(meta["layout"]) == {"provider_references", "inline_provider_groups"}
    assert meta["header"]["version"] == "V2.0.0" and meta["header"]["reporting_entity_name"] == "Test Insurer"


def test_ids_are_deterministic_and_order_free():
    assert h("ps", [b"\x01" * 16, b"\x02" * 16]) == h("ps", [b"\x02" * 16, b"\x01" * 16])
    assert h("pt", "negotiated", 1) != h("pt", "negotiated", 10)


def test_reduce_merges_identical_files_into_one_network(tmp_path):
    import shutil

    from ticdata.reduce import reduce_dims_local, reduce_part_local

    src = tmp_path / "f.json.gz"
    _write_two_member_gzip(src)
    parse_file(str(src), str(tmp_path / "map/a"), {"name": "a"})
    shutil.copytree(tmp_path / "map/a", tmp_path / "map/b")  # same bytes under another name
    facts = 0
    for k in range(16):
        facts += reduce_part_local(str(tmp_path / "map"), "test", "2026-10", k, str(tmp_path / "out")).get("facts", 0)
    assert facts == 4
    dims = reduce_dims_local(str(tmp_path / "map"), "test", str(tmp_path / "out"))
    assert dims["networks"] == 1 and dims["files"] == 2
    assert dims["tables"]["price_term"]["rows_out"] == 5
    sets = pq.read_table(tmp_path / "out/network_set").to_pylist()
    assert {len(s["network_ids"]) for s in sets} == {1}


def _fact_sets(out):
    """fact_id -> frozenset of network_ids, from a reduced release folder."""
    sets = {r["ns_id"]: frozenset(r["network_ids"]) for r in pq.read_table(out / "network_set").to_pylist()}
    return {r["fact_id"]: sets[r["ns_id"]] for r in pq.read_table(out / "rate_fact").to_pylist()}


def test_reduce_network_sets_blocks_and_files_modes_agree(tmp_path):
    """A fact shared by two files in different blocks gets both networks, in both reduce modes."""
    import copy
    import shutil

    from ticdata.reduce import reduce_part_local

    doc_b = copy.deepcopy(DOC)
    doc_b["in_network"][0]["negotiated_rates"][0]["negotiated_prices"][0]["negotiated_rate"] = 80.0
    (tmp_path / "b.json").write_text(json.dumps(doc_b))
    _write_two_member_gzip(tmp_path / "a.json.gz")
    with open(tmp_path / "b.json.gz", "wb") as f:
        f.write(gzip.compress((tmp_path / "b.json").read_bytes()))
    results = {}
    for mode, shared in (("blocks", set()), ("blocks_sep", None), ("files", None)):
        m = tmp_path / mode / "map"
        parse_file(str(tmp_path / "a.json.gz"), str(m / "a"), {"name": "a"}, shared)
        parse_file(str(tmp_path / "b.json.gz"), str(m / "b"), {"name": "b"}, shared)
        shutil.copytree(m / "a", m / "c")  # identical file: same network as a
        if mode == "files":
            for fb in m.glob("*/file_block.parquet"):
                fb.unlink()
        for k in range(16):
            r = reduce_part_local(str(m), "test", "2026-10", k, str(tmp_path / mode / "out"))
            assert r.get("mode", mode.split("_")[0]) == mode.split("_")[0]
        results[mode] = _fact_sets(tmp_path / mode / "out")
    assert results["blocks"] == results["files"] == results["blocks_sep"]
    sizes = sorted(len(s) for s in results["files"].values())
    # 99213 group 1 (one price list): one fact only in a, one only in b, since the changed price changes
    # the price list; the other 3 facts (99213 group 2, URC, RC 918) are in both networks
    assert sizes == [1, 1, 2, 2, 2]


def test_codebook_on_a_reduced_release(tmp_path):
    from ticdata import codebook
    from ticdata.reduce import reduce_dims_local, reduce_part_local

    _write_two_member_gzip(tmp_path / "a.json.gz")
    parse_file(str(tmp_path / "a.json.gz"), str(tmp_path / "map/a"), {"name": "a"})
    for k in range(16):
        reduce_part_local(str(tmp_path / "map"), "test", "2026-10", k, str(tmp_path / "out"))
    reduce_dims_local(str(tmp_path / "map"), "test", str(tmp_path / "out"))
    res = codebook.build(str(tmp_path / "out"), str(tmp_path / "cb.parquet"), "test")
    rows = pq.read_table(tmp_path / "cb.parquet").to_pylist()
    assert res["codes"] == 1 and rows[0]["billing_code"] == "URC" and rows[0]["rate_max"] == 255
    assert (tmp_path / "out.restricted/code_text.parquet").exists()  # the CPT name went private
    code = {r["billing_code"]: r for r in pq.read_table(tmp_path / "out/code.parquet").to_pylist()}
    assert code["99213"]["name"] is None and code["99213"]["text_withheld"] and code["URC"]["name"] == "URGENT CARE"
