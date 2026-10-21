import pyarrow as pa

from ticdata.licensing import redact_codes, text_withheld


def test_withheld_text_rules():
    assert text_withheld("CPT", "99213") and text_withheld("HCPCS", "99213") and text_withheld("cpt", "0075T")
    assert text_withheld("RC", "0450") and text_withheld("APR-DRG", "194") and text_withheld("CDT", "D0120")
    assert not text_withheld("HCPCS", "J1885") and not text_withheld("MS-DRG", "470")
    assert not text_withheld("ICD", "E11.65") and not text_withheld("CSTM-ALL", "URC")


def test_redact_codes_keeps_ids_and_moves_text_aside():
    t = pa.table({"code_id": pa.array([b"a" * 16, b"b" * 16, b"c" * 16], pa.binary(16)),
                  "billing_code_type": ["CPT", "HCPCS", "CSTM-ALL"], "billing_code": ["99213", "J1885", "URC"],
                  "name": ["OFFICE VISIT", "KETOROLAC", "URGENT CARE"], "description": ["x", "y", "z"],
                  "bundle": [None, None, '{"bundled_codes": [{"billing_code_type": "CPT", "billing_code": '
                                         '"99283", "description": "ER VISIT"}]}']})
    pub, priv = redact_codes(t)
    rows = pub.to_pylist()
    assert rows[0]["name"] is None and rows[0]["description"] is None and rows[0]["text_withheld"]
    assert rows[1]["name"] == "KETOROLAC" and not rows[1]["text_withheld"]
    assert rows[2]["name"] == "URGENT CARE" and "ER VISIT" not in rows[2]["bundle"] and rows[2]["text_withheld"]
    assert [r["billing_code"] for r in priv.to_pylist()] == ["99213", "URC"]
    assert priv.to_pylist()[0]["name"] == "OFFICE VISIT"
    again, priv2 = redact_codes(pub)  # idempotent
    assert again.to_pylist() == rows and priv2.num_rows == 0
