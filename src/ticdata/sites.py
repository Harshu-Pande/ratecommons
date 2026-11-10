"""Care-site registry: where a patient can physically get a service, with evidence for each kind of service.

Why: the patient tool used to turn every clinician's NPPES address into a "place" (2026-11-09 audit:
77-90% of imaging places nationwide had no evidence of a scanner; teleradiologists' homes, a palliative-care
office and dental offices were offering CT). A place now has to be a site, and an equipment service has to be
supported by evidence at that site.

`build()` writes, to the work bucket under shop/sites/:
  sites.parquet       site_key, name, kind, line1, city, state, zip5, ccn, sources (list), n_clin
  place_site.parquet  place_key -> site_key (several spellings of one address map to one site)
  site_cap.parquet    site_key, cap, level ('c' confirmed / 'l' likely), evidence (list of strings)

A site needs at least one organizational source: a Medicare-certified facility (POS files), a facility-type
Medicare supplier (enrollment file), an organization NPI with a patient-care taxonomy, or a group practice
location with 2+ enrolled clinicians. A lone clinician's address (often a home) is never a site. Places whose
only organizations are home health, hospice, dialysis, nursing homes, pharmacies, equipment suppliers or
transport are not sites for this tool, and neither are VA hospitals (they do not take commercial insurance
as in-network care).

Capability evidence for equipment services (cap = ct, mri, us, xray, mammo, dexa, pet, echo, sleep, lab):
  - Medicare claims (Physician & Other Practitioners by Provider and Service): an NPI located at the site billed a
    code of that family in a non-facility setting at more than 1.5x the professional-component amount, i.e. it
    billed the technical part, so the machine is its own. Confirmed.
  - acute hospitals (POS file subtype 01/06/11/28): the POS service flags (CT, MRI, nuclear, PET) confirm; a general
    acute hospital without a flag is likely to have CT, X-ray and ultrasound (the flags are known to be incomplete:
    Missouri Baptist Medical Center is flagged without CT). Hospitals billing imaging APCs to Medicare outpatient
    confirm CT and ultrasound/X-ray.
  - a radiology-center / IDTF / mammography organization at the site whose radiologists bill that family: likely.
"""
from __future__ import annotations

import json
import os
import re
import time

from .serving import _duck, _log
from .shop import SRC, CLOUD, place_key_sql, _download

POS_HOSP = "https://data.cms.gov/sites/default/files/2026-10/e5a8afbb-a1f4-4d3b-bdb9-3968e194da0e/Hospital_and_other.DATA.Q3_2026.csv"
POS_IQIES = "https://data.cms.gov/sites/default/files/2026-10/d7e32873-6bf0-4719-9048-376972900d5c/POS_iQIES.DATA.Q3_2026.csv"
PPEF = "https://data.cms.gov/sites/default/files/2026-09/b840a66b-6781-4630-9238-d056ecd633ce/PPEF_Enrollment_Extract_2026.09.29.csv"
OPPS_PROV = "https://data.cms.gov/sites/default/files/2026-06/794975f5-e335-4cbf-8e87-982c834a9639/MUP_OUT_RY26_P04_V10_DY24_Prov_Svc.csv"
W = "(FORMAT parquet, COMPRESSION zstd)"

# HCPCS families: (cap, lo, hi) inclusive numeric ranges of 5-digit codes
FAMILIES = [
    ("ct", 70450, 70498), ("ct", 71250, 71275), ("ct", 72125, 72133), ("ct", 72191, 72194), ("ct", 73200, 73206),
    ("ct", 73700, 73706), ("ct", 74150, 74178), ("ct", 74261, 74263), ("ct", 75571, 75574),
    ("mri", 70540, 70559), ("mri", 71550, 71555), ("mri", 72141, 72159), ("mri", 72195, 72198), ("mri", 73218, 73225),
    ("mri", 73718, 73725), ("mri", 74181, 74185), ("mri", 77046, 77049),
    ("us", 76506, 76999), ("us", 93880, 93998),
    ("mammo", 77061, 77067),
    ("dexa", 77080, 77086),
    ("pet", 78811, 78816),
    ("echo", 93303, 93356),
    ("sleep", 95805, 95811),
    ("xray", 70010, 70360), ("xray", 71045, 71130), ("xray", 72020, 72120), ("xray", 72170, 72190), ("xray", 72200, 72220),
    ("xray", 73000, 73140), ("xray", 73501, 73660), ("xray", 74018, 74022),
    ("lab", 80047, 89398),
]
# catalog modality -> capability
MODALITY_CAP = {"CT": "ct", "MRI": "mri", "Ultrasound": "us", "Mammogram": "mammo", "X-ray": "xray", "PET": "pet"}
PROC_CAP = {"dexa": "dexa", "echo": "echo", "sleep-study": "sleep", "us-carotid": "us"}

