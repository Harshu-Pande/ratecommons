"""Hospital serving pack for the query server (MCP / API): every hospital's standard charges, by billing code.

Source: the every-code hospital files (work bucket hospitals/full/<fid>.parquet, published as the dataset
ratecommons/hospitals). Three steps, run on GitHub Actions (hospitals.yml "pack"):

  pack_map(n, of)     every of-th file: keep CPT/HCPCS/MS-DRG/APR-DRG/APC rows, collapse duplicate items, label the
                      payer (carrier + program: commercial / medicare_advantage / medicaid / ...), turn percent-of-charges
                      rates into dollars with the item's gross charge, and split by the first 2 hex digits of md5(code)
                      -> hospitals/pack/parts/{rates,charges}/b=XX/sNN_*.parquet, plus one row per file (header info)
  pack_reduce(n, of)  for each coarse bucket XX: gather every shard's part and write the 16 serving files
                      XXY.parquet (first 3 hex digits of md5(code)), sorted by code, state -> serve/v2/hospital/{rates,charges}
  pack_meta()         hospitals.parquet (file -> hospital: CCN, name, address, EIN, type-2 NPIs, how attached),
                      codes.parquet (code -> how many hospitals publish it), meta.json (release id)

The server fetches one small file per code (rates/XXY.parquet) and filters it, the same way the insurer packs work.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import time

from .serving import _log

WORK_BUCKET = "ratecommons/work"
BASE = "https://huggingface.co/buckets/ratecommons/work/resolve"
OUT = "serve/v2/hospital"
PARTS = "hospitals/pack/parts"
CODE_TYPES = ("CPT", "HCPCS", "MS-DRG", "APR-DRG", "APC")

# carrier: the insurance company behind a hospital's payer/plan label (order matters: Anthem before Blue Cross)
CARRIERS = [
    ("aetna", r"AETNA|COVENTRY|MERITAIN"),
    ("cigna", r"CIGNA|HEALTHSPRING|EVERNORTH"),
    ("uhc", r"UNITED ?HEALTH|\bUHC\b|\bUMR\b|OPTUM|SURE ?ST\b|GOLDEN RULE|ALL SAVERS|\bAARP\b|SIERRA HEALTH|ROCKY MOUNTAIN HEALTH"),
    ("anthem", r"ANTHEM|ELEVANCE|WELLPOINT|UNICARE|AMERIGROUP|EMPIRE|HEALTHKEEPERS|HEALTHY BLUE"),
    ("bcbs", r"BLUE ?CROSS|BLUE ?SHIELD|\bBCBS|\bBC ?/? ?BS\b|HIGHMARK|REGENCE|PREMERA|CAREFIRST|FLORIDA BLUE|HORIZON|EXCELLUS"
             r"|INDEPENDENCE|\bIBX\b|WELLMARK|CAPITAL ?BLUE|\bHCSC\b|BLUECARE|BLUE CARE|BLUE ADVANTAGE|\bFEP\b|ARKANSAS BLUE"
             r"|BLUE KC|BLUE PLUS|BLUECHOICE|BLUE CHOICE|USABLE|LIFEWISE"),
    ("humana", r"HUMANA"),
    ("kaiser", r"KAISER"),
    ("centene", r"CENTENE|AMBETTER|WELLCARE|HEALTH ?NET|MERIDIAN|SUNSHINE HEALTH|PEACH STATE|SUPERIOR HEALTH|HOME STATE"
                r"|BUCKEYE|MAGNOLIA|NEBRASKA TOTAL|SILVERSUMMIT|ARIZONA COMPLETE|FIDELIS|CAROLINA COMPLETE|ILLINICARE"
                r"|LOUISIANA HEALTHCARE CONNECTIONS|MANAGED HEALTH SERVICES|ABSOLUTE TOTAL|SUNFLOWER|WESTERN SKY|COORDINATED CARE"),
    ("molina", r"MOLINA"),
    ("oscar", r"OSCAR"),
    ("devoted", r"DEVOTED"),
    ("clover", r"CLOVER"),
    ("alignment", r"ALIGNMENT"),
    ("caresource", r"CARESOURCE"),
    ("tricare", r"TRICARE|CHAMPVA|HUMANA MILITARY"),
]
MEDICAID = (r"MEDICAID|MEDI-?CAL\b|\bCHIP\b|\bMCO\b|CAID\b|COMMUNITY PLAN|COMMUNITY CARE PLAN|SOONERCARE|TENNCARE|MASSHEALTH"
            r"|\bHUSKY\b|APPLE HEALTH|BADGERCARE|HOOSIER|KANCARE|MO ?HEALTHNET|AHCCCS|\bSTAR\b|STAR ?PLUS|STAR ?KIDS"
            r"|HEALTHY ?CONNECTIONS|MEDI-?ASSIST|PEACH ?CARE|DENALI|HEALTHCHOICE|DIAMOND|HEALTH FIRST COLORADO|NJ ?FAMILYCARE"
            r"|MAINECARE|HEALTHY ?LOUISIANA|KY ?SPIRIT|PASSPORT|MEDALLION|CCC ?PLUS|AMERIHEALTH CARITAS|CARESOURCE")
MA_WORDS = (r"MEDICARE ?ADVANTAGE|MEDICARE ?MANAGED|MEDICARE ?(HMO|PPO|PLAN|REPLACEMENT|COMPLETE|PLUS)|\bMA\b|\bMAPD\b"
            r"|\bMA-?PD\b|D-?SNP|\bC-?SNP\b|\bI-?SNP\b|\bSNP\b|SENIOR|GOLD PLUS|SECURE ?HORIZONS|DUAL|\bMMP\b|ADVANTAGE"
            r"|WELLCARE|DEVOTED|CLOVER|ALIGNMENT|HEALTHSPRING|AARP")
MA = MA_WORDS + "|MEDICARE"
WORKERS = r"WORKER|WORK ?COMP|\bW/?C\b|WORKMAN|INDUSTRIAL"


WITHHELD = ("(regexp_matches(code, '^[0-9]{4}[0-9FTU]$') OR ct IN ('CPT', 'CDT', 'RC', 'APR-DRG', 'AP-DRG', 'EAPG') "
            "OR (ct = 'HCPCS' AND NOT regexp_matches(code, '^[A-V][0-9]{4}$')))")  # mirrors licensing.text_withheld


def label(payer: str | None, plan: str | None) -> tuple[str | None, str | None]:
    """(carrier, program) for one payer/plan label as a hospital published it."""
    t = re.sub(r"\s+", " ", f"{payer or ''} {plan or ''}".upper()).strip()
    if not t:
        return None, None
    carrier = next((c for c, rx in CARRIERS if re.search(rx, t)), None)
    if carrier == "tricare":
        return carrier, "tricare"
    if re.search(r"\bVA\b|VETERAN|\bVACCN\b|COMMUNITY CARE NETWORK|TRIWEST", t):
        return carrier, "va"
    if re.search(WORKERS, t):
        return carrier, "workers_comp"
    if re.search(r"MEDICARE", t) and not carrier and not re.search(MA_WORDS, t):
        return "medicare", "medicare"  # traditional Medicare, listed by the hospital as a payer
    if re.search(MEDICAID, t) and not re.search(r"MEDICARE", t):
        return carrier, "medicaid"
    if re.search(MA, t) or carrier in ("devoted", "clover", "alignment"):
        return carrier, "medicare_advantage"
    if re.search(MEDICAID, t):  # Medicare-Medicaid dual plans fall here only without a Medicare Advantage word
        return carrier, "medicaid"
    return carrier, "commercial"


def _cols(con, p: str) -> set[str]:
    return {c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p}')").fetchall()}


def _src_sql(con, p: str) -> str:
    have = _cols(con, p)

    def c(name, cast="VARCHAR"):
        return f"TRY_CAST({name} AS {cast})" if name in have else f"CAST(NULL AS {cast})"

    code = f"upper(trim({c('code')}))"
    ct = f"upper(trim({c('code_type')}))"
    # MS-DRG / APR-DRG codes are published as 3 digits, sometimes 4 with a leading zero or as 1-2 digits
    norm = f"CASE WHEN {ct} IN ('MS-DRG','APR-DRG') AND regexp_matches({code}, '^[0-9]+$') THEN lpad(ltrim({code}, '0'), 3, '0') ELSE {code} END"
    return f"""SELECT {norm} AS code, {ct} AS ct, coalesce(lower(trim({c('setting')})), '') AS setting,
                      coalesce(lower(trim({c('billing_class')})), '') AS bc, nullif(trim({c('modifiers')}), '') AS mods,
                      {c('description')} AS descr, {c('gross', 'DOUBLE')} AS gross, {c('cash', 'DOUBLE')} AS cash,
                      nullif(trim({c('payer')}), '') AS payer, nullif(trim({c('plan')}), '') AS plan,
                      lower(trim({c('methodology')})) AS meth, {c('dollar', 'DOUBLE')} AS dollar,
                      {c('percentage', 'DOUBLE')} AS pct, left({c('algorithm')}, 300) AS alg,
                      {c('median_allowed', 'DOUBLE')} AS med, {c('p10', 'DOUBLE')} AS p10, {c('p90', 'DOUBLE')} AS p90,
                      {c('count')} AS cnt
               FROM read_parquet('{p}') WHERE {ct} IN {CODE_TYPES} AND {code} IS NOT NULL AND {code} <> ''"""


def _attach(work: str) -> dict:
    from .shop import _fetch

    a = _fetch(f"{BASE}/hospitals/fees/attach.json", f"{work}/attach.json")
    return {x["fid"]: x for x in json.load(open(a))}


def _site_states(work: str) -> dict:
    import duckdb

    from .shop import _fetch

    s = _fetch(f"{BASE}/shop/sites/sites.parquet", f"{work}/sites.parquet")
    return {r[0]: r[1] for r in duckdb.connect().execute(
        f"SELECT ccn, any_value(state) FROM '{s}' WHERE ccn IS NOT NULL GROUP BY 1").fetchall()}


ADDR = re.compile(r",\s*([A-Za-z .'-]+?)\s*,?\s+([A-Z]{2})\s+(\d{5})(?:-\d{4})?\s*$")


US = {"AL": "ALABAMA", "AK": "ALASKA", "AZ": "ARIZONA", "AR": "ARKANSAS", "CA": "CALIFORNIA", "CO": "COLORADO",
      "CT": "CONNECTICUT", "DE": "DELAWARE", "DC": "DISTRICT OF COLUMBIA", "FL": "FLORIDA", "GA": "GEORGIA",
      "HI": "HAWAII", "ID": "IDAHO", "IL": "ILLINOIS", "IN": "INDIANA", "IA": "IOWA", "KS": "KANSAS", "KY": "KENTUCKY",
      "LA": "LOUISIANA", "ME": "MAINE", "MD": "MARYLAND", "MA": "MASSACHUSETTS", "MI": "MICHIGAN", "MN": "MINNESOTA",
      "MS": "MISSISSIPPI", "MO": "MISSOURI", "MT": "MONTANA", "NE": "NEBRASKA", "NV": "NEVADA", "NH": "NEW HAMPSHIRE",
      "NJ": "NEW JERSEY", "NM": "NEW MEXICO", "NY": "NEW YORK", "NC": "NORTH CAROLINA", "ND": "NORTH DAKOTA",
      "OH": "OHIO", "OK": "OKLAHOMA", "OR": "OREGON", "PA": "PENNSYLVANIA", "RI": "RHODE ISLAND",
      "SC": "SOUTH CAROLINA", "SD": "SOUTH DAKOTA", "TN": "TENNESSEE", "TX": "TEXAS", "UT": "UTAH", "VT": "VERMONT",
      "VA": "VIRGINIA", "WA": "WASHINGTON", "WV": "WEST VIRGINIA", "WI": "WISCONSIN", "WY": "WYOMING", "PR": "PUERTO RICO"}
_NAME_ST = {v: k for k, v in US.items()}
_ST_ZIP = re.compile(r"\b(" + "|".join(US) + r")\.?[,\s]+(\d{5})(?:-\d{4})?\b")
_NAME_ZIP = re.compile(r"\b(" + "|".join(sorted(_NAME_ST, key=len, reverse=True)) + r")[,\s]+(\d{5})(?:-\d{4})?\b", re.I)
_ST_END = re.compile(r"[,\s](" + "|".join(US) + r")\.?\s*$")


def _addr_parts(a: str | None) -> tuple[str | None, str | None, str | None]:
    """(city, state, zip5) from a free-text US address; city only when the address has the usual commas."""
    t = (a or "").strip()
    m = ADDR.search(t)
    if m and m.group(2) in US:
        return m.group(1).strip().title(), m.group(2), m.group(3)
    m = _ST_ZIP.search(t)
    if m:
        return None, m.group(1), m.group(2)
    m = _NAME_ZIP.search(t)
    if m:
        return None, _NAME_ST[m.group(1).upper()], m.group(2)
    m = _ST_END.search(t)
    return (None, m.group(1), None) if m else (None, None, None)


def _header(j: dict) -> dict:
    """The hospital header of a file's report json: top level for JSON files, under "header" for CSV files."""
    h = dict(j.get("header") or {})
    for k in ("hospital_name", "last_updated_on", "version", "location_name", "hospital_address", "type_2_npi"):
        if not h.get(k) and j.get(k):
            h[k] = j[k]
    h["url"] = j.get("url")
    return h


