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
