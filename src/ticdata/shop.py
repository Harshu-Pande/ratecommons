"""CareCompass shop data: patient-facing, precleaned prices per procedure and place.

Stage 1, `sources()`: reference tables the cleaning needs, written to the work bucket under shop/sources/:

  addr.parquet       every practice address of every NPI (NPPES primary + secondary locations, Doctors and
                     Clinicians), with a place key (normalized street without suite + ZIP5)
  clin.parquet       NPI -> entity type, name, credential, all taxonomy codes, primary taxonomy + NUCC names
  medicare.parquet   Medicare Physician & Other Practitioners by Provider and Service (latest year): which NPI
                     billed which HCPCS, how often, place (F/O), average submitted charge. No descriptor text.
  affil.parquet      clinician -> facility (CCN) affiliations (Doctors and Clinicians facility affiliation)
  hospitals.parquet  CCN -> hospital name, address, type, emergency services
  zip.parquet        ZIP5 -> latitude/longitude (Census ZCTA gazetteer)

Stage 2, `build_state()` (see below): cleaned offers per procedure and place.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import time
import zipfile

from .serving import _duck, _log

MEDICARE_PS = "https://data.cms.gov/sites/default/files/2026-05/b5ebab5a-f490-418a-9bce-4b9f31419356/PHY_R26_P05_V10_D24_Prov_Svc.csv"
AFFIL = "https://data.cms.gov/provider-data/sites/default/files/resources/b7c4080ae144663e43353a9c35cd3f53_1790972135/Facility_Affiliation.csv"
HOSPITALS = "https://data.cms.gov/provider-data/sites/default/files/resources/893c372430d9d71a1c52737d01239d47_1785189955/Hospital_General_Information.csv"
ZCTA = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip"
IDENTITY = "ratecommons/identity"
W = "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)"

STREET_WORDS = {"STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "ROAD": "RD", "DRIVE": "DR", "LANE": "LN",
                "PARKWAY": "PKWY", "HIGHWAY": "HWY", "COURT": "CT", "CIRCLE": "CIR", "PLACE": "PL", "SQUARE": "SQ",
                "TERRACE": "TER", "TRAIL": "TRL", "CENTER": "CTR", "PLAZA": "PLZ", "NORTH": "N", "SOUTH": "S",
                "EAST": "E", "WEST": "W", "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
                "FREEWAY": "FWY", "EXPRESSWAY": "EXPY", "MOUNT": "MT", "SAINT": "ST", "FORT": "FT"}


def place_key_sql(line: str, zip5: str) -> str:
    """SQL for a place key: upper-case street line, punctuation removed, suite/floor/room dropped, common street
    words abbreviated, spaces collapsed, then '|' ZIP5. Two clinicians at one building share a key."""
    x = f"upper(coalesce({line}, ''))"
    x = f"regexp_replace({x}, '\\s*#.*$', '')"  # "#200" and anything after it is a unit
    x = f"regexp_replace({x}, '\\s\\d+(ST|ND|RD|TH)\\s+(FL|FLOOR|FLR)\\b.*$', '')"  # "5th floor"
    x = f"regexp_replace({x}, '[.,'']', ' ', 'g')"
    x = (f"regexp_replace({x}, '\\s(STE|SUITE|UNIT|APT|BLDG|BUILDING|FL|FLOOR|RM|ROOM|DEPT|SPC|LOWR|UPPR|LBBY|LOBBY)"
         f"(\\s.*)?$', '')")
    for k, v in STREET_WORDS.items():
        x = f"regexp_replace({x}, '\\b{k}\\b', '{v}', 'g')"
    x = f"trim(regexp_replace({x}, '\\s+', ' ', 'g'))"
    return f"({x} || '|' || left(coalesce({zip5}, ''), 5))"


def _download(url: str, path: str, tries: int = 4) -> str:
    import requests

    for i in range(tries):
        try:
            with requests.get(url, stream=True, timeout=600) as r:  # data.cms.gov answers 403 to a browser-like UA
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(8 << 20):
                        f.write(chunk)
            return path
        except Exception as e:
            _log(f"download retry {i}: {url}: {e!r}")
            time.sleep(20 * (i + 1))
    raise RuntimeError(f"could not download {url}")


def sources(work: str = "/tmp/shop-src", upload_to: str | None = "ratecommons/work", prefix: str = "shop/sources",
            cms: bool = True) -> dict:
    from huggingface_hub import hf_hub_download

    t0 = time.time()
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(f"{work}/out")
    con = _duck(f"{work}/duck")
    res: dict = {}

    # ZIP centroids
    z = _download(ZCTA, f"{work}/zcta.zip")
    with zipfile.ZipFile(z) as zf:
        name = [n for n in zf.namelist() if n.endswith(".txt")][0]
        zf.extract(name, work)
    zc = con.execute(f"SELECT * FROM read_csv('{work}/{name}', delim = '\\t', header = true, all_varchar = true) LIMIT 0")
    cols = [d[0] for d in zc.description]
    lat = next(c for c in cols if c.strip().upper() == "INTPTLAT")
    lon = next(c for c in cols if c.strip().upper().startswith("INTPTLONG"))
    con.execute(f"""COPY (SELECT trim("GEOID") AS zip5, TRY_CAST(trim("{lat}") AS DOUBLE) AS lat,
                                 TRY_CAST(trim("{lon}") AS DOUBLE) AS lon
                          FROM read_csv('{work}/{name}', delim = '\\t', header = true, all_varchar = true))
                    TO '{work}/out/zip.parquet' {W}""")
    res["zips"] = con.execute(f"SELECT count(*) FROM '{work}/out/zip.parquet'").fetchone()[0]
    _log(json.dumps(res))

    if cms:
        # hospitals and affiliations
        _download(HOSPITALS, f"{work}/hosp.csv")
        con.execute(f"""COPY (SELECT "Facility ID" AS ccn, "Facility Name" AS name, "Address" AS line1, "City/Town" AS city,
                                     "State" AS state, left("ZIP Code", 5) AS zip5, "Telephone Number" AS phone,
                                     "Hospital Type" AS hospital_type, "Emergency Services" AS emergency,
                                     {place_key_sql('"Address"', '"ZIP Code"')} AS place_key
                              FROM read_csv('{work}/hosp.csv', header = true, all_varchar = true))
                        TO '{work}/out/hospitals.parquet' {W}""")
        res["hospitals"] = con.execute(f"SELECT count(*) FROM '{work}/out/hospitals.parquet'").fetchone()[0]
        _download(AFFIL, f"{work}/affil.csv")
        con.execute(f"""COPY (SELECT DISTINCT TRY_CAST("NPI" AS BIGINT) AS npi, facility_type,
                                     "Facility Affiliations Certification Number" AS ccn
                              FROM read_csv('{work}/affil.csv', header = true, all_varchar = true))
                        TO '{work}/out/affil.parquet' {W}""")
        res["affiliations"] = con.execute(f"SELECT count(*) FROM '{work}/out/affil.parquet'").fetchone()[0]
        os.remove(f"{work}/affil.csv")
        _log(json.dumps(res))

        # Medicare provider x service (codes and counts only; CMS's HCPCS text is AMA's and is not kept)
        _download(MEDICARE_PS, f"{work}/mps.csv")
        con.execute(f"""COPY (SELECT TRY_CAST(Rndrng_NPI AS BIGINT) AS npi, Rndrng_Prvdr_Ent_Cd AS entity,
                                     Rndrng_Prvdr_Type AS provider_type, Rndrng_Prvdr_State_Abrvtn AS state,
                                     Rndrng_Prvdr_Zip5 AS zip5, HCPCS_Cd AS hcpcs, Place_Of_Srvc AS pos,
                                     TRY_CAST(Tot_Benes AS INTEGER) AS benes, TRY_CAST(Tot_Srvcs AS DOUBLE) AS services,
                                     TRY_CAST(Avg_Sbmtd_Chrg AS DOUBLE) AS avg_charge,
                                     TRY_CAST(Avg_Mdcr_Alowd_Amt AS DOUBLE) AS avg_allowed
                              FROM read_csv('{work}/mps.csv', header = true, all_varchar = true, quote = '"')
                              ORDER BY hcpcs, npi)
                        TO '{work}/out/medicare.parquet' {W}""")
        res["medicare_rows"] = con.execute(f"SELECT count(*) FROM '{work}/out/medicare.parquet'").fetchone()[0]
        os.remove(f"{work}/mps.csv")
        _log(json.dumps(res))

    # clinicians and addresses from NPPES + Doctors and Clinicians
    npi = hf_hub_download(IDENTITY, "nppes/release=2026-10/npi.parquet", repo_type="dataset", local_dir=work)
    pl = hf_hub_download(IDENTITY, "nppes/release=2026-10/practice_locations.parquet", repo_type="dataset", local_dir=work)
    dac = hf_hub_download(IDENTITY, "dac/release=2026-10/dac_nationaldownloadablefile.parquet", repo_type="dataset",
                          local_dir=work)
    lite = hf_hub_download(IDENTITY, "serving/nppes.parquet", repo_type="dataset", local_dir=work)
    from .serving import US_STATES

    con.execute("CREATE TABLE st (code VARCHAR, name VARCHAR)")
    con.executemany("INSERT INTO st VALUES (?, ?)", [[k, v] for k, v in US_STATES.items()] + [[k, k] for k in US_STATES])
    taxes = ", ".join(f"healthcare_provider_taxonomy_code_{i}" for i in range(1, 16))
    con.execute(f"""COPY (
        SELECT n.npi, n.entity_type, n.name, n.credential, n.taxonomy_code, n.taxonomy, n.classification,
               n.specialization, n.ein,
               list_filter([{taxes}], x -> x IS NOT NULL AND x <> '') AS taxonomies,
               r.provider_other_organization_name AS other_name
        FROM read_parquet('{lite}') n
        LEFT JOIN (SELECT TRY_CAST(npi AS BIGINT) AS npi, {taxes}, provider_other_organization_name
                   FROM read_parquet('{npi}')) r USING (npi))
        TO '{work}/out/clin.parquet' {W}""")
    res["clinicians"] = con.execute(f"SELECT count(*) FROM '{work}/out/clin.parquet'").fetchone()[0]
    stc = "coalesce((SELECT code FROM st WHERE st.name = upper(trim({}))), 'XX')"
    con.execute(f"""COPY (
        WITH a AS (
          SELECT TRY_CAST(npi AS BIGINT) AS npi, provider_first_line_business_practice_location_address AS line1,
                 provider_business_practice_location_address_city_name AS city,
                 {stc.format('provider_business_practice_location_address_state_name')} AS state,
                 left(provider_business_practice_location_address_postal_code, 5) AS zip5,
                 provider_business_practice_location_address_telephone_number AS phone, 'nppes' AS src
          FROM read_parquet('{npi}') WHERE npi_deactivation_date IS NULL OR npi_reactivation_date IS NOT NULL
          UNION ALL
          SELECT TRY_CAST(npi AS BIGINT), provider_secondary_practice_location_address_address_line_1,
                 provider_secondary_practice_location_address_city_name,
                 {stc.format('provider_secondary_practice_location_address_state_name')},
                 left(provider_secondary_practice_location_address_postal_code, 5),
                 provider_secondary_practice_location_address_telephone_number, 'nppes2'
          FROM read_parquet('{pl}')
          UNION ALL
          SELECT TRY_CAST(npi AS BIGINT), adr_ln_1, city_town, {stc.format('state')}, left(zip_code, 5),
                 telephone_number, 'dac'
          FROM read_parquet('{dac}'))
        SELECT npi, any_value(line1) AS line1, any_value(city) AS city, any_value(state) AS state, zip5,
               any_value(phone) AS phone, list(DISTINCT src) AS srcs, place_key
        FROM (SELECT *, {place_key_sql('line1', 'zip5')} AS place_key FROM a WHERE npi IS NOT NULL AND zip5 IS NOT NULL)
        GROUP BY npi, place_key, zip5 ORDER BY state, place_key)
        TO '{work}/out/addr.parquet' {W}""")
    res["addresses"] = con.execute(f"SELECT count(*), count(DISTINCT place_key) FROM '{work}/out/addr.parquet'").fetchone()
    # DAC group names per address (facility_name = the clinician's group practice at that address)
    con.execute(f"""COPY (SELECT DISTINCT TRY_CAST(npi AS BIGINT) AS npi, facility_name AS group_name, org_pac_id,
                                 {place_key_sql('adr_ln_1', 'zip_code')} AS place_key, pri_spec
                          FROM read_parquet('{dac}') WHERE facility_name IS NOT NULL AND facility_name <> '')
                    TO '{work}/out/dac_groups.parquet' {W}""")
    for f in (npi, pl, dac, lite):
        os.remove(f)
    res["seconds"] = round(time.time() - t0)
    _log(json.dumps(res, default=str))
    if upload_to:
        from .cloudpack import upload

        res["uploaded"] = upload(f"{work}/out", prefix, upload_to)
    return res


# ---------------------------------------------------------------------------------------------------------------
# Stage 2: cleaned offers per procedure and place

CLOUD = "https://huggingface.co/buckets/ratecommons/work/resolve/serve/v2"
SRC = "https://huggingface.co/buckets/ratecommons/work/resolve/shop/sources"
ONAMES = "https://huggingface.co/datasets/ratecommons/identity/resolve/main/nppes/release=2026-10/other_names.parquet"
PAYERS = ["cigna", "aetna", "uhc"]
STATES = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
          "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
          "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR"]
FACILITY_POS = ("19", "21", "22", "23", "24", "26", "31", "34", "41", "42", "51", "52", "53", "56", "61")
PLACEHOLDER = "(rate <= 0.01 OR rate >= 99999 OR rate_raw LIKE '9999%')"


def _fetch(url: str, dest: str) -> str | None:
    import requests

    if os.path.exists(dest):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for i in range(4):
        try:
            with requests.get(url, stream=True, timeout=300) as r:
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                tmp = dest + ".part"
                with open(tmp, "wb") as f:
                    for c in r.iter_content(4 << 20):
                        f.write(c)
                os.replace(tmp, dest)
                return dest
        except Exception as e:
            _log(f"fetch retry {i}: {url}: {e!r}")
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"could not fetch {url}")


def _fetch_many(pairs: list[tuple[str, str]], threads: int = 16) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(threads) as ex:
        return dict(zip([d for _, d in pairs], ex.map(lambda p: _fetch(*p), pairs)))


def _code_key(code: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9._-]", "_", (code or "").strip())[:80] or "_"


def _products(payer: str, meta: dict) -> tuple[list[str], dict]:
    """Friendly product names per payer (sorted) and net -> product index."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("rcapi", os.path.join(os.path.dirname(__file__), "..", "..",
                                                                         "cloud", "api", "_rc.py"))
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    lab = {n["net"]: rc._label(payer, n.get("file_names") or [], n.get("plan_names") or [])[0] for n in meta["networks"]}
    names = sorted(set(lab.values()))
    idx = {p: i for i, p in enumerate(names)}
    return names, {net: idx[p] for net, p in lab.items()}