def _list_full(tok) -> dict[str, int]:
    from huggingface_hub import list_bucket_tree

    return {os.path.basename(i.path)[:-8]: (getattr(i, "size", 0) or 0)
            for i in list_bucket_tree(WORK_BUCKET, prefix="hospitals/full", recursive=True, token=tok)
            if i.path.endswith(".parquet")}


def pack_map(n: int, of: int, work: str = "/tmp/hpack", upload_to: str | None = WORK_BUCKET,
             local: dict | None = None) -> dict:
    """local: {fid: (parquet, header json)} to run on files already on disk (tests); attach/sites still fetched."""
    import duckdb
    from huggingface_hub import download_bucket_files

    from . import hfio

    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(f"{work}/in", exist_ok=True)
    tok = hfio.token_for(hfio.bucket(WORK_BUCKET)) if hfio.oidc_available() else None
    att = _attach(work)
    states = _site_states(work)
    sizes = {f: os.path.getsize(v[0]) for f, v in local.items()} if local else _list_full(tok)
    fids = sorted((f for f in att if f in sizes), key=lambda f: -sizes[f])  # biggest first, dealt round-robin
    mine = fids[n::of]
    db = duckdb.connect(f"{work}/acc.duckdb")
    db.execute(f"SET memory_limit = '{os.environ.get('RC_DUCK_MEMORY', '10GB')}'")
    db.execute(f"SET temp_directory = '{work}/spill'")
    db.execute("SET preserve_insertion_order = false")
    hosp, stats = [], {"files": len(mine), "rates": 0, "charges": 0, "errors": 0}
    first = True
    for i, fid in enumerate(mine):
        t0 = time.time()
        p, h = f"{work}/in/{fid}.parquet", f"{work}/in/{fid}.json"
        try:
            if local:
                shutil.copy(local[fid][0], p)
                shutil.copy(local[fid][1], h)
            else:
                download_bucket_files(WORK_BUCKET, files=[(f"hospitals/full/{fid}.parquet", p),
                                                          (f"hospitals/full/{fid}.json", h)], token=tok)
            head = _header(json.load(open(h)) if os.path.exists(h) else {})
            a = att[fid]
            addrs = head.get("hospital_address") or []
            city, st, zip5 = _addr_parts(addrs[0] if addrs else None)
            state = next((states[c] for c in a.get("ccns") or [] if c in states), None) or st
            hosp.append({"fid": fid, "ccns": a.get("ccns") or [], "ein": a.get("ein"), "how": a.get("how"),
                         "name": head.get("hospital_name"), "locations": head.get("location_name") or [],
                         "address": addrs[0] if addrs else None, "city": city, "state": state, "zip5": zip5,
                         "npis": head.get("type_2_npi") or [], "last_updated": head.get("last_updated_on"),
                         "version": head.get("version"), "url": head.get("url")})
            src = _src_sql(db, p)
            pairs = db.execute(f"SELECT DISTINCT payer, plan FROM ({src}) WHERE payer IS NOT NULL OR plan IS NOT NULL").fetchall()
            db.execute("CREATE OR REPLACE TEMP TABLE lab (payer VARCHAR, plan VARCHAR, carrier VARCHAR, program VARCHAR)")
            if pairs:
                db.executemany("INSERT INTO lab VALUES (?, ?, ?, ?)", [(py, pl, *label(py, pl)) for py, pl in pairs])
            # CPT descriptors (AMA), revenue-code text and APR-DRG labels are not ours to republish (licensing.py):
            # the hospital's description is kept only for public code sets (HCPCS Level II, MS-DRG, APC)
            db.execute(f"CREATE OR REPLACE TEMP TABLE ch AS SELECT code, ct, setting, any_value(descr) FILTER (WHERE NOT ({WITHHELD})) AS descr,"
                       f" median(gross) FILTER (WHERE gross > 0) AS gross, min(gross) FILTER (WHERE gross > 0) AS gross_min,"
                       f" max(gross) FILTER (WHERE gross > 0) AS gross_max, min(cash) FILTER (WHERE cash > 0) AS cash,"
                       f" max(cash) FILTER (WHERE cash > 0) AS cash_max FROM ({src}) GROUP BY ALL")
            sel = f"""SELECT r.*, l.carrier, l.program,
                         CASE WHEN r.pct > 0 AND r.dmin IS NULL THEN round(r.pct / 100 * coalesce(c1.gross, c2.gross), 2) END AS est
                  FROM (SELECT code, ct, setting, bc, mods, payer, plan, meth, min(dollar) AS dmin, max(dollar) AS dmax,
                               min(pct) AS pct, max(pct) AS pct_max, any_value(alg) AS alg, max(med) AS med, min(p10) AS p10,
                               max(p90) AS p90, any_value(cnt) AS claims, count(*) AS n_items
                        FROM ({src}) WHERE (payer IS NOT NULL OR plan IS NOT NULL)
                          AND (dollar IS NOT NULL OR pct IS NOT NULL OR med IS NOT NULL OR alg IS NOT NULL)
                        GROUP BY ALL) r
                  LEFT JOIN lab l ON l.payer IS NOT DISTINCT FROM r.payer AND l.plan IS NOT DISTINCT FROM r.plan
                  LEFT JOIN ch c1 ON c1.code = r.code AND c1.ct = r.ct AND c1.setting = r.setting
                  LEFT JOIN (SELECT code, ct, median(gross) AS gross FROM ch GROUP BY ALL) c2 ON c2.code = r.code AND c2.ct = r.ct"""
            st_lit = f"'{state}'" if state else "CAST(NULL AS VARCHAR)"
            wrap = lambda q: f"SELECT '{fid}' AS fid, {st_lit} AS state, q.*, left(md5(q.code), 2) AS b FROM ({q}) q"  # noqa: E731
            if first:
                db.execute(f"CREATE TABLE rates AS {wrap(sel)}")
                db.execute(f"CREATE TABLE charges AS {wrap('SELECT * FROM ch')}")
                first = False
            else:
                db.execute(f"INSERT INTO rates {wrap(sel)}")
                db.execute(f"INSERT INTO charges {wrap('SELECT * FROM ch')}")
            nr = db.execute(f"SELECT count(*) FROM rates WHERE fid = '{fid}'").fetchone()[0]
            nc = db.execute(f"SELECT count(*) FROM charges WHERE fid = '{fid}'").fetchone()[0]
            hosp[-1].update({"rates": nr, "charges": nc})
            stats["rates"] += nr
            stats["charges"] += nc
            _log(json.dumps({"i": i, "of": len(mine), "fid": fid, "state": state, "rates": nr, "charges": nc,
                             "seconds": round(time.time() - t0)}))
        except Exception as e:  # one bad file must not stop the pack
            stats["errors"] += 1
            _log(f"skip {fid}: {e!r}"[:400])
        finally:
            for x in (p, h):
                if os.path.exists(x):
                    os.remove(x)
    out = f"{work}/out"
    os.makedirs(out, exist_ok=True)
    for t in ("rates", "charges"):
        if not first:
            db.execute(f"COPY {t} TO '{out}/{t}' (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (b), "
                       f"FILENAME_PATTERN 's{n:02d}_{{i}}', OVERWRITE_OR_IGNORE)")
    os.makedirs(f"{out}/hosp", exist_ok=True)
    json.dump(hosp, open(f"{out}/hosp/s{n:02d}.json", "w"), default=str)
    db.close()
    if upload_to:
        from .cloudpack import upload

        stats["uploaded"] = upload(out, PARTS, upload_to)
    return stats