# organization taxonomies that do not make an address a place to shop for these services
EXCLUDED_ORG_TAX = ("251E", "251G", "315D", "3140", "3130", "314", "311", "310", "3336", "332", "335", "341", "343", "344",
                    "261QE0700X", "251B", "251C", "251J", "251K", "251S", "385H", "253", "323P", "320", "322", "324")
URGENT_TAX = ("261QU0200X",)
RADCTR_TAX = ("261QR0200X", "261QR0206X", "261QR0207X", "261QR0208X", "261QX0200X", "261QM1200X")
FAC_SUPPLIERS = {  # Medicare enrollment provider type code -> site source label
    "12-47": "idtf", "12-45": "mammo_ctr", "12-49": "asc", "12-69": "lab", "12-70": "clinic", "12-Z1": "hospdept",
    "12-74": "radtx", "12-C0": "sleep_lab", "00-04": "fqhc", "00-17": "rhc", "00-09": "hosp_npi", "00-85": "hosp_npi",
    "12-65": "pt", "00-14": "pt", "00-02": "pt",
}


def site_key_sql(pk: str) -> str:
    """Merge spellings of one address: house number + first non-directional street word + ZIP5.
    '1 BARNES JEWISH HOSPITAL PLZ|63110', '1 BARNES JEW HOSP PLZ|63110' and 'ONE BARNES-JEWISH HOSPITAL PLZ|63110'
    all become '1 BARNES|63110'. Addresses without a leading number keep their whole place key."""
    street = f"regexp_replace(regexp_replace(split_part({pk}, '|', 1), '^ONE ', '1 '), '-', ' ', 'g')"
    words = f"string_split(trim(regexp_replace({street}, '\\s+(N|S|E|W|NE|NW|SE|SW)\\s+', ' ', 'g')), ' ')"
    zip5 = f"split_part({pk}, '|', 2)"
    return (f"CASE WHEN regexp_matches(split_part({pk}, '|', 1), '^(\\d+|ONE)\\s') AND len({words}) >= 2 "
            f"THEN {words}[1] || ' ' || {words}[2] || '|' || {zip5} ELSE {pk} END")


def _fam_sql(col: str) -> str:
    x = f"TRY_CAST({col} AS INTEGER)"
    return "CASE " + " ".join(f"WHEN {x} BETWEEN {lo} AND {hi} THEN '{c}'" for c, lo, hi in FAMILIES) + " END"


def _csv_utf8(url: str, path: str) -> str:
    raw = _download(url, path + ".raw")
    with open(raw, "rb") as f, open(path, "w", encoding="utf-8") as g:
        for line in f:
            g.write(line.decode("cp1252", errors="replace"))
    os.remove(raw)
    return path