def _setup(con, work: str) -> dict:
    """Tables shared by every state: catalog, taxonomy groups, clinicians' groups, Medicare PFS."""
    from .shopcatalog import TAX, catalog

    cat = catalog()
    rows = []
    for p in cat:
        roles = p["who"]
        for code in p["codes"] + p.get("alt", []) + p.get("addon", []):
            for role, grps in roles.items():
                for g in grps:
                    rows.append((p["id"], p["kind"], code, role, g, code in p.get("addon", [])))
    con.execute("CREATE TABLE cat (proc VARCHAR, kind VARCHAR, code VARCHAR, role VARCHAR, grp VARCHAR, addon BOOLEAN)")
    con.executemany("INSERT INTO cat VALUES (?, ?, ?, ?, ?, ?)", rows)
    con.execute("CREATE TABLE taxgrp (grp VARCHAR, prefix VARCHAR, n INTEGER)")
    con.executemany("INSERT INTO taxgrp VALUES (?, ?, ?)", [(g, x, len(x)) for g, xs in TAX.items() for x in xs])
    src = {f: f"{work}/src/{f}.parquet" for f in ("addr", "clin", "medicare", "affil", "hospitals", "zip", "dac_groups")}
    _fetch_many([(f"{SRC}/{f}.parquet", d) for f, d in src.items()], 4)
    _fetch(f"{CLOUD}/shared/medicare.parquet", f"{work}/src/pfs.parquet")
    lens = [r[0] for r in con.execute("SELECT DISTINCT n FROM taxgrp").fetchall()]
    union = " UNION ALL ".join(f"""SELECT c.npi, g.grp FROM (SELECT npi, unnest(taxonomies) AS tax FROM read_parquet('{src["clin"]}')) c
                                   JOIN taxgrp g ON g.n = {n} AND left(c.tax, {n}) = g.prefix""" for n in lens)
    con.execute(f"CREATE TABLE npigrp AS SELECT DISTINCT * FROM ({union})")
    codes = sorted({r[2] for r in rows})
    con.execute(f"""CREATE TABLE ev AS SELECT npi, hcpcs, sum(services) AS services, max(avg_charge) AS avg_charge
                    FROM read_parquet('{src["medicare"]}') WHERE hcpcs IN ({", ".join(f"'{c}'" for c in codes)})
                    GROUP BY 1, 2""")
    # family evidence: the clinician bills a closely related code (same first 4 characters), e.g. 70450 ~ 70460
    con.execute(f"""CREATE TABLE evfam AS SELECT DISTINCT npi, left(hcpcs, 4) AS fam FROM read_parquet('{src["medicare"]}')
                    WHERE left(hcpcs, 4) IN ({", ".join(f"'{c[:4]}'" for c in codes)})""")
    con.execute(f"CREATE TABLE pfs AS SELECT hcpcs, coalesce(modifier, '') AS m, state, nonfacility_amount AS nf, "
                f"facility_amount AS fa FROM read_parquet('{work}/src/pfs.parquet')")
    con.execute(f"CREATE TABLE zipc AS SELECT * FROM read_parquet('{src['zip']}')")
    # NPPES "other names": type 3 = doing business as; the newest one per NPI
    on = _fetch(ONAMES, f"{work}/src/other_names.parquet")
    con.execute(f"""CREATE TABLE dba AS SELECT TRY_CAST(npi AS BIGINT) AS npi,
                        arg_max(provider_other_organization_name, strptime(created_date, '%m/%d/%Y')) AS dba
                    FROM read_parquet('{on}') WHERE provider_other_organization_name_type_code = '3'
                         AND provider_other_organization_name NOT IN ('', '<UNAVAIL>') GROUP BY 1""")
    return {"cat": cat, "codes": codes, "src": src}


