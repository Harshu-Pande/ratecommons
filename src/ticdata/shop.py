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
            with requests.get(url, stream=True, timeout=600, headers={"User-Agent": "Mozilla/5.0 RateCommons"}) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(8 << 20):
                        f.write(chunk)
            return path
        except Exception as e:
            _log(f"download retry {i}: {url}: {e!r}")
            time.sleep(20 * (i + 1))
    raise RuntimeError(f"could not download {url}")


def sources(work: str = "/tmp/shop-src", upload_to: str | None = "ratecommons/work", prefix: str = "shop/sources") -> dict:
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