def build(work: str = "/tmp/sites", upload_to: str | None = "ratecommons/work", prefix: str = "shop/sites",
          local: dict | None = None) -> dict:
    """Build the registry. `local` maps source names to already-downloaded paths (for tests)."""
    t0 = time.time()
    os.makedirs(f"{work}/out", exist_ok=True)
    local = local or {}
    src = {}
    for f in ("addr", "clin", "dac_groups", "medicare", "hospitals"):
        src[f] = local.get(f) or _download(f"{SRC}/{f}.parquet", f"{work}/{f}.parquet")
    src["pfs"] = local.get("pfs") or _download(f"{CLOUD}/shared/medicare.parquet", f"{work}/pfs.parquet")
    src["pos"] = local.get("pos") or _csv_utf8(POS_HOSP, f"{work}/pos.csv")
    src["iqies"] = local.get("iqies") or _csv_utf8(POS_IQIES, f"{work}/iqies.csv")
    src["ppef"] = local.get("ppef") or _csv_utf8(PPEF, f"{work}/ppef.csv")
    src["opps"] = local.get("opps") or _csv_utf8(OPPS_PROV, f"{work}/opps.csv")
    con = _duck(f"{work}/duck")
    rd = lambda p: f"read_parquet('{p}')" if p.endswith(".parquet") else f"read_csv('{p}', all_varchar = true, header = true)"
    res: dict = {}

    # ---- source rows: (place_key, src, name, kind hint, ccn, npi) --------------------------------------------
    con.execute(f"""CREATE OR REPLACE TABLE pos AS SELECT PRVDR_NUM AS ccn, FAC_NAME AS name, ST_ADR AS line1, CITY_NAME AS city,
            STATE_CD AS state, left(ZIP_CD, 5) AS zip5, PRVDR_CTGRY_SBTYP_CD AS sub, CT_SCAN_SRVC_CD AS ct,
            MGNTC_RSNC_IMG_SRVC_CD AS mri, NUCLR_MDCN_SRVC_CD AS nuc, PET_SCAN_SRVC_CD AS pet, DGNSTC_RDLGY_SRVC_CD AS dr,
            {place_key_sql('ST_ADR', 'ZIP_CD')} AS place_key
        FROM {rd(src['pos'])} WHERE PGM_TRMNTN_CD = '00'""")
    # acute (01), critical access (11), children's (06), rural emergency (28); VA and other federal hospitals have
    # no subtype and a CCN ending in a letter
    con.execute("""CREATE OR REPLACE TABLE hosp AS SELECT *, sub = '11' AS cah FROM pos
                   WHERE sub IN ('01', '06', '11', '28') AND regexp_matches(ccn, '^\\d{6}$')""")
    con.execute("""CREATE OR REPLACE TABLE va AS SELECT place_key FROM pos
                   WHERE NOT regexp_matches(ccn, '^\\d{6}$') OR name ILIKE '%VETERANS%' OR name ILIKE 'VA %'""")
    con.execute(f"""CREATE OR REPLACE TABLE iq AS SELECT prvdr_num AS ccn, fac_name AS name, st_adr AS line1, city_name AS city,
            state_cd AS state, left(zip_cd, 5) AS zip5, prvdr_type_id AS t, {place_key_sql('st_adr', 'zip_cd')} AS place_key
        FROM {rd(src['iqies'])} WHERE trim(pgm_trmntn_cd) = '00'""")
    con.execute(f"""CREATE OR REPLACE TABLE ppef AS SELECT DISTINCT TRY_CAST(NPI AS BIGINT) AS npi, PROVIDER_TYPE_CD AS t
                    FROM {rd(src['ppef'])} WHERE PROVIDER_TYPE_CD IN ({", ".join(f"'{k}'" for k in FAC_SUPPLIERS)})""")
    con.execute(f"CREATE OR REPLACE TABLE addr AS SELECT * FROM {rd(src['addr'])} WHERE place_key IS NOT NULL AND NOT starts_with(place_key, '|')")
    con.execute(f"CREATE OR REPLACE TABLE clin AS SELECT npi, entity_type, name, other_name, taxonomy_code, taxonomies FROM {rd(src['clin'])}")
    excl = " OR ".join(f"starts_with(t, '{x}')" for x in EXCLUDED_ORG_TAX)
    urg = " OR ".join(f"t = '{x}'" for x in URGENT_TAX)
    rad = " OR ".join(f"t = '{x}'" for x in RADCTR_TAX)
    con.execute(f"""CREATE OR REPLACE TABLE orgs AS
        SELECT a.place_key, c.npi, coalesce(nullif(nullif(c.other_name, ''), '<UNAVAIL>'), c.name) AS name,
               bool_and({excl}) AS excluded, bool_or({urg}) AS urgent, bool_or({rad}) AS radctr,
               bool_or(starts_with(t, '282N') OR starts_with(t, '283X') OR starts_with(t, '273')) AS hospital_tax
        FROM addr a JOIN (SELECT npi, name, other_name, unnest(coalesce(taxonomies, [taxonomy_code])) AS t FROM clin
                          WHERE entity_type = '2') c USING (npi)
        GROUP BY ALL""")
    con.execute(f"""CREATE OR REPLACE TABLE dacloc AS SELECT place_key, count(DISTINCT npi) AS n, mode(group_name) AS gname
                    FROM {rd(src['dac_groups'])} WHERE place_key IS NOT NULL GROUP BY 1""")
    fs = "CASE " + " ".join(f"WHEN p.t = '{k}' THEN '{v}'" for k, v in FAC_SUPPLIERS.items()) + " END"
    iqk = "CASE t WHEN '11' THEN 'asc' WHEN '15' THEN 'fqhc' WHEN '9' THEN 'rhc' WHEN '6' THEN 'pt' WHEN '10' THEN 'pt' END"
    con.execute(f"""CREATE OR REPLACE TABLE srcrows AS
        SELECT place_key, 'hosp' AS src, name, ccn, NULL::BIGINT AS npi, line1, city, state, zip5 FROM hosp
        UNION ALL SELECT place_key, 'hosp', name, ccn, NULL, line1, city, state, zip5 FROM {rd(src['hospitals'])}
            WHERE place_key IS NOT NULL AND (hospital_type ILIKE '%acute%' OR hospital_type ILIKE '%critical%' OR hospital_type ILIKE '%child%')
        UNION ALL SELECT place_key, {iqk}, name, ccn, NULL, line1, city, state, zip5 FROM iq WHERE {iqk} IS NOT NULL
        UNION ALL SELECT a.place_key, {fs}, NULL, NULL, a.npi, a.line1, a.city, a.state, a.zip5 FROM ppef p JOIN addr a USING (npi)
        UNION ALL SELECT place_key, CASE WHEN hospital_tax THEN 'hosp_npi' WHEN urgent THEN 'urgent' WHEN radctr THEN 'radctr'
                                         ELSE 'org' END, name, NULL, npi, NULL, NULL, NULL, NULL FROM orgs WHERE NOT excluded
        UNION ALL SELECT place_key, 'excluded', name, NULL, npi, NULL, NULL, NULL, NULL FROM orgs WHERE excluded
        UNION ALL SELECT place_key, 'group', gname, NULL, NULL, NULL, NULL, NULL, NULL FROM dacloc WHERE n >= 2
        UNION ALL SELECT place_key, 'va', NULL, NULL, NULL, NULL, NULL, NULL, NULL FROM va""")
    con.execute(f"""CREATE OR REPLACE TABLE pk AS SELECT DISTINCT place_key, {site_key_sql('place_key')} AS site_key
                    FROM (SELECT place_key FROM srcrows UNION SELECT place_key FROM addr)""")
    # ---- sites ---------------------------------------------------------------------------------------------------
    con.execute("""CREATE OR REPLACE TABLE site_src AS SELECT k.site_key, list(DISTINCT s.src ORDER BY s.src) AS sources
                   FROM srcrows s JOIN pk k USING (place_key) GROUP BY 1""")
    con.execute("""CREATE OR REPLACE TABLE ok AS SELECT site_key, sources FROM site_src
                   WHERE NOT list_contains(sources, 'va')
                     AND len(list_filter(sources, x -> x NOT IN ('excluded', 'va'))) > 0""")
    con.execute("""CREATE OR REPLACE TABLE clinsite AS SELECT DISTINCT k.site_key, a.npi FROM addr a JOIN pk k USING (place_key)
                   JOIN clin c USING (npi) WHERE c.entity_type = '1' AND k.site_key IN (SELECT site_key FROM ok)""")
    # name: hospital, then facility suppliers, urgent care, radiology center, group practice, other organization
    rank = ("CASE s.src WHEN 'hosp' THEN 1 WHEN 'asc' THEN 2 WHEN 'fqhc' THEN 3 WHEN 'rhc' THEN 3 WHEN 'urgent' THEN 4 "
            "WHEN 'radctr' THEN 5 WHEN 'idtf' THEN 5 WHEN 'mammo_ctr' THEN 5 WHEN 'hosp_npi' THEN 6 WHEN 'group' THEN 7 "
            "WHEN 'org' THEN 8 WHEN 'clinic' THEN 9 ELSE 20 END")
    con.execute(f"""CREATE OR REPLACE TABLE sites AS
        WITH nm AS (SELECT k.site_key, arg_min(s.name, {rank} * 1000 + length(coalesce(s.name, 'x'))) FILTER (WHERE s.name IS NOT NULL
                           AND s.src NOT IN ('excluded', 'va')) AS name,
                           min({rank}) AS best,
                           arg_min(s.ccn, {rank}) FILTER (WHERE s.ccn IS NOT NULL AND s.src = 'hosp') AS ccn
                    FROM srcrows s JOIN pk k USING (place_key) GROUP BY 1),
        ad AS (SELECT k.site_key, arg_min(a.line1, length(a.line1)) AS line1, mode(a.city) AS city, mode(a.state) AS state,
                      mode(a.zip5) AS zip5 FROM addr a JOIN pk k USING (place_key) GROUP BY 1),
        ad2 AS (SELECT k.site_key, any_value(s.line1) AS line1, any_value(s.city) AS city, any_value(s.state) AS state,
                       any_value(s.zip5) AS zip5 FROM srcrows s JOIN pk k USING (place_key) WHERE s.line1 IS NOT NULL GROUP BY 1)
        SELECT ok.site_key, nm.name, nm.ccn,
               CASE WHEN list_contains(ok.sources, 'hosp') THEN 'hospital' WHEN list_contains(ok.sources, 'asc') THEN 'asc'
                    WHEN list_contains(ok.sources, 'urgent') THEN 'urgent'
                    WHEN list_has_any(ok.sources, ['radctr', 'idtf', 'mammo_ctr']) THEN 'imaging'
                    WHEN list_contains(ok.sources, 'lab') AND len(ok.sources) = 1 THEN 'lab'
                    WHEN list_has_any(ok.sources, ['fqhc', 'rhc']) THEN 'clinic' ELSE 'clinic' END AS kind,
               coalesce(ad2.line1, ad.line1) AS line1, coalesce(ad2.city, ad.city) AS city, coalesce(ad2.state, ad.state) AS state,
               coalesce(ad2.zip5, ad.zip5) AS zip5, ok.sources,
               (SELECT count(*) FROM clinsite c WHERE c.site_key = ok.site_key) AS n_clin
        FROM ok LEFT JOIN nm USING (site_key) LEFT JOIN ad USING (site_key) LEFT JOIN ad2 USING (site_key)""")
    res["sites"] = con.execute("SELECT kind, count(*) FROM sites GROUP BY 1 ORDER BY 2 DESC").fetchall()

    # ---- capability evidence ------------------------------------------------------------------------------------
    con.execute(f"""CREATE OR REPLACE TABLE pro AS SELECT hcpcs, median(nonfacility_amount) AS pro
                    FROM {rd(src['pfs'])} WHERE modifier = '26' AND state = 'US' GROUP BY 1""")
    con.execute(f"""CREATE OR REPLACE TABLE techclaims AS
        SELECT m.npi, m.zip5, {_fam_sql('m.hcpcs')} AS cap, sum(m.services) AS services
        FROM {rd(src['medicare'])} m LEFT JOIN pro p USING (hcpcs)
        WHERE m.pos = 'O' AND {_fam_sql('m.hcpcs')} IS NOT NULL
          AND (p.pro IS NULL OR m.avg_allowed > 1.5 * p.pro)
        GROUP BY ALL""")
    # where those NPIs work: their site addresses, if they have no more than 5 (a clinician on 30 addresses says nothing)
    con.execute("""CREATE OR REPLACE TABLE npisites AS
        SELECT a.npi, k.site_key FROM addr a JOIN pk k USING (place_key) WHERE k.site_key IN (SELECT site_key FROM sites)
        GROUP BY ALL""")
    con.execute("""CREATE OR REPLACE TABLE npisites5 AS SELECT * FROM npisites
                   WHERE npi IN (SELECT npi FROM npisites GROUP BY 1 HAVING count(*) <= 5)""")
    con.execute(f"""CREATE OR REPLACE TABLE allclaims AS SELECT DISTINCT m.npi, {_fam_sql('m.hcpcs')} AS cap
                    FROM {rd(src['medicare'])} m WHERE {_fam_sql('m.hcpcs')} IS NOT NULL""")
    con.execute(f"""CREATE OR REPLACE TABLE opps AS SELECT Rndrng_Prvdr_CCN AS ccn, APC_Cd AS apc, TRY_CAST(CAPC_Srvcs AS DOUBLE) AS n
                    FROM {rd(src['opps'])}""")
    con.execute("""CREATE OR REPLACE TABLE cap AS
        -- 1. technical-component claims by someone working at the site
        -- (only at the clinician's sites in the ZIP Medicare lists for them, so a radiologist's other addresses get nothing)
        SELECT s.site_key, t.cap, 'c' AS level, 'medicare_tech_claims' AS ev FROM techclaims t JOIN npisites5 s USING (npi)
        WHERE split_part(s.site_key, '|', 2) = t.zip5
        UNION ALL
        -- 2. hospital service flags (POS file): 1 own staff, 2 under arrangement, 3 both
        SELECT k.site_key, x.cap, 'c', 'pos_flag_' || x.cap FROM hosp h JOIN pk k USING (place_key)
        CROSS JOIN LATERAL (SELECT unnest(['ct', 'mri', 'pet', 'xray', 'us', 'mammo']) AS cap,
                                   unnest([h.ct, h.mri, h.pet, h.dr, h.dr, NULL]) AS flag) x
        WHERE x.flag IN ('1', '2', '3')
        UNION ALL
        -- 3. hospitals billing imaging APCs to Medicare outpatient (5521-5524 without contrast, 5571-5573 with)
        SELECT k.site_key, c.cap, 'c', 'opps_imaging_apc' FROM hosp h JOIN pk k USING (place_key)
        JOIN (SELECT ccn FROM opps WHERE apc IN ('5521','5522','5523','5524','5571','5572','5573') GROUP BY 1 HAVING sum(n) >= 11) o USING (ccn)
        CROSS JOIN (SELECT unnest(['ct', 'xray', 'us']) AS cap) c
        UNION ALL
        -- 4. any general acute (non-CAH) or children's hospital: CT, X-ray, ultrasound, echo, lab likely; MRI, mammo likely
        SELECT k.site_key, c.cap, 'l', 'acute_hospital' FROM hosp h JOIN pk k USING (place_key)
        CROSS JOIN (SELECT unnest(['ct', 'xray', 'us', 'echo', 'lab', 'mri', 'mammo', 'dexa', 'sleep']) AS cap) c WHERE NOT h.cah
        UNION ALL
        SELECT k.site_key, c.cap, 'l', 'critical_access_hospital' FROM hosp h JOIN pk k USING (place_key)
        CROSS JOIN (SELECT unnest(['ct', 'xray', 'us', 'lab']) AS cap) c WHERE h.cah
        UNION ALL
        -- 5. imaging organization at the site whose radiologists bill the family (any setting)
        SELECT s.site_key, a.cap, 'l', 'imaging_org_with_billing_radiologists'
        FROM sites s JOIN npisites5 n USING (site_key) JOIN allclaims a USING (npi)
        WHERE list_has_any(s.sources, ['radctr', 'mammo_ctr', 'hospdept']) AND a.cap NOT IN ('lab', 'sleep')
        UNION ALL
        -- 6. laboratories
        SELECT site_key, 'lab', 'c', 'lab_supplier' FROM sites WHERE list_contains(sources, 'lab')""")
    con.execute("""CREATE OR REPLACE TABLE site_cap AS SELECT site_key, cap, min(level) AS level, list(DISTINCT ev) AS evidence
                   FROM cap WHERE site_key IN (SELECT site_key FROM sites) GROUP BY 1, 2""")
    res["capabilities"] = con.execute("SELECT cap, level, count(*) FROM site_cap GROUP BY 1, 2 ORDER BY 1, 2").fetchall()

    con.execute(f"COPY sites TO '{work}/out/sites.parquet' {W}")
    con.execute(f"COPY (SELECT place_key, site_key FROM pk WHERE site_key IN (SELECT site_key FROM sites)) TO '{work}/out/place_site.parquet' {W}")
    con.execute(f"COPY site_cap TO '{work}/out/site_cap.parquet' {W}")
    res["seconds"] = round(time.time() - t0)
    _log(json.dumps(res, default=str))
    if upload_to:
        from .cloudpack import upload

        res["uploaded"] = upload(f"{work}/out", prefix, upload_to)
    return res