def _payer_files(payer: str, codes: list[str], states: list[str], work: str) -> dict:
    meta = json.load(open(_fetch(f"{CLOUD}/{payer}/meta.json", f"{work}/{payer}/meta.json")))
    _fetch(f"{CLOUD}/{payer}/ns.parquet", f"{work}/{payer}/ns.parquet")
    _fetch(f"{CLOUD}/{payer}/codes.parquet", f"{work}/{payer}/codes.parquet")
    import duckdb

    idx = duckdb.connect().execute(f"SELECT DISTINCT t, k, billing_code FROM read_parquet('{work}/{payer}/codes.parquet') "
                                   f"WHERE billing_code IN ({', '.join(repr(c) for c in codes)})").fetchall()
    pairs = [(f"{CLOUD}/{payer}/code/{t}/{k}.parquet", f"{work}/{payer}/code/{t}/{k}.parquet") for t, k, _ in idx]
    pairs.append((f"{CLOUD}/{payer}/cstm_all.parquet", f"{work}/{payer}/cstm_all.parquet"))
    got = _fetch_many(pairs)
    buckets = sorted({(t, k[:3]) for t, k, _ in idx})
    st = []
    for s in states:
        for f in ("pg", "pgnpi", "plipg"):
            st.append((f"{CLOUD}/{payer}/state/{s}/{f}.parquet", f"{work}/{payer}/state/{s}/{f}.parquet"))
        for t, b in buckets:
            st.append((f"{CLOUD}/{payer}/state/{s}/pspli/{t}/{b}.parquet", f"{work}/{payer}/state/{s}/pspli/{t}/{b}.parquet"))
        st.append((f"{CLOUD}/{payer}/state/{s}/pspli/_cstm_all.parquet", f"{work}/{payer}/state/{s}/pspli/_cstm_all.parquet"))
    got.update(_fetch_many(st))
    return {"meta": meta, "code_files": [d for d in got if "/code/" in d and got[d]], "got": got}


