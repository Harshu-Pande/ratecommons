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
               plans: dict[str, list[str]] | None = None, work: str = "/tmp/packwork",
               states: list[str] | None = None, products: dict | None = None) -> dict:
    """`src` holds release tables (a published release, or one reduce wave). `nppes` is the shared
    nppes.parquet (npi, state, zip5...). `plans` maps source file name -> plan names. `states` limits the
    pack to provider groups practicing in those states (and the rates of their provider sets).
    `products` (network_id -> product label) groups a payer's networks by product: the pack's "networks" are then
    products (network_id = md5 of the label), and ns_net.parquet / network_real.parquet keep every real network
    and its network sets for exact-network questions (Aetna: 6,219 networks, a price in ~300 of them)."""
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
    con.execute("DROP TABLE ns_all")
    con.execute("CREATE TABLE plans (name VARCHAR, plan_name VARCHAR)")
    if plans:
        con.executemany("INSERT INTO plans VALUES (?, ?)", [[n, p] for n, ps in plans.items() for p in ps])
    real = f"""SELECT ? AS payer, s.network_id, list(DISTINCT s.name ORDER BY s.name) AS file_names,
                     max(s.bytes) AS bytes, list(DISTINCT p.plan_name ORDER BY p.plan_name)
                       FILTER (WHERE p.plan_name IS NOT NULL) AS plan_names
              FROM sf s SEMI JOIN keep_net USING (network_id) LEFT JOIN plans p USING (name)
              GROUP BY s.network_id"""
    if products:  # networks grouped by product; every real network kept beside for exact-network questions
        con.execute("CREATE TABLE prodmap (network_id BLOB, product VARCHAR)")
        con.executemany("INSERT INTO prodmap VALUES (?, ?)", [[k, v] for k, v in products.items()])
        con.execute(f"COPY (SELECT * FROM ns ORDER BY network_id, ns_id) TO '{out}/ns_net.parquet' {W}")
        con.execute(f"CREATE TABLE realnet AS SELECT r.*, m.product FROM ({real}) r LEFT JOIN prodmap m USING (network_id)",
                    [payer])
        con.execute(f"COPY (SELECT * FROM realnet ORDER BY product, network_id) TO '{out}/network_real.parquet' {W}")
        con.execute("""CREATE OR REPLACE TABLE ns AS SELECT DISTINCT n.ns_id, unhex(md5(coalesce(m.product, 'other'))) AS network_id
                       FROM ns n LEFT JOIN prodmap m USING (network_id)""")
        # a product row carries its networks' file names and up to 200 plan names (the app labels it from them)
        con.execute(f"""COPY (SELECT ? AS payer, unhex(md5(coalesce(product, 'other'))) AS network_id,
                                     (list(DISTINCT f ORDER BY f) FILTER (WHERE f IS NOT NULL))[1:50] AS file_names, sum(bytes) AS bytes,
                                     (list(DISTINCT q ORDER BY q) FILTER (WHERE q IS NOT NULL))[1:200] AS plan_names,
                                     count(DISTINCT network_id) AS real_networks
                              FROM (SELECT product, network_id, bytes, unnest(file_names) f, unnest(coalesce(plan_names, [NULL])) q
                                    FROM realnet) GROUP BY product)
                        TO '{out}/network.parquet' {W}""", [payer])
        res["real_networks"] = len(products)
    else:
        con.execute(f"COPY ({real}) TO '{out}/network.parquet' {W}", [payer])
    con.execute(f"COPY (SELECT * FROM ns ORDER BY ns_id) TO '{out}/ns.parquet' {W}")
    res["networks"] = con.execute(f"SELECT count(*) FROM '{out}/network.parquet'").fetchone()[0]
    _log(f"networks {res['networks']}")

    con.execute(f"CREATE VIEW nppes AS SELECT npi, state FROM read_parquet('{nppes}')")
    irs_sql = " UNION ALL ".join(f"SELECT ein, state FROM read_parquet('{p}')" for p in irs) if irs else \
        "SELECT NULL::VARCHAR ein, NULL::VARCHAR state WHERE false"
    con.execute(f"CREATE TABLE irs AS SELECT ein, any_value(upper(state)) state FROM ({irs_sql}) GROUP BY ein")
    keep_ps = ""
    if states:
        res["states"] = states
        st = ", ".join(f"'{x}'" for x in states if re.fullmatch(r"[A-Z]{2}", x))
        con.execute(f"""CREATE TABLE geo_pg AS
            SELECT DISTINCT g.pg_id FROM (SELECT pg_id, unnest(npis) npi FROM {_src(src, 'provider_group')}) g
            JOIN nppes n USING (npi) WHERE n.state IN ({st})
            UNION SELECT g.pg_id FROM {_src(src, 'provider_group')} g JOIN irs e ON e.ein = g.tin_value
            WHERE (g.tin_wide OR len(g.npis) = 0) AND e.state IN ({st})""")
        con.execute(f"""CREATE TABLE keep_pli AS SELECT DISTINCT pli_id FROM
            (SELECT pli_id, unnest(pg_ids) pg_id FROM {_src(src, 'provider_list')}) SEMI JOIN geo_pg USING (pg_id)""")
        con.execute(f"""CREATE TABLE ps_pli_k AS SELECT ps_id, pli_id FROM
            (SELECT ps_id, unnest(pli_ids) pli_id FROM {_src(src, 'provider_set')}) SEMI JOIN keep_pli USING (pli_id)""")
        con.execute("CREATE TABLE keep_ps AS SELECT DISTINCT ps_id FROM ps_pli_k")
        keep_ps = "SEMI JOIN keep_ps USING (ps_id)"
        _log(f"states {states}: pg {con.execute('SELECT count(*) FROM geo_pg').fetchone()[0]:,} "
             f"pli {con.execute('SELECT count(*) FROM keep_pli').fetchone()[0]:,} "
             f"ps {con.execute('SELECT count(*) FROM keep_ps').fetchone()[0]:,}")

    # rates: facts x price terms, per fact part, sorted by code
    con.execute(f"CREATE VIEW pl AS SELECT * FROM {_src(src, 'price_list')}")
    n = 0
    con.execute("CREATE TABLE psns (ps_id BLOB, ns_id BLOB)")
    for f in sorted(glob.glob(f"{src}/rate_fact/*.parquet")):
        name = os.path.basename(f)
        con.execute(f"""CREATE OR REPLACE TABLE fx AS SELECT billing_code_type, billing_code, code_id, ps_id, pl_id, ns_id
                        FROM read_parquet('{f}') SEMI JOIN (SELECT DISTINCT ns_id FROM ns) USING (ns_id) {keep_ps}""")
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
    if states:
        con.execute("CREATE TABLE ps_pli AS SELECT * FROM ps_pli_k SEMI JOIN ps_used USING (ps_id)")
        con.execute("DROP TABLE ps_pli_k")
    else:
        con.execute(f"""CREATE TABLE ps_pli AS SELECT ps_id, unnest(pli_ids) pli_id
                        FROM {_src(src, 'provider_set')} SEMI JOIN ps_used USING (ps_id)""")
    _log(f"ps_pli {con.execute('SELECT count(*) FROM ps_pli').fetchone()[0]:,}")
    # no DISTINCT: a provider list's groups are already distinct (it is a content-hashed sorted list), and the
    # DISTINCT over Anthem's wide lists ran a runner out of memory
    con.execute(f"""CREATE TABLE pli_pg AS SELECT pli_id, unnest(pg_ids) pg_id
                    FROM {_src(src, 'provider_list')} SEMI JOIN (SELECT DISTINCT pli_id FROM ps_pli) USING (pli_id)""")
    if states:  # only the groups practicing in the chosen states
        con.execute("DELETE FROM pli_pg WHERE pg_id NOT IN (SELECT pg_id FROM geo_pg)")
    con.execute(f"COPY (SELECT * FROM pli_pg) TO '{out}/pli_pg.parquet' {W}")  # unsorted: sorting Anthem's filled the disk
    # which networks each provider group has any rate in (network breadth, "is X in network Y"): network sets
    # become bitmasks (64 networks per word) OR-ed up ps -> list -> group, so nothing explodes by network
    nn = con.execute("SELECT count(DISTINCT network_id) FROM ns").fetchone()[0]
    words = max(1, (nn + 63) // 64)
    con.execute("CREATE TABLE net_idx AS SELECT network_id, (row_number() OVER (ORDER BY network_id) - 1)::INTEGER idx "
                "FROM (SELECT DISTINCT network_id FROM ns)")
    mw = ", ".join(f"bit_or(CASE WHEN i.idx // 64 = {k} THEN (1::UBIGINT << (i.idx % 64)) ELSE 0::UBIGINT END) m{k}"
                   for k in range(words))
    con.execute(f"CREATE TABLE ns_mask AS SELECT n.ns_id, {mw} FROM ns n JOIN net_idx i USING (network_id) GROUP BY n.ns_id")
    agg = ", ".join(f"bit_or(m{k}) m{k}" for k in range(words))
    con.execute(f"CREATE TABLE ps_mask AS SELECT x.ps_id, {agg} FROM (SELECT DISTINCT ps_id, ns_id FROM psns) x "
                "JOIN ns_mask USING (ns_id) GROUP BY x.ps_id")
    con.execute("DROP TABLE psns")
    con.execute(f"CREATE TABLE pli_mask AS SELECT p.pli_id, {agg} FROM ps_pli p JOIN ps_mask USING (ps_id) GROUP BY p.pli_id")
    con.execute(f"CREATE TABLE pg_mask AS SELECT l.pg_id, {agg} FROM pli_pg l JOIN pli_mask USING (pli_id) GROUP BY l.pg_id")
    con.execute(f"""COPY (SELECT g.pg_id, i.network_id FROM pg_mask g CROSS JOIN net_idx i
                          WHERE (CASE i.idx // 64 {" ".join(f"WHEN {k} THEN g.m{k}" for k in range(words))} END
                                 >> (i.idx % 64)) & 1 = 1 ORDER BY 1)
                    TO '{out}/pg_network.parquet' {W}""")
    res["pg_network"] = con.execute(f"SELECT count(*) FROM '{out}/pg_network.parquet'").fetchone()[0]
    con.execute("DROP TABLE ps_mask; DROP TABLE pli_mask; DROP TABLE pg_mask; DROP TABLE ns_mask")
    con.execute(f"""CREATE TABLE pg AS SELECT * FROM {_src(src, 'provider_group')}
                    SEMI JOIN (SELECT DISTINCT pg_id FROM pli_pg) USING (pg_id)""")

    # geography from identifiers: NPI -> NPPES practice state; TIN-wide EIN -> IRS exempt-org state
    con.execute("""CREATE TABLE pg_npi AS
                   SELECT g.pg_id, x.npi, coalesce(n.state, 'XX') AS state
                   FROM (SELECT pg_id, unnest(npis) npi FROM pg) x JOIN pg g USING (pg_id)
                   LEFT JOIN nppes n USING (npi) WHERE x.npi <> 0""")
    con.execute(f"""INSERT INTO pg_npi
                    SELECT g.pg_id, NULL, coalesce(e.state, 'XX') FROM pg g
                    LEFT JOIN irs e ON e.ein = g.tin_value
                    WHERE g.tin_wide OR len(g.npis) = 0 OR g.npis IS NULL""")
    con.execute("UPDATE pg_npi SET state = 'XX' WHERE state IS NULL OR length(state) <> 2 OR NOT regexp_matches(state, '^[A-Z]{2}$')")
    if states:
        con.execute(f"DELETE FROM pg_npi WHERE state NOT IN ({st})")
    con.execute(f"COPY (SELECT state, pg_id, npi FROM pg_npi ORDER BY state, pg_id) TO '{out}/pg_npi' "
                f"(FORMAT parquet, COMPRESSION zstd, PARTITION_BY (state), ROW_GROUP_SIZE 50000)")
    con.execute(f"""COPY (SELECT g.pg_id, g.tin_type, g.tin_value, g.npi_count, g.tin_wide, g.business_names,
                                 s.states FROM pg g
                          LEFT JOIN (SELECT pg_id, list(DISTINCT state ORDER BY state) states FROM pg_npi GROUP BY pg_id) s
                          USING (pg_id)) TO '{out}/provider_group.parquet' {W}""")
    con.execute("""CREATE TABLE pli_state AS SELECT DISTINCT l.pli_id, p.state
                   FROM pli_pg l JOIN (SELECT DISTINCT pg_id, state FROM pg_npi) p USING (pg_id)""")
    # one state at a time and unsorted: a sorted partitioned write of Aetna's 0.7 billion rows filled the disk
    for (st_,) in con.execute("SELECT DISTINCT state FROM pli_state ORDER BY 1").fetchall():
        os.makedirs(f"{out}/ps_pli/state={st_}", exist_ok=True)
        con.execute(f"""COPY (SELECT p.ps_id, p.pli_id FROM ps_pli p
                              SEMI JOIN (SELECT pli_id FROM pli_state WHERE state = ?) s USING (pli_id))
                        TO '{out}/ps_pli/state={st_}/data_0.parquet' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)""",
                    [st_])
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
    """Physician fee schedule amounts per HCPCS/modifier: national (total RVUs x conversion factor) and per state
    (each component RVU x the state's mean locality GPCI). Descriptors are AMA text, so they are not kept.
    Columns of PPRRVU (fixed by CMS): 0 HCPCS, 1 MOD, 3 STATUS, 5 WORK, 6 NF PE, 8 F PE, 10 MP, 11 NF TOTAL,
    12 F TOTAL, 25 CONV FACTOR."""
    z = zipfile.ZipFile(zip_path)
    names = z.namelist()
    name = next((n for n in names if re.search(r"PPRRVU.*nonQP.*\.csv$", n, re.I)), None) or \
        next(n for n in names if re.search(r"PPRRVU.*\.csv$", n, re.I))
    rows = list(csv.reader(io.TextIOWrapper(z.open(name), encoding="latin-1")))
    hdr = next(i for i, r in enumerate(rows) if r and r[0].strip() == "HCPCS")
    assert rows[hdr][1].strip() == "MOD" and "FACTOR" in rows[hdr][25].upper(), rows[hdr][:30]

    def f(x):
        try:
            return float(x)
        except ValueError:
            return None
    gname = next(n for n in names if re.search(r"GPCI.*\.csv$", n, re.I))
    grows = list(csv.reader(io.TextIOWrapper(z.open(gname), encoding="latin-1")))
    gh = next(i for i, r in enumerate(grows) if any("PW GPCI" in c for c in r))
    loc: dict[str, list] = {}
    for r in grows[gh + 1:]:
        if len(r) >= 7 and re.fullmatch(r"[A-Z]{2}", r[1].strip()) and f(r[4]) is not None:
            loc.setdefault(r[1].strip(), []).append((f(r[4]), f(r[5]), f(r[6])))
    gpci = {st: tuple(sum(x[i] for x in v) / len(v) for i in range(3)) for st, v in loc.items()}
    gpci["US"] = (1.0, 1.0, 1.0)
    out_rows = []
    for r in rows[hdr + 1:]:
        if len(r) < 26 or not re.fullmatch(r"[0-9A-Z]{5}", r[0].strip()):
            continue
        w, nfpe, fpe, mp, cf = f(r[5]), f(r[6]), f(r[8]), f(r[10]), f(r[25])
        if cf is None or w is None:
            continue
        for st, (gw, gpe, gmp) in gpci.items():
            nf = (w * gw + (nfpe or 0) * gpe + (mp or 0) * gmp) * cf
            fa = (w * gw + (fpe or 0) * gpe + (mp or 0) * gmp) * cf
            out_rows.append({"hcpcs": r[0].strip(), "modifier": r[1].strip() or None, "status": r[3].strip(),
                             "state": st, "nonfacility_amount": round(nf, 2), "facility_amount": round(fa, 2),
                             "conversion_factor": cf, "year": year})
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.Table.from_pylist(out_rows), out, compression="zstd")
    s = [x for x in out_rows if x["hcpcs"] == "99213" and not x["modifier"] and x["state"] in ("US", "TX", "NY")]
    return {"rows": len(out_rows), "file": name, "gpci_file": gname, "states": len(gpci), "sample_99213": s}
