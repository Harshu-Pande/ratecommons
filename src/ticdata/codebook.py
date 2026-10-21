"""Track D: the payer-private code dictionary.

Every code a payer uses outside the public code sets (CSTM-ALL, LOCAL, and anything else not in
the standard list) with how often it appears and what its prices look like. This is step 1 of
the crosswalk in the Rates and codes tab: collect every (payer, code type, code, description)
with counts, rate types and example rates. Mapping to CPT/HCPCS comes later, with evidence.
"""
from __future__ import annotations

import os

STANDARD_TYPES = ("CPT", "HCPCS", "ICD", "MS-DRG", "R-DRG", "S-DRG", "APS-DRG", "AP-DRG", "APR-DRG",
                  "APC", "NDC", "HIPPS", "EAPG", "CDT", "RC")


def build(release_dir: str, out_path: str, payer: str, all_codes: bool = False) -> dict:
    """Read one release's reduced tables (local folder or hf:// path) and write the dictionary."""
    import duckdb

    def src(t: str) -> str:  # a table is one file or a folder of parts
        f = f"{release_dir}/{t}.parquet"
        return f if os.path.exists(f) or "://" in release_dir else f"{release_dir}/{t}/*.parquet"

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    std = ", ".join(f"'{t}'" for t in STANDARD_TYPES)
    where = "" if all_codes else f"WHERE upper(c.billing_code_type) NOT IN ({std}) OR upper(c.billing_code) LIKE 'CSTM%'"
    q = f"""
    WITH c AS (SELECT * FROM read_parquet('{release_dir}/code.parquet')),
         f AS (SELECT * FROM read_parquet('{release_dir}/rate_fact/*.parquet')),
         pl AS (SELECT pl_id, unnest(pt_ids) AS pt_id FROM read_parquet('{src("price_list")}')),
         pt AS (SELECT pt_id, negotiated_type, rate_e4, setting, billing_class FROM read_parquet('{src("price_term")}')),
         sel AS (SELECT * FROM c {where}),
         j AS (
           SELECT sel.billing_code_type, sel.billing_code, sel.name, sel.description, sel.negotiation_arrangement,
                  f.fact_id, f.ns_id, pt.negotiated_type, pt.rate_e4, pt.setting, pt.billing_class
           FROM sel JOIN f ON f.code_id = sel.code_id
                    JOIN pl ON pl.pl_id = f.pl_id
                    JOIN pt ON pt.pt_id = pl.pt_id)
    SELECT '{payer}' AS payer, billing_code_type, billing_code,
           list(DISTINCT name) AS names, list(DISTINCT description) AS descriptions,
           list(DISTINCT negotiation_arrangement) AS arrangements,
           count(DISTINCT fact_id) AS facts, count(DISTINCT ns_id) AS network_sets,
           histogram(negotiated_type) AS negotiated_types, histogram(setting) AS settings,
           histogram(billing_class) AS billing_classes,
           min(rate_e4) / 1e4 AS rate_min, quantile_cont(rate_e4, 0.5) / 1e4 AS rate_median,
           max(rate_e4) / 1e4 AS rate_max
    FROM j GROUP BY billing_code_type, billing_code
    ORDER BY facts DESC
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    con.execute(f"COPY ({q}) TO '{out_path}' (FORMAT parquet, COMPRESSION zstd)")
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out_path}')").fetchone()[0]
    top = con.execute(f"""SELECT billing_code_type, billing_code, descriptions[1], facts, negotiated_types
                          FROM read_parquet('{out_path}') ORDER BY facts DESC LIMIT 15""").fetchall()
    return {"codes": n, "top": [list(map(str, r)) for r in top], "out": out_path}