# ---- rewrite the published patient offers onto sites ----------------------------------------------------------------
def _proc_cap(p: dict) -> str | None:
    if p["id"] in PROC_CAP:
        return PROC_CAP[p["id"]]
    if p["kind"] == "imaging":
        return MODALITY_CAP.get(p.get("modality") or "")
    if p["id"].startswith("lab-"):
        return "lab"
    return None


def clean_file(d: dict, proc: dict, place_site: dict, sites: dict, caps: dict, stats: dict, hf: dict | None = None) -> dict:
    """One offers file: keep places that are sites (with evidence for equipment services), merge spellings of one
    address, take names and kinds from the registry, and read facility-setting 'global' professional rates as what
    they are (the professional fee)."""
    cap = _proc_cap(proc)
    out: dict = {}
    for p in d["places"]:
        sk = place_site.get(p["k"])
        if not sk:
            stats["dropped_not_site"] += 1
            continue
        lvl = caps.get((sk, cap)) if cap else "c"
        if cap and not lvl:
            stats["dropped_no_evidence"] += 1
            continue
        s = sites[sk]
        if cap and cap != "lab":
            # equipment services: a group's rate at this site counts only if one of its clinicians here has billed
            # the code or its family to Medicare (nev), or it is the hospital's own (institutional) contract;
            # otherwise it is a network-wide fee schedule attached to a group that does not do this here
            n0 = len(p["o"])
            p = dict(p, o=[o for o in p["o"] if o[5] or (o[12] or 0) > 0 or o[7] == "x"])
            stats["dropped_no_billing"] = stats.get("dropped_no_billing", 0) + n0 - len(p["o"])
            if not p["o"] and not p.get("t"):
                stats["dropped_no_evidence"] += 1
                continue
        for o in p["o"]:
            if o[1] == "global" and not o[5] and not o[6]:
                o[1] = "pro"  # a global code paid only in hospital settings is the physician's fee
                stats["global_to_pro"] += 1
        e = out.get(sk)
        if e is None:
            e = dict(p)
            e["k"] = sk
            e["n"] = s["name"] or p["n"]
            e["kind"] = (s["kind"] if s["kind"] in ("hospital", "imaging", "urgent", "lab")
                         else p["kind"] if p["kind"] in ("urgent", "lab", "imaging") else "clinic")
            if s["line1"]:
                e["a"], e["c"], e["z"] = s["line1"].title() if s["line1"].isupper() else s["line1"], (s["city"] or p["c"]).title(), s["zip5"] or p["z"]
            if s["ccn"] and "ccn" not in e:
                e["ccn"] = s["ccn"]
            e["ev"] = lvl
            e["o"] = list(p["o"])
            out[sk] = e
            stats["kept"] += 1
        else:
            e["o"].extend(p["o"])
            if "t" in p and "t" not in e:
                e["t"] = p["t"]
            stats["merged"] += 1
    if hf:  # facility fees from hospitals' own price files, for the codes of this procedure
        codes = set(proc["codes"]) | set(proc.get("alt", []))
        for e in out.values():
            rows = [r for r in hf.get(e.get("ccn") or "", []) if r[1] in codes]
            if rows:
                e["hf"] = rows
                stats["hospital_file_fees"] = stats.get("hospital_file_fees", 0) + 1
    d = dict(d)
    d["places"] = list(out.values())
    used = {t for e in d["places"] for o in e["o"] for t in (o[9] or [])} | {t[5] for e in d["places"] for t in e.get("t", [])}
    d["g"] = {t: v for t, v in d["g"].items() if t in used}
    return d