def pack_reduce(n: int, of: int, work: str = "/tmp/hpackr", upload_to: str | None = WORK_BUCKET) -> dict:
    """Coarse buckets n, n+of, ... (of 256): gather every shard's parts and write the 16 fine serving files each."""
    from huggingface_hub import download_bucket_files, list_bucket_tree

    from . import hfio

    tok = hfio.token_for(hfio.bucket(WORK_BUCKET)) if hfio.oidc_available() else None
    mine = [f"{b:02x}" for b in range(256) if b % of == n]
    stats = {"buckets": len(mine), "rates": 0, "charges": 0, "files": 0}
    for b in mine:
        shutil.rmtree(work, ignore_errors=True)
        out = f"{work}/out"
        for t in ("rates", "charges", "codes"):
            os.makedirs(f"{out}/{t}", exist_ok=True)
        got = {}
        for t in ("rates", "charges"):
            files = [i.path for i in list_bucket_tree(WORK_BUCKET, prefix=f"{PARTS}/{t}/b={b}/", recursive=True, token=tok)
                     if i.path.endswith(".parquet")]
            os.makedirs(f"{work}/{t}", exist_ok=True)
            if files:
                download_bucket_files(WORK_BUCKET, files=[(f, f"{work}/{t}/{os.path.basename(f)}") for f in files], token=tok)
            got[t] = bool(files)
        _reduce_bucket(work, b, got, stats)
        if upload_to:
            from .cloudpack import upload

            upload(f"{out}/rates", f"{OUT}/rates", upload_to)
            upload(f"{out}/charges", f"{OUT}/charges", upload_to)
            upload(f"{out}/codes", "hospitals/pack/codes", upload_to)
        _log(json.dumps({"bucket": b, **stats}))
    shutil.rmtree(work, ignore_errors=True)
    return stats