def build(states: list[str], work: str = "/tmp/shop", out: str = "/tmp/shop-out", upload_to: str | None = "ratecommons/work",
          prefix: str = "shop/v1") -> dict:
    """Cleaned offers for the given states, written as offers/<proc>/<zip3>.json (+ summaries)."""
    t0 = time.time()
    os.makedirs(work, exist_ok=True)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    con = _duck(f"{work}/duck")
    env = _setup(con, work)
    res: dict = {"states": {}, "products": {}}
    pf = {}
    for p in PAYERS:
        pf[p] = _payer_files(p, env["codes"], states, work)
        names, netmap = _products(p, pf[p]["meta"])
        res["products"][p] = names
        con.execute(f"CREATE OR REPLACE TABLE prod_{p} AS SELECT DISTINCT n.ns, x.prod FROM read_parquet('{work}/{p}/ns.parquet') n "
                    f"JOIN (SELECT unnest(?) AS net, unnest(?) AS prod) x USING (net)",
                    [list(netmap.keys()), list(netmap.values())])
        cf = pf[p]["code_files"]
        con.execute(f"""CREATE OR REPLACE TABLE rates_{p} AS
            SELECT code, ps, ns, negotiated_type AS ntype, round(rate, 2) AS rate, rate_raw, billing_class AS bclass,
                   coalesce(modifiers, '') AS mods, coalesce(pos, '') AS pos, expiration
            FROM read_parquet({cf!r}, union_by_name = true)
            WHERE NOT {PLACEHOLDER} AND (expiration IS NULL OR expiration = '' OR expiration >= strftime(current_date, '%Y-%m-%d'))""")
        flat = f"{work}/{p}/cstm_all.parquet"
        if os.path.exists(flat):
            con.execute(f"""CREATE OR REPLACE TABLE flat_{p} AS
                SELECT code, ps, ns, negotiated_type AS ntype, round(rate, 2) AS rate, rate_raw, billing_class AS bclass
                FROM read_parquet('{flat}') WHERE NOT {PLACEHOLDER} AND negotiated_type IN ('per diem', 'negotiated', 'fee schedule', 'derived')""")
        else:
            con.execute(f"CREATE OR REPLACE TABLE flat_{p} AS SELECT NULL::VARCHAR code, NULL::INTEGER ps, NULL::INTEGER ns, "
                        f"NULL::VARCHAR ntype, NULL::DOUBLE rate, NULL::VARCHAR rate_raw, NULL::VARCHAR bclass WHERE false")
        res[f"rates_{p}"] = con.execute(f"SELECT count(*) FROM rates_{p}").fetchone()[0]
    _log(json.dumps({k: v for k, v in res.items() if k.startswith("rates")}))
    for s in states:
        try:
            res["states"][s] = _build_state(con, s, env, pf, work, out, res["products"])
        except Exception as e:
            import traceback

            traceback.print_exc()
            res["states"][s] = {"error": repr(e)[:400]}
        _log(json.dumps({s: res["states"][s]}, default=str))
        for p in PAYERS:  # state files are no longer needed
            shutil.rmtree(f"{work}/{p}/state/{s}", ignore_errors=True)
    json.dump({"products": res["products"]}, open(f"{out}/products-{'-'.join(states)}.json", "w"))
    res["seconds"] = round(time.time() - t0)
    if upload_to:
        from .cloudpack import upload

        res["uploaded"] = upload(out, prefix, upload_to)
    return res


