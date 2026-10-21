"""What code text we may republish.

Rates and code numbers are public by design (the rule names researchers and developers as
intended users). Descriptor text is not always ours to republish: CPT descriptors (including
Category II/III and PLA codes) are AMA copyright, CDT is ADA's, revenue-code descriptions are
licensed by the AHA/NUBC, and APR-DRG, AP-DRG and EAPG are proprietary groupers. Payer files
often carry that text in `name`, `description` and bundled-code descriptions.

Design rule (Licensing and legal constraints): publish code numbers, never republish CPT
descriptions found in payer files. Invariant: discard no data. So the raw text is split off,
not dropped: the public code table keeps the row (and its content-hash `code_id`, computed
over the raw text) with the text nulled and `text_withheld = true`; the raw text goes to the
private restricted bucket.

Text from public code sets (HCPCS Level II, MS-DRG, ICD, NDC, APC, HIPPS) and payer-defined
codes (CSTM-ALL, LOCAL and the like) is published as found.
"""
from __future__ import annotations

import json
import re

LICENSED_TYPES = {"CPT", "CDT", "RC", "APR-DRG", "AP-DRG", "APS-DRG", "R-DRG", "S-DRG", "EAPG"}
CPT_LIKE = re.compile(r"^\d{4}[0-9FTU]$", re.I)  # CPT, Category II (F), III (T), PLA (U)
HCPCS_LEVEL_II = re.compile(r"^[A-V]\d{4}$", re.I)
TEXT_COLUMNS = ("name", "description")


def text_withheld(ctype: str | None, code: str | None) -> bool:
    t = (ctype or "").strip().upper()
    c = (code or "").strip()
    if CPT_LIKE.match(c) or t in LICENSED_TYPES:
        return True
    if t == "HCPCS":
        return not HCPCS_LEVEL_II.match(c)
    return False


def redact_bundle(bundle: str | None) -> tuple[str | None, bool]:
    """Drop withheld descriptions inside bundled_codes / covered_services; (text, changed)."""
    if not bundle:
        return bundle, False
    try:
        doc = json.loads(bundle)
    except ValueError:
        return None, True  # unparseable: withhold rather than guess
    changed = False
    for key in ("bundled_codes", "covered_services"):
        for item in doc.get(key) or []:
            if isinstance(item, dict) and item.get("description") is not None and \
                    text_withheld(str(item.get("billing_code_type") or ""), str(item.get("billing_code") or "")):
                item["description"] = None
                changed = True
    return (json.dumps(doc) if changed else bundle), changed


def redact_codes(table):
    """Split a code table into (public table, private raw-text table)."""
    import pyarrow as pa

    rows = table.to_pylist()
    public, private = [], []
    for r in rows:
        withheld = text_withheld(r.get("billing_code_type"), r.get("billing_code"))
        bundle, bchanged = redact_bundle(r.get("bundle"))
        already = bool(r.get("text_withheld"))
        out = dict(r)
        if withheld:
            for c in TEXT_COLUMNS:
                out[c] = None
        out["bundle"] = bundle
        out["text_withheld"] = withheld or bchanged or already
        public.append(out)
        if (withheld and any(r.get(c) is not None for c in TEXT_COLUMNS)) or bchanged:
            private.append({"code_id": r["code_id"], "billing_code_type": r.get("billing_code_type"),
                            "billing_code": r.get("billing_code"), "name": r.get("name"),
                            "description": r.get("description"), "bundle": r.get("bundle")})
    schema = table.schema
    if "text_withheld" not in schema.names:
        schema = schema.append(pa.field("text_withheld", pa.bool_()))
    priv_schema = pa.schema([schema.field(c) for c in ("code_id", "billing_code_type", "billing_code", "name",
                                                       "description", "bundle")])
    return pa.Table.from_pylist(public, schema=schema), pa.Table.from_pylist(private, schema=priv_schema)


def redact_code_file(path: str, private_path: str) -> dict:
    """Rewrite a code.parquet in place as its public form; write the withheld text beside it."""
    import pyarrow.parquet as pq

    pub, priv = redact_codes(pq.read_table(path))
    pq.write_table(pub, path, compression="zstd")
    if priv.num_rows:
        pq.write_table(priv, private_path, compression="zstd")
    return {"rows": pub.num_rows, "withheld": int(sum(pub.column("text_withheld").to_pylist())),
            "private_rows": priv.num_rows}