ADDENDUM_B = "https://www.cms.gov/files/zip/October-2026-OPPS-Addendum-B.zip"


def medicare_table(work: str) -> dict:
    """Original Medicare 2026 amounts for the catalog's codes: OPPS national payment (hospital outpatient facility fee)
    from Addendum B, and physician fee schedule amounts by state (global non-facility, 26 in a facility, TC)."""
    import io
    import zipfile

    import duckdb
    import requests

    from .shop import _fetch
    from .shopcatalog import catalog

    codes = sorted({c for p in catalog() for k in ("codes", "alt", "addon") for c in p.get(k, [])})
    opps = {}
    z = zipfile.ZipFile(io.BytesIO(requests.get(ADDENDUM_B, timeout=300).content))
    txt = [n for n in z.namelist() if n.endswith(".txt")][0]
    for line in z.read(txt).decode("cp1252", errors="replace").splitlines():
        f = line.split("\t")
        if len(f) > 7 and f[0] in codes and f[5].startswith("$"):
            opps[f[0]] = [float(f[5][1:].replace(",", "")), float(f[7][1:].replace(",", "")) if f[7].startswith("$") else None, f[2]]
    pfs = _fetch(f"{CLOUD}/shared/medicare.parquet", f"{work}/pfs.parquet")
    con = duckdb.connect()
    by: dict = {}
    for st, code, mod, nf, fa in con.execute(f"""SELECT state, hcpcs, coalesce(modifier, ''), nonfacility_amount, facility_amount
                                               FROM '{pfs}' WHERE hcpcs IN ({", ".join(f"'{c}'" for c in codes)})""").fetchall():
        r = by.setdefault(st, {}).setdefault(code, [None, None, None])
        if mod == "":
            r[0] = nf if nf else None
            r[1] = r[1] if r[1] is not None else (fa or None)  # codes without a 26 split: the facility amount
        elif mod == "26":
            r[1] = fa or nf
        elif mod == "TC":
            r[2] = nf
    return {"year": 2026, "part_b_deductible": 283, "opps": opps, "pfs": by,
            "sources": ["CMS OPPS Addendum B, October 2026", "CMS Physician Fee Schedule 2026 (state = mean locality GPCI)"]}