def _build_state(con, s: str, env: dict, pf: dict, work: str, out: str, products: dict) -> dict:
    t0 = time.time()
    src = env["src"]
    con.execute(f"""CREATE OR REPLACE TABLE addr_s AS SELECT npi, place_key, line1, city, state, zip5, phone
                    FROM read_parquet('{src["addr"]}') WHERE state = '{s}'""")
    con.execute(f"""CREATE OR REPLACE TABLE clin_s AS SELECT npi, entity_type, name, credential, taxonomy_code, classification,
                           other_name FROM read_parquet('{src["clin"]}') WHERE npi IN (SELECT npi FROM addr_s)""")
    con.execute("CREATE OR REPLACE TABLE rolemap AS SELECT DISTINCT proc, kind, code, role, addon FROM cat")
    con.execute("CREATE OR REPLACE TABLE catg AS SELECT DISTINCT proc, code, role, grp FROM cat")
    po_parts, team_parts = [], []
    for p in PAYERS:
        d = f"{work}/{p}/state/{s}"
        if not os.path.exists(f"{d}/pgnpi.parquet"):
            continue
        buckets = [b for b in glob.glob(f"{d}/pspli/*/*.parquet")]
        if not buckets:
            continue
        con.execute(f"""CREATE OR REPLACE TABLE psg AS SELECT DISTINCT b.ps, l.pg FROM read_parquet({buckets!r}) b
                        JOIN read_parquet('{d}/plipg.parquet') l USING (pli)""")
        con.execute(f"""CREATE OR REPLACE TABLE og AS
            SELECT g.pg, r.code, r.ntype, r.rate, r.bclass, r.mods,
                   (r.pos = '' OR list_contains(string_split(r.pos, ','), '11') OR r.pos LIKE 'CSTM%') AS office,
                   list(DISTINCT pr.prod ORDER BY pr.prod) AS prods
            FROM rates_{p} r JOIN psg g USING (ps) JOIN prod_{p} pr USING (ns)
            GROUP BY ALL""")
        flatb = f"{d}/pspli/_cstm_all.parquet"
        if os.path.exists(flatb):  # flat all-services arrangements (e.g. one amount per urgent-care visit)
            con.execute(f"""INSERT INTO og SELECT l.pg, 'FLAT' AS code, f.ntype, f.rate, f.bclass, '' AS mods, true AS office,
                                   list(DISTINCT pr.prod ORDER BY pr.prod) AS prods
                            FROM flat_{p} f JOIN read_parquet('{flatb}') b USING (ps)
                            JOIN read_parquet('{d}/plipg.parquet') l USING (pli) JOIN prod_{p} pr USING (ns)
                            GROUP BY ALL""")
        con.execute(f"""CREATE OR REPLACE TABLE ogr AS
            SELECT og.*, m.proc, m.role, m.addon FROM og JOIN rolemap m ON m.code = og.code AND (
                   (m.kind = 'imaging' AND ((m.role = 'global' AND og.mods = '') OR (m.role = 'pro' AND og.mods = '26')
                                           OR (m.role = 'tc' AND og.mods = 'TC')))
                   OR (m.kind <> 'imaging' AND m.role = 'any' AND og.mods = ''))
            UNION ALL
            SELECT og.*, m.proc, m.role, false AS addon FROM og
            JOIN (SELECT DISTINCT proc, role FROM rolemap WHERE kind = 'visit' AND role = 'any' AND NOT addon) m ON og.code = 'FLAT'""")
        # groups' clinicians in this state, at their practice addresses
        con.execute(f"""CREATE OR REPLACE TABLE gp AS SELECT DISTINCT n.pg, n.npi, a.place_key
                        FROM read_parquet('{d}/pgnpi.parquet') n JOIN addr_s a USING (npi)
                        WHERE n.pg IN (SELECT DISTINCT pg FROM ogr)""")
        # qualified clinicians per group, place, procedure part; with Medicare evidence for the code (or its family)
        con.execute("""CREATE OR REPLACE TABLE q AS
            SELECT gp.pg, gp.place_key, c.proc, c.role, c.code, count(DISTINCT gp.npi) AS nq,
                   count(DISTINCT gp.npi) FILTER (WHERE ev.npi IS NOT NULL OR ef.npi IS NOT NULL) AS nev
            FROM gp JOIN npigrp g USING (npi) JOIN catg c ON c.grp = g.grp
            LEFT JOIN ev ON ev.npi = gp.npi AND ev.hcpcs = c.code
            LEFT JOIN evfam ef ON ef.npi = gp.npi AND ef.fam = left(c.code, 4)
            GROUP BY ALL""")
        # a flat all-services contract applies to the visit whatever its code: match it to the group's best code
        con.execute("""CREATE OR REPLACE TABLE qx AS SELECT * FROM q UNION ALL
                       SELECT pg, place_key, proc, role, 'FLAT' AS code, max(nq), max(nev) FROM q GROUP BY ALL""")
        con.execute(f"""CREATE OR REPLACE TABLE pgs AS SELECT pg, tin,
                               coalesce(business_names[1], name) AS gname FROM read_parquet('{d}/pg.parquet')""")
        po_parts.append(f"po_{p}")
        con.execute("CREATE TABLE IF NOT EXISTS tn (tin VARCHAR, gname VARCHAR)")
        con.execute("INSERT INTO tn SELECT tin, mode(gname) FROM pgs WHERE tin NOT IN (SELECT tin FROM tn) GROUP BY tin")
        # price sanity per row: Medicare PFS for the state (office = non-facility amount), else this payer's own spread
        con.execute(f"""CREATE OR REPLACE TABLE chk AS
            WITH d AS (SELECT proc, role, code, quantile_cont(rate, 0.02) AS p02, quantile_cont(rate, 0.98) AS p98
                       FROM ogr WHERE ntype IN ('negotiated', 'fee schedule', 'derived') GROUP BY ALL)
            SELECT DISTINCT o.proc, o.role, o.code, o.office, m.mcr, d.p02, d.p98 FROM (SELECT DISTINCT proc, role, code, office FROM ogr) o
            LEFT JOIN (SELECT hcpcs, m, nf, coalesce(fa, nf) AS fa FROM pfs WHERE state = '{s}') m0
                   ON m0.hcpcs = o.code AND m0.m = CASE WHEN o.role = 'pro' THEN '26' WHEN o.role = 'tc' THEN 'TC' ELSE '' END
            CROSS JOIN LATERAL (SELECT CASE WHEN o.office THEN m0.nf ELSE m0.fa END AS mcr) m
            LEFT JOIN d USING (proc, role, code)""")
        # one procedure at a time (the place x contract join is tens of millions of rows for a big state), then
        # collapsed: a hospital campus can carry 2,000 provider groups with 2,500 distinct rates for one visit code
        procs = [r[0] for r in con.execute("SELECT DISTINCT proc FROM ogr ORDER BY 1").fetchall()]
        for k, proc in enumerate(procs):
            con.execute(f"""{'CREATE OR REPLACE TABLE po_' + p + ' AS' if k == 0 else 'INSERT INTO po_' + p}
                WITH x AS (
                    SELECT q.place_key, o.proc, o.role, o.code, o.ntype, o.rate, o.bclass, o.office, o.prods, g.tin, g.gname,
                           q.nq, q.nev,
                           CASE WHEN o.ntype NOT IN ('negotiated', 'fee schedule', 'derived', 'per diem') THEN 'x'
                                WHEN c.mcr > 0 AND (o.rate < 0.15 * c.mcr OR o.rate > 15 * c.mcr) THEN 'h'
                                WHEN (c.mcr IS NULL OR c.mcr <= 0) AND o.code <> 'FLAT' AND c.p98 IS NOT NULL
                                     AND (o.rate < c.p02 / 3 OR o.rate > c.p98 * 3) THEN 'h'
                                WHEN q.nev > 0 THEN 'c' ELSE 'l' END AS badge
                    FROM (SELECT * FROM ogr WHERE proc = $proc) o
                    JOIN (SELECT * FROM qx WHERE proc = $proc) q ON q.pg = o.pg AND q.role = o.role AND q.code = o.code
                    JOIN pgs g ON g.pg = o.pg
                    LEFT JOIN chk c ON c.proc = o.proc AND c.role = o.role AND c.code = o.code AND c.office = o.office)
                SELECT place_key, '{p}' AS payer, proc, role, code, ntype, median(rate) AS rate, min(rate) AS lo, max(rate) AS hi,
                       count(*) AS n, bclass, office, prods, badge,
                       (list(tin ORDER BY nq DESC))[1:12] AS tins, NULL::VARCHAR[] AS gnames,
                       max(nq) AS nq, max(nev) AS nev
                FROM x GROUP BY place_key, proc, role, code, ntype, bclass, office, prods, badge""", {"proc": proc})
        _log(json.dumps({"state": s, "payer": p, **{t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                                                    for t in ("ogr", "q", f"po_{p}")}}))
        # reading groups at hospitals: radiologists affiliated with a hospital (CMS facility affiliations)
        team_parts.append(f"team_{p}")
        con.execute(f"""CREATE OR REPLACE TABLE team_{p} AS
            SELECT a.ccn, '{p}' AS payer, o.proc, o.code, o.ntype, median(o.rate) AS rate, o.office, o.prods, g.tin,
                   any_value(g.gname) AS gname, count(DISTINCT n.npi) AS nrad
            FROM read_parquet('{src["affil"]}') a JOIN npigrp r ON r.npi = a.npi AND r.grp = 'radiology'
            JOIN read_parquet('{d}/pgnpi.parquet') n ON n.npi = a.npi
            JOIN ogr o ON o.pg = n.pg AND o.role = 'pro'
            JOIN pgs g ON g.pg = o.pg
            WHERE a.ccn IN (SELECT ccn FROM read_parquet('{src["hospitals"]}') WHERE state = '{s}')
            GROUP BY ALL""")
        con.execute("CHECKPOINT")
    if not po_parts:
        return {"places": 0}
    con.execute("CREATE OR REPLACE TABLE offers AS " + " UNION ALL ".join(f"SELECT * FROM {t}" for t in po_parts))
    con.execute("CREATE OR REPLACE TABLE team AS " + " UNION ALL ".join(f"SELECT * FROM {t}" for t in team_parts))
    for t in po_parts + team_parts + ["og", "ogr", "gp", "q", "qx", "psg", "chk"]:
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.execute("CHECKPOINT")
    # places
    con.execute(f"""CREATE OR REPLACE TABLE pl AS
        WITH a AS (SELECT place_key, any_value(line1) AS line1, any_value(city) AS city, any_value(zip5) AS zip5,
                          any_value(phone) AS phone FROM addr_s WHERE place_key IN (SELECT DISTINCT place_key FROM offers) AND NOT starts_with(place_key, '|')
                   GROUP BY place_key),
        h AS (SELECT place_key, any_value(ccn) AS ccn, any_value(name) AS hname, any_value(hospital_type) AS htype,
                     any_value(emergency) AS er FROM read_parquet('{src["hospitals"]}') WHERE state = '{s}' GROUP BY place_key),
        o AS (SELECT a.place_key,
                     -- the name on the door: a hospital's "doing business as" name first (shortest wins, e.g. "Le Bonheur
                     -- Children's Hospital" over "... ESRD Unit"), then the most common organization name here
                     coalesce(arg_min(d.dba, length(d.dba)) FILTER (WHERE c.taxonomy_code LIKE '282N%' AND d.dba IS NOT NULL),
                              mode(coalesce(d.dba, c.name))) AS oname,
                     bool_or(c.taxonomy_code = '282NC2000X') AS kidshosp,
                     bool_or(c.taxonomy_code = '261QU0200X') AS urgent,
                     bool_or(c.taxonomy_code IN ('261QR0200X', '261QM1200X', '261QR0206X', '261QR0207X', '261QR0208X')) AS imaging,
                     bool_or(c.taxonomy_code = '291U00000X') AS lab,
                     bool_or(c.taxonomy_code LIKE '282N%') AS hosp
              FROM addr_s a JOIN clin_s c USING (npi) LEFT JOIN dba d USING (npi) WHERE c.entity_type = '2' GROUP BY 1),
        g AS (SELECT place_key, mode(group_name) AS gname FROM read_parquet('{src["dac_groups"]}')
              WHERE place_key IN (SELECT place_key FROM a) GROUP BY 1),
        doc AS (SELECT a.place_key, mode(c.name || coalesce(', ' || c.credential, '')) AS dname
                FROM addr_s a JOIN clin_s c USING (npi) WHERE c.entity_type = '1' AND a.place_key IN (SELECT place_key FROM a)
                GROUP BY 1)
        SELECT a.*, h.ccn, h.htype, h.er,
               coalesce(CASE WHEN o.hosp THEN o.oname END, h.hname, o.oname, g.gname, doc.dname, 'Medical office') AS name,
               CASE WHEN h.ccn IS NOT NULL OR o.hosp THEN 'hospital' WHEN o.urgent THEN 'urgent' WHEN o.imaging THEN 'imaging'
                    WHEN o.lab THEN 'lab' ELSE 'clinic' END AS kind,
               coalesce(o.kidshosp OR h.hname ILIKE '%CHILDREN%' OR o.oname ILIKE '%CHILDREN%' OR h.htype ILIKE '%Childrens%',
                        false) AS kids,
               z.lat + ((hash(a.place_key) % 1000) / 1000.0 - 0.5) * 0.012 AS lat,
               z.lon + ((hash(a.place_key || 'x') % 1000) / 1000.0 - 0.5) * 0.015 AS lng
        FROM a LEFT JOIN h USING (place_key) LEFT JOIN o USING (place_key) LEFT JOIN g USING (place_key)
        LEFT JOIN doc USING (place_key) LEFT JOIN zipc z ON z.zip5 = a.zip5""")
    _log(f"{s}: places and offers ready, writing")
    stats = _write_state(con, s, out)
    stats["seconds"] = round(time.time() - t0)
    stats["offers"] = con.execute("SELECT badge, count(*) FROM offers GROUP BY 1 ORDER BY 1").fetchall()
    return stats


