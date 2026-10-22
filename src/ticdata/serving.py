"""Serving packs: the release tables rearranged for fast interactive questions (the app and MCP tools).

A pack keeps every published value but lays it out for "this code, in this area":

  rate/part-XX.parquet      billing code, provider set, price term, network set: one row per fact and
                            price term, sorted by code in small row groups (a code reads a few MB)
  price_term.parquet        the price terms the pack uses (as published)
  ps_pli/state=XX/*.parquet provider set -> provider list, only the lists with a provider group
                            practicing in that state (a list in several states is in each)
  pli_pg.parquet            provider list -> provider group
  provider_group.parquet    TIN, NPIs, tin_wide, business-name hints, and the states it practices in
  pg_npi/state=XX/*.parquet provider group -> NPI located in that state (NPPES practice address); a
                            TIN-wide group (npi 0) has npi NULL and the state of its EIN where known
  ns.parquet                network set -> network
  network.parquet           network -> payer, file names, plan names (Aetna's table of contents)
  code.parquet              codes as published (text withheld where licensed)

Geography comes from identifiers only (NPI -> NPPES practice location, EIN -> IRS exempt-org
address), never from names. A pack can be a subset of networks (`networks`); a fact is kept when its
network set holds one of them, and `ns` then lists only those networks.

Shared tables (identity dataset, serving/): nppes (npi -> name, place, primary taxonomy and its
NUCC description), medicare_pfs (CY national physician fee schedule amounts per HCPCS/modifier).
"""
from __future__ import annotations

import csv
import glob
import io
import json
import os
import re
import shutil
import time
import zipfile


def _src(base: str, table: str) -> str:
    one = f"{base}/{table}.parquet"
    if os.path.exists(one):
        return f"read_parquet('{one}', union_by_name = true)"
    files = sorted(glob.glob(f"{base}/{table}/*.parquet"))
    if not files:
        raise FileNotFoundError(f"{base}/{table}")
    return f"read_parquet({files!r}, union_by_name = true)"


def _duck(work: str, mem: str | None = None):
    import duckdb

    os.makedirs(work, exist_ok=True)
    con = duckdb.connect(f"{work}/pack-{time.time_ns()}.db")
    con.execute("SET preserve_insertion_order = false")
    con.execute("SET enable_progress_bar = false")
    con.execute(f"SET memory_limit = '{mem or os.environ.get('RC_DUCK_MEMORY', '10GB')}'")
    con.execute(f"SET temp_directory = '{work}/tmp'")
    con.execute(f"SET threads = {int(os.environ.get('RC_DUCK_THREADS', '4'))}")
    return con