def _reduce_bucket(work: str, b: str, got: dict, stats: dict) -> None:
    """Parts already in work/{rates,charges}/*.parquet -> work/out/{rates,charges}/<fine>.parquet and codes/<b>.parquet."""
    import duckdb

    out = f"{work}/out"
    for t in ("rates", "charges", "codes"):
        os.makedirs(f"{out}/{t}", exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{os.environ.get('RC_DUCK_MEMORY', '10GB')}'")
    con.execute(f"SET temp_directory = '{work}/spill'")
    for t in ("rates", "charges"):
        if not got[t]:
            continue
        con.execute(f"CREATE TABLE {t} AS SELECT *, left(md5(code), 3) AS fb "
                    f"FROM read_parquet('{work}/{t}/*.parquet', union_by_name = true)")
        stats[t] += con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for (fb,) in con.execute(f"SELECT DISTINCT fb FROM {t}").fetchall():
            con.execute(f"COPY (SELECT * EXCLUDE (fb) FROM {t} WHERE fb = '{fb}' ORDER BY code, state, fid) "
                        f"TO '{out}/{t}/{fb}.parquet' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)")
            stats["files"] += 1
    if got["rates"] or got["charges"]:
        src = "rates" if got["rates"] else "charges"
        ch = ("LEFT JOIN (SELECT code, ct, count(DISTINCT fid) AS hospitals_with_charges, any_value(descr) AS descr "
              "FROM charges GROUP BY ALL) c USING (code, ct)") if got["charges"] and got["rates"] else ""
        con.execute(f"""COPY (SELECT code, ct AS code_type, count(DISTINCT fid) AS hospitals, count(DISTINCT state) AS states,
                                count(*) AS rows{', any_value(c.hospitals_with_charges) AS hospitals_with_charges, any_value(c.descr) AS example_description' if ch else ''}
                         FROM {src} {ch} GROUP BY ALL) TO '{out}/codes/{b}.parquet' (FORMAT parquet)""")
    con.close()


def pack_meta(work: str = "/tmp/hpackm", upload_to: str | None = WORK_BUCKET, download: bool = True) -> dict:
    """hospitals.parquet, codes.parquet and meta.json for the server (download=False: parts already in work/)."""
    import duckdb
    from huggingface_hub import download_bucket_files, list_bucket_tree

    from . import hfio
    from .shop import _fetch

    if download:
        shutil.rmtree(work, ignore_errors=True)
    os.makedirs(f"{work}/hosp", exist_ok=True)
    os.makedirs(f"{work}/codes", exist_ok=True)
    os.makedirs(f"{work}/out", exist_ok=True)
    tok = hfio.token_for(hfio.bucket(WORK_BUCKET)) if hfio.oidc_available() else None
    for pre, dest in ((f"{PARTS}/hosp", "hosp"), ("hospitals/pack/codes", "codes")) if download else ():
        files = [i.path for i in list_bucket_tree(WORK_BUCKET, prefix=pre, recursive=True, token=tok)
                 if getattr(i, "type", "file") != "directory"]
        for k in range(0, len(files), 200):
            download_bucket_files(WORK_BUCKET, files=[(f, f"{work}/{dest}/{os.path.basename(f)}") for f in files[k:k + 200]],
                                  token=tok)
    hosp = [h for f in sorted(glob.glob(f"{work}/hosp/*.json")) for h in json.load(open(f))]
    if download:  # header fields from each file's report json (the first pack run missed CSV headers)
        os.makedirs(f"{work}/heads", exist_ok=True)
        fids = [h["fid"] for h in hosp]
        for k in range(0, len(fids), 500):
            try:
                download_bucket_files(WORK_BUCKET, files=[(f"hospitals/full/{f}.json", f"{work}/heads/{f}.json")
                                                          for f in fids[k:k + 500]], token=tok)
            except Exception as e:
                _log(f"headers: {e!r}"[:300])
        states = _site_states(work)
        for h in hosp:
            p = f"{work}/heads/{h['fid']}.json"
            if not os.path.exists(p):
                continue
            hd = _header(json.load(open(p)))
            addrs = hd.get("hospital_address") or []
            city, st, zip5 = None, None, None
            for t in [*addrs, *(hd.get("location_name") or []), hd.get("hospital_name"), h.get("address"), h.get("name")]:
                city, st, zip5 = _addr_parts(t if isinstance(t, str) else None)
                if st:
                    break
            h["name"] = h.get("name") or hd.get("hospital_name")
            h["locations"] = h.get("locations") or hd.get("location_name") or []
            h["address"] = h.get("address") or (addrs[0] if addrs else None)
            h["city"], h["zip5"] = h.get("city") or city, h.get("zip5") or zip5
            h["name"] = (h["name"] or "").strip() or None
            h["state"] = h.get("state") or next((states[c] for c in h.get("ccns") or [] if c in states), None) or st
            h["npis"] = h.get("npis") or hd.get("type_2_npi") or []
            h["last_updated"] = h.get("last_updated") or hd.get("last_updated_on")
            h["version"] = h.get("version") or hd.get("version")
            h["url"] = h.get("url") or hd.get("url")
    sites = _fetch(f"{BASE}/shop/sites/sites.parquet", f"{work}/sites.parquet")
    con = duckdb.connect()
    con.execute("CREATE TABLE h (fid VARCHAR, ccns VARCHAR[], ein VARCHAR, how VARCHAR, name VARCHAR, locations VARCHAR[],"
                " address VARCHAR, city VARCHAR, state VARCHAR, zip5 VARCHAR, npis VARCHAR[], last_updated VARCHAR,"
                " version VARCHAR, url VARCHAR, rates BIGINT, charges BIGINT)")
    con.executemany("INSERT INTO h VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(h["fid"], h.get("ccns") or [], h.get("ein"), h.get("how"), h.get("name"), [str(x) for x in h.get("locations") or []],
                      h.get("address"), h.get("city"), h.get("state"), h.get("zip5"), [str(x) for x in h.get("npis") or []],
                      h.get("last_updated"), h.get("version"), h.get("url"), h.get("rates"), h.get("charges")) for h in hosp])
    # the CMS site registry names the hospital and gives its street address when the file is attached to a CCN
    con.execute(f"""COPY (SELECT h.fid, h.ccns, h.ein, h.npis, h.how AS attached_by,
                                coalesce(h.name, s.name) AS name, s.name AS cms_name, h.locations,
                                coalesce(s.line1 || ', ' || s.city || ', ' || s.state || ' ' || s.zip5, h.address) AS address,
                                coalesce(s.city, h.city) AS city, coalesce(s.state, h.state) AS state, coalesce(s.zip5, h.zip5) AS zip5,
                                s.kind, h.last_updated, h.version, h.url, h.rates, h.charges, len(h.ccns) > 1 AS shared_file
                         FROM h LEFT JOIN (SELECT ccn, any_value(name) AS name, any_value(line1) AS line1, any_value(city) AS city,
                                                  any_value(state) AS state, any_value(zip5) AS zip5, any_value(kind) AS kind
                                           FROM '{sites}' WHERE ccn IS NOT NULL GROUP BY 1) s ON s.ccn = h.ccns[1]
                         WHERE coalesce(h.rates, 0) + coalesce(h.charges, 0) > 0
                         ORDER BY state, name) TO '{work}/out/hospitals.parquet' (FORMAT parquet)""")
    con.execute(f"COPY (SELECT * FROM read_parquet('{work}/codes/*.parquet', union_by_name = true) ORDER BY hospitals DESC) "
                f"TO '{work}/out/codes.parquet' (FORMAT parquet)")
    m = {"release": time.strftime("%Y%m%d%H%M"),
         "hospitals": con.execute(f"SELECT count(*) FROM '{work}/out/hospitals.parquet'").fetchone()[0],
         "with_ccn": con.execute(f"SELECT count(*) FROM '{work}/out/hospitals.parquet' WHERE len(ccns) > 0").fetchone()[0],
         "states": con.execute(f"SELECT count(DISTINCT state) FROM '{work}/out/hospitals.parquet'").fetchone()[0],
         "rate_rows": con.execute(f"SELECT sum(rates) FROM '{work}/out/hospitals.parquet'").fetchone()[0],
         "codes": con.execute(f"SELECT count(*) FROM '{work}/out/codes.parquet'").fetchone()[0],
         "last_updated_range": con.execute(f"SELECT min(last_updated), max(last_updated) FROM '{work}/out/hospitals.parquet' "
                                           f"WHERE regexp_matches(last_updated, '^20[0-9]{{2}}-')").fetchone()}
    json.dump(m, open(f"{work}/out/meta.json", "w"), default=str)
    if upload_to:
        from .cloudpack import upload

        upload(f"{work}/out", OUT, upload_to)
    return m


def bucket_of(code: str) -> str:
    return hashlib.md5(code.encode()).hexdigest()[:3]