def _write_state(con, s: str, out: str) -> dict:
    """offers/<proc>/<zip3>-<state>.json: places with their offers (and hospital reading groups)."""
    places = {r[0]: r for r in con.execute(
        "SELECT place_key, name, line1, city, zip5, phone, lat, lng, kind, kids, ccn, er FROM pl").fetchall()}
    teams: dict = {}
    for ccn, payer, proc, code, ntype, rate, office, prods, tin, gname, nrad in con.execute(
            "SELECT ccn, payer, proc, code, ntype, rate, office, prods, tin, gname, nrad FROM team "
            "WHERE ntype IN ('negotiated', 'fee schedule', 'derived')").fetchall():
        teams.setdefault((ccn, proc), []).append([payer, code, ntype[0], round(rate, 2), prods, tin, None, nrad])
    names = dict(con.execute("SELECT tin, gname FROM tn").fetchall()) if con.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'tn'").fetchone()[0] else {}
    n = nfiles = 0
    procs = [r[0] for r in con.execute("SELECT DISTINCT proc FROM offers ORDER BY 1").fetchall()]
    for proc in procs:  # one procedure at a time, streamed: a state has millions of offers
        files: dict = {}
        cur = con.execute("""SELECT place_key, payer, proc, role, code, ntype, round(rate, 2), bclass, office, prods, tins,
                                    gnames, nq, nev, badge, round(lo, 2), round(hi, 2), n FROM offers WHERE proc = ?
                             ORDER BY place_key""", [proc])
        while True:
            rows = cur.fetchmany(50000)
            if not rows:
                break
            for (place_key, payer, proc, role, code, ntype, rate, bclass, office, prods, tins, gnames, nq, nev, badge, lo,
                 hi, cnt) in rows:
                pl = places.get(place_key)
                if not pl or pl[6] is None:
                    continue
                f = files.setdefault((pl[4] or "000")[:3], {})
                e = f.get(place_key)
                if e is None:
                    e = f[place_key] = {"k": place_key, "n": pl[1], "a": pl[2], "c": pl[3], "s": s, "z": pl[4], "ph": pl[5],
                                        "lat": round(pl[6], 5), "lng": round(pl[7], 5), "kind": pl[8], "kids": bool(pl[9]),
                                        "o": []}
                    if pl[10]:
                        e["ccn"] = pl[10]
                        e["er"] = pl[11] == "Yes"
                        if (pl[10], proc) in teams:
                            e["t"] = teams[(pl[10], proc)]
                tins = list(dict.fromkeys(tins))[:4]
                e["o"].append([payer, role, code, ntype, rate, 1 if bclass == "institutional" else 0, 1 if office else 0,
                               badge, prods, tins, None, nq, nev, lo, hi, cnt])
                n += 1
        os.makedirs(f"{out}/offers/{proc}", exist_ok=True)
        for z3, f in files.items():
            used = {t for e in f.values() for o in e["o"] for t in o[9]} | {t[5] for e in f.values() for t in e.get("t", [])}
            with open(f"{out}/offers/{proc}/{z3}-{s}.json", "w") as fh:
                json.dump({"proc": proc, "zip3": z3, "state": s, "g": {t: names.get(t) for t in sorted(used)},
                           "places": list(f.values())}, fh, separators=(",", ":"))
        nfiles += len(files)
        del files
    # summary: per procedure, the spread of confirmed/likely dollar totals (global or any) for this state
    summ = con.execute("""SELECT proc, payer, count(DISTINCT place_key), quantile_cont(rate, 0.1), median(rate),
                                 quantile_cont(rate, 0.9)
                          FROM offers WHERE badge IN ('c', 'l') AND role IN ('global', 'any') AND code <> 'FLAT'
                          GROUP BY ALL""").fetchall()
    os.makedirs(f"{out}/summary", exist_ok=True)
    json.dump([list(r) for r in summ], open(f"{out}/summary/{s}.json", "w"))
    return {"places": len(places), "files": nfiles, "offers_written": n}