def _fetch_many_safe(pairs, threads=16) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    from .shop import _fetch

    def one(p):
        try:
            return _fetch(*p)
        except Exception as e:  # one unreadable file must not stop the state; it is counted as missing
            _log(f"skip {p[0]}: {e!r}")
            return None

    with ThreadPoolExecutor(threads) as ex:
        return dict(zip([d for _, d in pairs], ex.map(one, pairs)))


def clean(states: list[str] | None = None, src_prefix: str = "shop/v1", dst_prefix: str = "shop/v2",
          work: str = "/tmp/shop-clean", upload_to: str | None = "ratecommons/work", sites_dir: str | None = None) -> dict:
    """Rewrite every offers file (all procedures, the given states or all) from src_prefix to dst_prefix, and copy
    the meta files, so the app can switch prefixes."""
    import duckdb

    from .shop import _fetch, _fetch_many
    from .shopcatalog import catalog

    t0 = time.time()
    base = "https://huggingface.co/buckets/ratecommons/work/resolve"
    out = f"{work}/out"
    os.makedirs(out, exist_ok=True)
    sd = sites_dir or f"{work}/sites"
    if not sites_dir:
        os.makedirs(sd, exist_ok=True)
        _fetch_many([(f"{base}/shop/sites/{f}.parquet", f"{sd}/{f}.parquet") for f in ("sites", "place_site", "site_cap")], 3)
    con = duckdb.connect()
    place_site = dict(con.execute(f"SELECT place_key, site_key FROM '{sd}/place_site.parquet'").fetchall())
    cols = ["site_key", "name", "kind", "line1", "city", "state", "zip5", "ccn"]
    sites = {r[0]: dict(zip(cols, r)) for r in con.execute(f"SELECT {', '.join(cols)} FROM '{sd}/sites.parquet'").fetchall()}
    caps = {(a, b): c for a, b, c in con.execute(f"SELECT site_key, cap, level FROM '{sd}/site_cap.parquet'").fetchall()}
    idx = json.load(open(_fetch(f"{base}/{src_prefix}/meta/zip3.json", f"{work}/zip3.json")))
    hf: dict = {}
    hfp = os.path.join(os.path.dirname(__file__), "data", "hospital_fees.json")
    if os.path.exists(hfp):  # [ccn, payer, code, rate, how, count, lo, hi, plans] from hospitals.facility_fees
        for r in json.load(open(hfp)):
            hf.setdefault(r["ccn"], []).append([r["payer"], r["code"], r["rate"], r["how"], r["count"], r["lo"], r["hi"], r["plans"]])
    want = {s.upper() for s in states} if states else None
    pairs = [(z3, st) for z3, v in idx.items() for st in v[3] if want is None or st in want]
    stats = {k: 0 for k in ("files", "kept", "merged", "dropped_not_site", "dropped_no_evidence", "global_to_pro", "hospital_file_fees", "dropped_no_billing")}
    per_proc = {}
    for proc in catalog():
        before = dict(stats)
        jobs = [(f"{base}/{src_prefix}/offers/{proc['id']}/{z3}-{st}.json", f"{work}/in/{proc['id']}/{z3}-{st}.json")
                for z3, st in pairs]
        os.makedirs(f"{work}/in/{proc['id']}", exist_ok=True)
        got = _fetch_many_safe(jobs, 16)
        os.makedirs(f"{out}/offers/{proc['id']}", exist_ok=True)
        for (_, path) in jobs:
            if not got.get(path) or not os.path.exists(path):
                continue
            try:
                d = json.load(open(path))
            except Exception:
                continue
            if not d:
                continue
            d2 = clean_file(d, proc, place_site, sites, caps, stats, hf)
            stats["files"] += 1
            if d2["places"]:
                json.dump(d2, open(f"{out}/offers/{proc['id']}/{os.path.basename(path)}", "w"), separators=(",", ":"))
            os.remove(path)
        per_proc[proc["id"]] = {k: stats[k] - before[k] for k in stats}
        _log(json.dumps({proc["id"]: per_proc[proc["id"]]}))
    if want is None or states == ["META"]:
        os.makedirs(f"{out}/meta", exist_ok=True)
        for f in ("zip3.json", "products.json"):
            _fetch(f"{base}/{src_prefix}/meta/{f}", f"{out}/meta/{f}")
        # ZIP -> point lookups the app needs before it can search (meta/zip/<zip3>.json)
        _fetch_many_safe([(f"{base}/{src_prefix}/meta/zip/{z3}.json", f"{out}/meta/zip/{z3}.json") for z3 in idx], 16)
        pr = json.load(open(f"{out}/meta/products.json"))
        pr["medicare"] = []  # Original Medicare: one national program, no networks to choose
        json.dump(pr, open(f"{out}/meta/products.json", "w"))
        json.dump(medicare_table(work), open(f"{out}/meta/medicare.json", "w"), separators=(",", ":"))
    res = {"stats": stats, "per_proc": per_proc, "seconds": round(time.time() - t0)}
    json.dump(res, open(f"{out}/clean-{'-'.join(sorted(want)) if want else 'all'}.json", "w"))
    if upload_to:
        from .cloudpack import upload

        res["uploaded"] = upload(out, dst_prefix, upload_to)
    return res