def _log(msg: str):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def build_pack(payer: str, src: str, out: str, nppes: str, irs: list[str], networks: list[bytes] | None = None,
               plans: dict[str, list[str]] | None = None, work: str = "/tmp/packwork") -> dict:
    """`src` holds release tables (a published release, or one reduce wave). `nppes` is the shared
    nppes.parquet (npi, state, zip5...). `plans` maps source file name -> plan names."""
    t0 = time.time()
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(f"{out}/rate", exist_ok=True)
    con = _duck(work)
    res: dict = {"payer": payer}
    W = "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 50000)"

    # networks and network sets
    con.execute(f"CREATE TABLE sf AS SELECT name, network_id, bytes FROM {_src(src, 'source_file')}")
    con.execute(f"CREATE TABLE ns_all AS SELECT DISTINCT ns_id, unnest(network_ids) network_id FROM {_src(src, 'network_set')}")
    if networks:
        con.execute("CREATE TABLE keep_net (network_id BLOB)")
        con.executemany("INSERT INTO keep_net VALUES (?)", [[n] for n in networks])
    else:
        con.execute("CREATE TABLE keep_net AS SELECT DISTINCT network_id FROM sf")
    con.execute("CREATE TABLE ns AS SELECT * FROM ns_all SEMI JOIN keep_net USING (network_id)")
    con.execute(f"COPY (SELECT * FROM ns ORDER BY ns_id) TO '{out}/ns.parquet' {W}")
    con.execute("CREATE TABLE plans (name VARCHAR, plan_name VARCHAR)")
    if plans:
        con.executemany("INSERT INTO plans VALUES (?, ?)", [[n, p] for n, ps in plans.items() for p in ps])
    con.execute(f"""COPY (SELECT ? AS payer, s.network_id, list(DISTINCT s.name ORDER BY s.name) AS file_names,
                         max(s.bytes) AS bytes, list(DISTINCT p.plan_name ORDER BY p.plan_name)
                           FILTER (WHERE p.plan_name IS NOT NULL) AS plan_names
                  FROM sf s SEMI JOIN keep_net USING (network_id) LEFT JOIN plans p USING (name)
                  GROUP BY s.network_id) TO '{out}/network.parquet' {W}""", [payer])
    res["networks"] = con.execute(f"SELECT count(*) FROM '{out}/network.parquet'").fetchone()[0]
    _log(f"networks {res['networks']}")

    # rates: facts x price terms, per fact part, sorted by code
    con.execute(f"CREATE VIEW pl AS SELECT * FROM {_src(src, 'price_list')}")
    n = 0
    con.execute("CREATE TABLE psns (ps_id BLOB, ns_id BLOB)")
    for f in sorted(glob.glob(f"{src}/rate_fact/*.parquet")):
        name = os.path.basename(f)
        con.execute(f"""CREATE OR REPLACE TABLE fx AS SELECT billing_code_type, billing_code, code_id, ps_id, pl_id, ns_id
                        FROM read_parquet('{f}') SEMI JOIN (SELECT DISTINCT ns_id FROM ns) USING (ns_id)""")
        con.execute("INSERT INTO psns SELECT DISTINCT ps_id, ns_id FROM fx")
        con.execute(f"""COPY (SELECT f.billing_code_type, f.billing_code, f.code_id, f.ps_id, f.ns_id, unnest(p.pt_ids) pt_id
                              FROM fx f JOIN (SELECT pl_id, pt_ids FROM pl SEMI JOIN (SELECT DISTINCT pl_id FROM fx) USING (pl_id)) p
                              USING (pl_id)
                              ORDER BY billing_code_type, billing_code, ps_id) TO '{out}/rate/{name}' {W}""")
        k = con.execute(f"SELECT count(*) FROM '{out}/rate/{name}'").fetchone()[0]
        n += k
        _log(f"rate {name}: {k:,}")
    res["rate_rows"] = n
    con.execute("DROP TABLE IF EXISTS fx")
    R = f"read_parquet('{out}/rate/*.parquet')"
    con.execute(f"COPY (SELECT * FROM {_src(src, 'price_term')} SEMI JOIN (SELECT DISTINCT pt_id FROM {R}) USING (pt_id)) "
                f"TO '{out}/price_term.parquet' {W}")
    con.execute(f"COPY (SELECT * FROM {_src(src, 'code')} SEMI JOIN (SELECT DISTINCT code_id FROM {R}) USING (code_id)) "
                f"TO '{out}/code.parquet' {W}")

    # provider sets -> lists -> groups (only what the rates use)
    con.execute(f"CREATE TABLE ps_used AS SELECT DISTINCT ps_id FROM {R}")
    con.execute(f"""CREATE TABLE ps_pli AS SELECT ps_id, unnest(pli_ids) pli_id
                    FROM {_src(src, 'provider_set')} SEMI JOIN ps_used USING (ps_id)""")
    _log(f"ps_pli {con.execute('SELECT count(*) FROM ps_pli').fetchone()[0]:,}")
    con.execute(f"""CREATE TABLE pli_pg AS SELECT DISTINCT pli_id, unnest(pg_ids) pg_id
                    FROM {_src(src, 'provider_list')} SEMI JOIN (SELECT DISTINCT pli_id FROM ps_pli) USING (pli_id)""")
    con.execute(f"COPY (SELECT * FROM pli_pg ORDER BY pli_id) TO '{out}/pli_pg.parquet' {W}")
    # which networks each provider group has any rate in (network breadth, "is X in network Y")
    con.execute("""CREATE TABLE pli_net AS SELECT DISTINCT p.pli_id, n.network_id
                   FROM (SELECT DISTINCT ps_id, ns_id FROM psns) x JOIN ps_pli p USING (ps_id) JOIN ns n USING (ns_id)""")
    con.execute(f"""COPY (SELECT DISTINCT l.pg_id, x.network_id FROM pli_net x JOIN pli_pg l USING (pli_id) ORDER BY 1)
                    TO '{out}/pg_network.parquet' {W}""")
    res["pg_network"] = con.execute(f"SELECT count(*) FROM '{out}/pg_network.parquet'").fetchone()[0]
    con.execute("DROP TABLE pli_net; DROP TABLE psns")
    con.execute(f"""CREATE TABLE pg AS SELECT * FROM {_src(src, 'provider_group')}
                    SEMI JOIN (SELECT DISTINCT pg_id FROM pli_pg) USING (pg_id)""")

    # geography from identifiers: NPI -> NPPES practice state; TIN-wide EIN -> IRS exempt-org state
    con.execute(f"CREATE VIEW nppes AS SELECT npi, state FROM read_parquet('{nppes}')")
    con.execute("""CREATE TABLE pg_npi AS
                   SELECT g.pg_id, x.npi, coalesce(n.state, 'XX') AS state
                   FROM (SELECT pg_id, unnest(npis) npi FROM pg) x JOIN pg g USING (pg_id)
                   LEFT JOIN nppes n USING (npi) WHERE x.npi <> 0""")
    irs_sql = " UNION ALL ".join(f"SELECT ein, state FROM read_parquet('{p}')" for p in irs) if irs else \
        "SELECT NULL::VARCHAR ein, NULL::VARCHAR state WHERE false"
    con.execute(f"""INSERT INTO pg_npi
                    SELECT g.pg_id, NULL, coalesce(e.state, 'XX') FROM pg g
                    LEFT JOIN (SELECT ein, any_value(upper(state)) state FROM ({irs_sql}) GROUP BY ein) e
                      ON e.ein = g.tin_value
                    WHERE g.tin_wide OR len(g.npis) = 0 OR g.npis IS NULL""")
    con.execute("UPDATE pg_npi SET state = 'XX' WHERE state IS NULL OR length(state) <> 2 OR NOT regexp_matches(state, '^[A-Z]{2}$')")
    con.execute(f"COPY (SELECT state, pg_id, npi FROM pg_npi ORDER BY state, pg_id) TO '{out}/pg_npi' "
                f"(FORMAT parquet, COMPRESSION zstd, PARTITION_BY (state), ROW_GROUP_SIZE 50000)")
    con.execute(f"""COPY (SELECT g.pg_id, g.tin_type, g.tin_value, g.npi_count, g.tin_wide, g.business_names,
                                 s.states FROM pg g
                          LEFT JOIN (SELECT pg_id, list(DISTINCT state ORDER BY state) states FROM pg_npi GROUP BY pg_id) s
                          USING (pg_id)) TO '{out}/provider_group.parquet' {W}""")
    con.execute("""CREATE TABLE pli_state AS SELECT DISTINCT l.pli_id, p.state
                   FROM pli_pg l JOIN (SELECT DISTINCT pg_id, state FROM pg_npi) p USING (pg_id)""")
    con.execute(f"""COPY (SELECT s.state, p.ps_id, p.pli_id FROM ps_pli p JOIN pli_state s USING (pli_id)
                          ORDER BY s.state, p.ps_id) TO '{out}/ps_pli'
                    (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (state), ROW_GROUP_SIZE 50000)""")
    for t in ("pg", "ps_pli", "pli_pg", "pg_npi", "pli_state"):
        res[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    con.close()
    res["bytes"] = sum(os.path.getsize(p) for p in glob.glob(f"{out}/**/*.parquet", recursive=True))
    res["seconds"] = round(time.time() - t0, 1)
    json.dump(res, open(f"{out}/pack.json", "w"), indent=1, default=str)
    _log(json.dumps(res, default=str))
    return res


# ---------------------------------------------------------------- shared tables

US_STATES = dict(AL="ALABAMA", AK="ALASKA", AZ="ARIZONA", AR="ARKANSAS", CA="CALIFORNIA", CO="COLORADO",
                 CT="CONNECTICUT", DE="DELAWARE", DC="DISTRICT OF COLUMBIA", FL="FLORIDA", GA="GEORGIA", HI="HAWAII",
                 ID="IDAHO", IL="ILLINOIS", IN="INDIANA", IA="IOWA", KS="KANSAS", KY="KENTUCKY", LA="LOUISIANA",
                 ME="MAINE", MD="MARYLAND", MA="MASSACHUSETTS", MI="MICHIGAN", MN="MINNESOTA", MS="MISSISSIPPI",
                 MO="MISSOURI", MT="MONTANA", NE="NEBRASKA", NV="NEVADA", NH="NEW HAMPSHIRE", NJ="NEW JERSEY",
                 NM="NEW MEXICO", NY="NEW YORK", NC="NORTH CAROLINA", ND="NORTH DAKOTA", OH="OHIO", OK="OKLAHOMA",
                 OR="OREGON", PA="PENNSYLVANIA", RI="RHODE ISLAND", SC="SOUTH CAROLINA", SD="SOUTH DAKOTA",
                 TN="TENNESSEE", TX="TEXAS", UT="UTAH", VT="VERMONT", VA="VIRGINIA", WA="WASHINGTON",
                 WV="WEST VIRGINIA", WI="WISCONSIN", WY="WYOMING", PR="PUERTO RICO", VI="VIRGIN ISLANDS", GU="GUAM",
                 AS="AMERICAN SAMOA", MP="NORTHERN MARIANA ISLANDS")


def build_nppes(src: str, out: str, nucc_csv: str | None = None, work: str = "/tmp/packwork") -> dict:
    """Practice state is normalized to a USPS code (full names mapped; anything else is 'XX')."""
    con = _duck(work)
    con.execute("CREATE TABLE st (code VARCHAR, name VARCHAR)")
    con.executemany("INSERT INTO st VALUES (?, ?)", [[k, v] for k, v in US_STATES.items()] + [[k, k] for k in US_STATES])
    sw = " ".join(f"WHEN healthcare_provider_primary_taxonomy_switch_{i} = 'Y' THEN healthcare_provider_taxonomy_code_{i}"
                  for i in range(1, 16))
    con.execute(f"""CREATE TABLE n AS SELECT
        TRY_CAST(npi AS BIGINT) npi, entity_type_code AS entity_type,
        CASE WHEN entity_type_code = '2' THEN provider_organization_name_legal_business_name
             ELSE trim(concat_ws(' ', provider_first_name, provider_last_name_legal_name)) END AS name,
        provider_credential_text AS credential,
        provider_business_practice_location_address_city_name AS city,
        coalesce((SELECT code FROM st WHERE st.name = upper(trim(provider_business_practice_location_address_state_name))),
                 'XX') AS state,
        left(provider_business_practice_location_address_postal_code, 5) AS zip5,
        coalesce(CASE {sw} END, healthcare_provider_taxonomy_code_1) AS taxonomy_code,
        employer_identification_number_ein AS ein
      FROM read_parquet('{src}') WHERE npi_deactivation_date IS NULL OR npi_reactivation_date IS NOT NULL""")
    if nucc_csv:
        con.execute(f"""CREATE TABLE nucc AS SELECT "Code" AS taxonomy_code,
                        coalesce(nullif("Display Name", ''), concat_ws(' - ', "Classification", nullif("Specialization", ''))) AS taxonomy,
                        "Grouping" AS taxonomy_group, "Classification" AS classification, "Specialization" AS specialization
                        FROM read_csv('{nucc_csv}', header = true, all_varchar = true)""")
    else:
        con.execute("CREATE TABLE nucc (taxonomy_code VARCHAR, taxonomy VARCHAR, taxonomy_group VARCHAR, "
                    "classification VARCHAR, specialization VARCHAR)")
    con.execute(f"""COPY (SELECT n.*, c.taxonomy, c.taxonomy_group, c.classification, c.specialization
                          FROM n LEFT JOIN nucc c USING (taxonomy_code) ORDER BY state, npi)
                    TO '{out}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)""")
    r = con.execute(f"SELECT count(*), count(taxonomy) FROM '{out}'").fetchone()
    return {"rows": r[0], "with_taxonomy": r[1]}


def build_medicare(zip_path: str, out: str, year: str) -> dict:
    """National physician fee schedule amounts: total RVUs x conversion factor (no locality GPCI).
    Descriptors are AMA text, so they are not kept."""
    z = zipfile.ZipFile(zip_path)
    name = next(n for n in z.namelist() if re.search(r"PPRRVU.*\.csv$", n, re.I) and "nonqp" in n.lower()) \
        if any("nonqp" in n.lower() for n in z.namelist()) else \
        next(n for n in z.namelist() if re.search(r"PPRRVU.*\.csv$", n, re.I))
    rows = list(csv.reader(io.TextIOWrapper(z.open(name), encoding="latin-1")))
    data = [r for r in rows if r and re.fullmatch(r"[0-9A-Z]{4}[0-9A-Z]", r[0].strip())]
    # header rows: find the column titles by joining the lines above the first data row
    first = rows.index(data[0])
    heads = [" ".join(h[i].strip() for h in rows[max(0, first - 4):first] if i < len(h)).upper()
             for i in range(max(len(r) for r in rows[first - 4:first + 1]))]

    def col(*keys, avoid=()):
        for i, h in enumerate(heads):
            if all(k in h for k in keys) and not any(a in h for a in avoid):
                return i
        raise KeyError(keys)

    ci = {"mod": col("MOD"), "status": col("STATUS"), "work": col("WORK"),
          "nf_total": col("NON-FAC", "TOTAL"), "f_total": col("FACILITY TOTAL", avoid=("NON",)),
          "cf": col("CONV")}
    out_rows = []
    for r in data:
        def num(k):
            try:
                return float(r[ci[k]])
            except (ValueError, IndexError):
                return None
        cf, nf, f = num("cf"), num("nf_total"), num("f_total")
        out_rows.append({"hcpcs": r[0].strip(), "modifier": r[ci["mod"]].strip() or None,
                         "status": r[ci["status"]].strip(), "nonfacility_rvu": nf, "facility_rvu": f,
                         "conversion_factor": cf,
                         "nonfacility_amount": round(nf * cf, 2) if nf is not None and cf else None,
                         "facility_amount": round(f * cf, 2) if f is not None and cf else None,
                         "year": year, "source_file": name})
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.Table.from_pylist(out_rows), out, compression="zstd")
    s = next((x for x in out_rows if x["hcpcs"] == "99213" and not x["modifier"]), None)
    return {"rows": len(out_rows), "file": name, "columns": ci, "sample_99213": s}