def meta(work: str = "/tmp/shop-meta", out: str = "/tmp/shop-meta-out", upload_to: str | None = "ratecommons/work",
         prefix: str = "shop/v1") -> dict:
    """App lookups: meta/products.json (plan names per payer, same order as offer indexes), meta/zip3.json
    (ZIP3 -> [lat, lng, radius_mi, states]) and meta/zip/<zip3>.json (ZIP -> [lat, lng, state])."""
    os.makedirs(work, exist_ok=True)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(f"{out}/meta/zip")
    from .serving import US_STATES

    con = _duck(f"{work}/duck")
    src = {f: f"{work}/src/{f}.parquet" for f in ("addr", "zip")}
    _fetch_many([(f"{SRC}/{f}.parquet", d) for f, d in src.items()], 2)
    prods = {}
    for p in PAYERS:
        m = json.load(open(_fetch(f"{CLOUD}/{p}/meta.json", f"{work}/{p}/meta.json")))
        prods[p] = _products(p, m)[0]
    json.dump(prods, open(f"{out}/meta/products.json", "w"), separators=(",", ":"))
    # a ZIP's state: where most clinicians with that ZIP practice (ZCTA files carry no state)
    con.execute(f"""CREATE TABLE zs AS SELECT zip5, mode(state) AS state, count(*) AS n FROM read_parquet('{src["addr"]}')
                    WHERE zip5 IS NOT NULL GROUP BY 1""")
    con.execute(f"""CREATE TABLE z AS SELECT z.zip5, round(z.lat, 4) AS lat, round(z.lon, 4) AS lng, zs.state
                    FROM read_parquet('{src["zip"]}') z JOIN zs USING (zip5) WHERE z.lat IS NOT NULL""")
    by3: dict = {}
    for zip5, lat, lng, st in con.execute("SELECT zip5, lat, lng, state FROM z ORDER BY 1").fetchall():
        by3.setdefault(zip5[:3], {})[zip5] = [lat, lng, st]
    for z3, d in by3.items():
        json.dump(d, open(f"{out}/meta/zip/{z3}.json", "w"), separators=(",", ":"))
    rows = con.execute("""WITH c AS (SELECT left(zip5, 3) AS z3, avg(lat) AS clat, avg(lng) AS clng FROM z GROUP BY 1),
        r AS (SELECT c.z3, c.clat, c.clng, max(3958.8 * 2 * asin(sqrt(pow(sin(radians(z.lat - c.clat) / 2), 2)
                     + cos(radians(c.clat)) * cos(radians(z.lat)) * pow(sin(radians(z.lng - c.clng) / 2), 2)))) AS rad
              FROM z JOIN c ON left(z.zip5, 3) = c.z3 GROUP BY ALL),
        s AS (SELECT left(zip5, 3) AS z3, list(DISTINCT state ORDER BY state) AS states FROM zs WHERE n >= 5 AND state IN (SELECT unnest(?)) GROUP BY 1)
        SELECT r.z3, round(clat, 4), round(clng, 4), least(ceil(rad), 250), coalesce(s.states, []) FROM r LEFT JOIN s USING (z3)""",
        [sorted(US_STATES)]).fetchall()
    json.dump({z3: [lat, lng, int(rad or 0), sts] for z3, lat, lng, rad, sts in rows}, open(f"{out}/meta/zip3.json", "w"),
              separators=(",", ":"))
    res = {"zip3": len(rows), "zips": sum(len(d) for d in by3.values()), "products": {p: len(v) for p, v in prods.items()}}
    if upload_to:
        from .cloudpack import upload

        res["uploaded"] = upload(out, prefix, upload_to)
    return res
