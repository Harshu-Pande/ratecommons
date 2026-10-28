"""RateCommons cloud engine: answers from small Parquet files on Hugging Face (see src/ticdata/cloudpack.py).

Each query fetches only the files it needs (one file per billing code, a few per state), caches them on the
function's local disk, and joins them with DuckDB. Reading rules: a missing rate means "no published rate",
never "out of network"; percentages are not dollars; provider identity is TIN + NPI (names from NPPES by NPI).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import duckdb
import httpx

BASE = os.environ.get("RC_DATA_URL", "https://huggingface.co/buckets/ratecommons/work/resolve/serve/v2").rstrip("/")
CACHE = os.environ.get("RC_CACHE", "/tmp/rc-cache")
CACHE_MAX = int(float(os.environ.get("RC_CACHE_GB", "0.33")) * 1e9)  # Vercel's /tmp holds 500 MB in all
PAYERS = ["cigna", "aetna", "uhc", "bcbs", "anthem"]
BLUE_PLANS = {"020": "Arkansas Blue Cross and Blue Shield", "030": "Blue Cross Blue Shield Of Arizona", "040": "Anthem Blue Cross California", "042": "Blue Shield of California", "051": "Anthem Blue Cross and Blue Shield Colorado", "062": "Anthem Blue Cross and Blue Shield Connecticut", "070": "Highmark Blue Cross Blue Shield Delaware", "102": "Anthem Blue Cross and Blue Shield Georgia", "110": "Blue Cross of Idaho", "131": "Anthem Blue Cross and Blue Shield Indiana", "140": "Wellmark Blue Cross and Blue Shield of Iowa", "141": "Wellmark Blue Cross and Blue Shield of South Dakota", "150": "Blue Cross and Blue Shield of Kansas", "170": "Blue Cross and Blue Shield of Louisiana", "182": "Anthem Blue Cross and Blue Shield Maine", "230": "Blue Cross & Blue Shield of Mississippi", "240": "Blue Cross and Blue Shield of Kansas City", "250": "Blue Cross and Blue Shield of Montana", "254": "Empire BlueCross BlueShield", "260": "Blue Cross and Blue Shield of Nebraska", "266": "Anthem Blue Cross and Blue Shield Nevada", "271": "Anthem Blue Cross and Blue Shield New Hampshire", "280": "Horizon Blue Cross Blue Shield of New Jersey", "290": "Blue Cross and Blue Shield of New Mexico", "301": "Highmark Blue Cross Blue Shield of Western New York", "302": "Excellus BlueCross BlueShield", "310": "Blue Cross and Blue Shield of North Carolina", "320": "Blue Cross Blue Shield of North Dakota", "340": "Blue Cross and Blue Shield of Oklahoma", "361": "Capital BlueCross", "362": "Independence Blue Cross", "370": "Blue Cross & Blue Shield of Rhode Island", "378": "Highmark Blue Shield Pennsylvania", "380": "BlueCross BlueShield of South Carolina", "400": "Blue Cross and Blue Shield of Texas", "410": "Regence BlueCross BlueShield of Utah", "415": "Blue Cross and Blue Shield of Vermont", "425": "Anthem Blue Cross and Blue Shield Virginia", "430": "Premera Blue Cross", "443": "Highmark Blue Cross Blue Shield West Virginia", "458": "Anthem Blue Cross and Blue Shield Wisconsin", "460": "Blue Cross Blue Shield of Wyoming", "471": "Blue Cross and Blue Shield of Hawaii", "510": "Blue Cross and Blue Shield of Alabama", "590": "Florida Blue", "611": "Regence BlueShield of Idaho", "690": "CareFirst BlueCross BlueShield", "700": "Blue Cross Blue Shield of Massachusetts", "710": "Blue Cross Blue Shield of Michigan", "720": "Blue Cross and Blue Shield of Minnesota", "748": "Anthem Blue Cross and Blue Shield Missouri", "800": "Highmark Blue Shield of Northeastern New York", "850": "Regence BlueCross BlueShield of Oregon", "890": "BlueCross BlueShield of Tennessee", "932": "Regence BlueShield of Washington", "973": "BlueCross BlueShield of Puerto Rico"}
DOLLAR_TYPES = ("negotiated", "fee schedule", "derived")
MAX_ROWS = 2000
FACILITY_POS = ("19", "21", "22", "23", "24", "26", "31", "34", "41", "42", "51", "52", "53", "56", "61")

_http = httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, connect=15.0),
                     headers={"User-Agent": "RateCommons/1"})
_lock = threading.Lock()
_meta: dict = {}
_con: duckdb.DuckDBPyConnection | None = None


# ------------------------------------------------------------------ files

def _local(path: str) -> str:
    return os.path.join(CACHE, path)


def fetch(path: str) -> str | None:
    """Local copy of BASE/path (None if it does not exist). Cached across calls of a warm instance."""
    dest = _local(path)
    if os.path.exists(dest):
        os.utime(dest)
        return dest
    if BASE.startswith("/"):
        src = os.path.join(BASE, path)
        return src if os.path.exists(src) else None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    _evict()
    tmp = f"{dest}.{threading.get_ident()}.part"
    for attempt in range(3):
        try:
            with _http.stream("GET", f"{BASE}/{path}") as r:
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            os.replace(tmp, dest)
            _evict()
            return dest
        except httpx.HTTPError:
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))
    return None


def fetch_many(paths: list[str]) -> dict[str, str | None]:
    paths = list(dict.fromkeys(paths))
    with ThreadPoolExecutor(min(16, max(1, len(paths)))) as ex:
        return dict(zip(paths, ex.map(fetch, paths)))


_pinned: set[str] = set()  # files an open run_sql view reads; never evicted while pinned


def _evict():
    files = []
    for root, _, fs in os.walk(CACHE):
        for f in fs:
            p = os.path.join(root, f)
            if p in _pinned:
                continue
            try:
                st = os.stat(p)
                files.append((st.st_atime, st.st_size, p))
            except OSError:
                pass
    total = sum(s for _, s, _ in files)
    now = time.time()
    for at, s, p in sorted(files):
        if total <= CACHE_MAX or now - at < 20:  # keep files a running query just touched
            break
        try:
            os.remove(p)
            total -= s
        except OSError:
            pass


def con() -> duckdb.DuckDBPyConnection:
    global _con
    with _lock:
        if _con is None:
            c = duckdb.connect()
            c.execute("SET enable_progress_bar = false")
            c.execute(f"SET memory_limit = '{os.environ.get('RC_MEMORY', '1700MB')}'")
            c.execute("SET threads = 4")
            c.execute("SET preserve_insertion_order = false")
            c.execute("SET temp_directory = '/tmp/rc-duck'")  # the function's working directory is read-only
            c.execute("SET max_temp_directory_size = '150MB'")
            _con = c
        return _con.cursor()


def _q(sql: str, params=None):
    cur = con()
    rel = cur.execute(sql, params or [])
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _pq(path: str | None) -> str:
    return f"read_parquet('{path}')" if path else None


# ------------------------------------------------------------------ networks

AETNA_PRODUCTS = ["Aetna Open Access Managed Choice", "Open Access Aetna Select", "Aetna Open Access Elect Choice",
                  "Aetna Choice POS II", "Open Access POS II", "Open POS II", "Aetna Select", "Managed Choice POS",
                  "Elect Choice EPO", "Aetna Signature Administrators", "Choice POS II", "Open Choice PPO",
                  "Aetna PPO", "Aetna HMO", "Managed Choice", "EPO", "PPO", "HMO", "POS"]


def _aetna_product(plan: str) -> str:
    p = re.sub(r"_\d+$", "", plan or "")
    for k in AETNA_PRODUCTS:
        if k.lower() in p.lower():
            return k if k.startswith(("Aetna", "Open")) else f"Aetna {k}"
    return "Aetna (other)"


def _label(payer: str, files: list[str], plans: list[str] | None) -> tuple[str, str]:
    name = (files or [""])[0]
    if payer == "aetna":
        prods = Counter(_aetna_product(p) for p in plans or [])
        prod = prods.most_common(1)[0][0] if prods else "Aetna"
        sponsors = [re.split(r"(?i)(HSA )?(Aetna|Open Access|Open POS|Managed Choice)", p)[0].strip() for p in plans or []]
        who = ", ".join(sorted({s for s in sponsors if s})[:3])
        return prod, f"{prod} — {who or name[11:40]}" + (f" (+{len(plans) - 3} plans)" if plans and len(plans) > 3 else "")
    stem = re.sub(r"^\d{4}[-_]\d{2}[-_]\d{2}_", "", re.sub(r"_in-network-rates.*$", "", name))
    if payer == "cigna":
        t = re.sub(r"^cigna-health-life-insurance-company_", "", stem)
        t = re.sub(r"^cigna[-_]", "", t).replace("_", " ").replace("-", " ").title()
        for a, b in (("Oap", "OAP"), ("Ppo", "PPO"), ("Ebh", "EBH"), ("Hmo", "HMO"), ("Epo", "EPO"), ("Ifp", "IFP"),
                     ("Gppo", "GPPO"), ("Sar Ii", "SAR II"), ("Nj", "NJ"), ("Fl", "FL"), ("Az", "AZ")):
            t = re.sub(rf"\b{a}\b", b, t)
        return f"Cigna {t}", f"Cigna {t}"
    parts = stem.split("_")
    if payer in ("bcbs", "anthem"):
        m = re.match(r"\d{4}-\d{2}_(\d{3})_([0-9A-Z]{4})$", re.sub(r"_\d+_of_\d+$", "", stem))
        if m:  # BlueCard file of a Blue plan's network (plan code from the file name, as checked in Oct 2026)
            plan = BLUE_PLANS.get(m.group(1), f"Blue plan {m.group(1)}")
            return f"{plan} (BlueCard)", f"{plan} BlueCard network {m.group(2)}"
        m = re.match(r"([A-Z]{2})_([A-Z0-9]+?)MED", name)
        if m:  # Anthem's own networks: <ST>_<network code>MED<suffix>.json.gz
            return f"Anthem {m.group(1)}", f"Anthem {m.group(1)} network {m.group(2)}"
        m = re.match(r"Blue-Cross-and-Blue-Shield-of-([A-Za-z-]+?)_(.+)$", stem)
        if m:  # HCSC: <date>_Blue-Cross-and-Blue-Shield-of-<State>_<network>
            st = {"Illinois": "IL", "Texas": "TX", "Montana": "MT", "New-Mexico": "NM", "Oklahoma": "OK"}.get(m.group(1), m.group(1))
            net = m.group(2).replace("-", " ")
            return f"BCBS{st} {net.split('  ')[0][:40]}", f"BCBS{st} {net}"
        return payer, stem
    if payer == "uhc":
        prod = (parts[2] if len(parts) > 2 else stem).replace("-", " ").replace("Ppo", "PPO")
        return f"UHC {prod}", f"UHC {prod} ({' '.join(parts[0:2])} {parts[3] if len(parts) > 3 else ''})".strip()
    return payer, stem


def meta(p: str) -> dict | None:
    if p not in _meta:
        path = fetch(f"{p}/meta.json")
        if not path:
            _meta[p] = None
            return None
        m = json.load(open(path))
        for n in m["networks"]:
            n["product"], n["label"] = _label(p, n.get("file_names") or [], n.get("plan_names") or [])
        rows = [(p, n["net"], n["product"], n["label"], len(n.get("plan_names") or []), n.get("file_names") or [],
                 n.get("plan_names") or []) for n in m["networks"]]
        cur = con()
        cur.execute(f"CREATE OR REPLACE TABLE netlabel_{p} (payer VARCHAR, net INTEGER, product VARCHAR, label VARCHAR, "
                    "n_plans INTEGER, file_names VARCHAR[], plan_names VARCHAR[])")
        if rows:
            cur.executemany(f"INSERT INTO netlabel_{p} VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        ns = fetch(f"{p}/ns.parquet")
        cur.execute(f"CREATE OR REPLACE TABLE ns_{p} AS SELECT * FROM read_parquet('{ns}')")
        cx = fetch(f"{p}/codes.parquet")
        cur.execute(f"CREATE OR REPLACE TABLE codes_{p} AS SELECT * FROM read_parquet('{cx}')")
        _meta[p] = m
    return _meta[p]


def payers_loaded() -> list[str]:
    with ThreadPoolExecutor(3) as ex:
        ok = list(ex.map(meta, PAYERS))
    return [p for p, m in zip(PAYERS, ok) if m]


def _payers(payer: str | None) -> list[str]:
    have = payers_loaded()
    if not payer or payer.lower() in ("all", "any", ""):
        return have
    want = [x.strip().lower().replace("unitedhealthcare", "uhc").replace("united", "uhc") for x in payer.split(",")]
    return [p for p in have if p in want]


def _st(state: str | None) -> str:
    s = (state or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", s):
        raise ValueError("state must be a two-letter code, e.g. 'TX'")
    return s


def _code(code: str) -> str:
    c = (code or "").strip().upper()
    if not re.fullmatch(r"[0-9A-Z.\-]{1,12}", c):
        raise ValueError(f"bad billing code {code!r}")
    return c


def _lit(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


# ------------------------------------------------------------------ core

def _code_files(p: str, codes: list[str], code_type: str | None) -> list[str]:
    cl = ", ".join(_lit(c) for c in codes)
    rows = _q(f"SELECT t, k FROM codes_{p} WHERE billing_code IN ({cl})"
              + (f" AND billing_code_type = {_lit(code_type.upper())}" if code_type else ""))
    return [f"{p}/code/{r['t']}/{r['k']}.parquet" for r in rows]


def _place_mask_sql(place: str, modifier: str = "") -> str:
    pos = "string_split(coalesce(pos, ''), ',')"
    anyplace = "(coalesce(pos, '') = '' OR pos LIKE 'CSTM%')"
    m = re.sub(r"[^A-Z0-9]", "", (modifier or "").upper())[:2]
    mod = f"modifiers = '{m}'" if m else "coalesce(modifiers, '') = ''"
    if place == "any":
        return f"{mod}" if m else "true"
    if place == "facility":
        return f"{mod} AND (list_has_any({pos}, {list(FACILITY_POS)}) OR {anyplace})"
    return f"{mod} AND (list_contains({pos}, '11') OR {anyplace})"


def _rows(p: str, codes: list[str], state: str, code_type=None, network=None, city=None, zip_prefix=None,
          specialty=None, provider=None, billing_class=None, where: str = "true", select: str | None = None,
          group: str | None = None, limit: int | None = None, pg_where: str | None = None, copy_to: str | None = None,
          by_product: bool = True):
    """Rows (product, provider group, price) for codes in one state for one payer, optionally aggregated."""
    if not meta(p):
        return None if copy_to else []
    cf = _code_files(p, codes, code_type)
    if meta(p).get("pspli") == "bucket3":  # provider sets bucketed by the first 3 characters of the code key
        def bucket(f: str) -> str:
            t, k = f.split("/")[-2], f.rsplit("/", 1)[1][:-8]
            return f"{p}/state/{state}/pspli/" + ("_cstm_all.parquet" if t == "CSTM-ALL" else f"{t}/{k[:3]}.parquet")
        psf = sorted({bucket(f) for f in cf})
        if provider:
            psf.append(f"{p}/state/{state}/pspli/_cstm_all.parquet")
    else:
        psf = [f"{p}/state/{state}/pspli.parquet"]
    need = cf + psf + [f"{p}/state/{state}/{x}.parquet" for x in ("plipg", "pg")]
    if provider:
        need.append(f"{p}/cstm_all.parquet")
    loc = bool(city or zip_prefix or specialty or (provider and not re.fullmatch(r"\d{9,10}|\d{2}-\d{7}", provider.strip())))
    if loc or (provider and re.fullmatch(r"\d{10}", provider.strip())):
        need.append(f"{p}/state/{state}/pgnpi.parquet")
    if loc:
        need.append(f"shared/nppes/{state}.parquet")
    got = fetch_many(need)
    files = [got[f] for f in cf if got.get(f)]
    if provider and got.get(f"{p}/cstm_all.parquet"):
        files.append(got[f"{p}/cstm_all.parquet"])
    psl = [got[f] for f in psf if got.get(f)]
    if not files or not psl or not got.get(f"{p}/state/{state}/pg.parquet"):
        return None if copy_to else []
    S = {k: f"read_parquet('{got[f'{p}/state/{state}/{k}.parquet']}')" for k in ("plipg", "pg")}
    S["pspli"] = f"read_parquet({psl!r})"
    pv = ""
    if provider:
        v = provider.strip()
        if re.fullmatch(r"\d{10}", v):
            pv = f"SELECT DISTINCT pg FROM read_parquet('{got[f'{p}/state/{state}/pgnpi.parquet']}') WHERE npi = {int(v)}"
        elif re.fullmatch(r"\d{2}-?\d{7}", v):
            pv = f"SELECT pg FROM {S['pg']} WHERE tin = '{v.replace('-', '')}'"
        else:
            pv = (f"SELECT DISTINCT n.pg FROM read_parquet('{got[f'{p}/state/{state}/pgnpi.parquet']}') n "
                  f"JOIN read_parquet('{got[f'shared/nppes/{state}.parquet']}') x USING (npi) WHERE x.name ILIKE {_lit('%' + v + '%')}")
    locf = []
    if city:
        locf.append(f"x.city ILIKE {_lit(city.strip())}")
    if zip_prefix:
        locf.append(f"x.zip5 LIKE {_lit(zip_prefix.strip() + '%')}")
    if specialty:
        sp = _lit(f"%{specialty.strip()}%")
        locf.append(f"(x.taxonomy ILIKE {sp} OR x.classification ILIKE {sp} OR x.specialization ILIKE {sp} "
                    f"OR x.taxonomy_code = {_lit(specialty.strip())})")
    locq = ""
    if locf:
        locq = (f"SELECT DISTINCT n.pg FROM read_parquet('{got[f'{p}/state/{state}/pgnpi.parquet']}') n "
                f"JOIN read_parquet('{got[f'shared/nppes/{state}.parquet']}') x USING (npi) WHERE " + " AND ".join(locf))
    nf = ""
    if network:
        w = _lit(f"%{network}%")
        nf = (f" AND (l.product ILIKE {w} OR l.label ILIKE {w} OR list_contains(list_transform(l.plan_names, z -> z ILIKE {w}), true)"
              f" OR list_contains(list_transform(l.file_names, z -> z ILIKE {w}), true))")
    bc = f" AND f.billing_class = {_lit(billing_class.lower())}" if billing_class else ""
    sql = f"""
    WITH f AS (SELECT * FROM read_parquet({files!r}, union_by_name = true) f WHERE true {bc}),
    nets AS (SELECT DISTINCT n.ns, l.product FROM ns_{p} n JOIN netlabel_{p} l USING (net) WHERE true {nf}),
    {"pv AS (" + pv + ")," if pv else ""}
    {"lq AS (" + locq + ")," if locq else ""}
    g AS (SELECT DISTINCT s.ps, l.pg FROM {S['pspli']} s JOIN {S['plipg']} l USING (pli)
          WHERE s.ps IN (SELECT ps FROM f) {"AND l.pg IN (SELECT pg FROM pv)" if pv else ""}
          {"AND l.pg IN (SELECT pg FROM lq)" if locq else ""}
          {f"AND l.pg IN (SELECT pg FROM {S['pg']} WHERE {pg_where})" if pg_where else ""}),
    base AS ({f"""SELECT DISTINCT '{p}' AS payer, nets.product, g.pg, f.code, f.negotiated_type, round(f.rate, 2) AS rate,
                    f.rate_raw, f.billing_class, f.setting, f.modifiers, f.pos, f.expiration
             FROM f JOIN nets USING (ns) JOIN g USING (ps)""" if by_product else
             f"""SELECT DISTINCT '{p}' AS payer, g.pg, f.code, f.negotiated_type, round(f.rate, 2) AS rate,
                    f.rate_raw, f.billing_class, f.setting, f.modifiers, f.pos, f.expiration
             FROM f JOIN g USING (ps) WHERE f.ns IN (SELECT ns FROM nets)"""}),
    rows AS (SELECT b.*, pg.tin, pg.name AS provider, pg.n_npi AS npis_in_area, pg.cities, pg.specialty, pg.tin_wide
             FROM base b JOIN {S['pg']} pg USING (pg) WHERE {where})
    SELECT {select or '*'} FROM rows {('GROUP BY ' + group) if group else ''} {('LIMIT ' + str(int(limit))) if limit else ''}
    """
    if copy_to:  # into a Parquet file (run_sql): returns the row count
        return con().execute(f"COPY ({sql}) TO '{copy_to}' (FORMAT parquet, COMPRESSION zstd)").fetchone()[0]
    return _q(sql)


def _for_payers(payer, fn) -> list[dict]:
    ps = _payers(payer)
    with ThreadPoolExecutor(max(1, len(ps))) as ex:
        out = list(ex.map(fn, ps))
    return [r for part in out for r in part]


def _codes(code: str) -> list[str]:
    cs = [_code(c) for c in str(code).split(",") if c.strip()][:50]
    if not cs:
        raise ValueError("give at least one billing code")
    return cs


_mcr_ready = False


def _mcr(codes: list[str], state: str) -> dict:
    """{(code, modifier): (nonfacility, facility)} for the state (mean locality GPCI) or national."""
    global _mcr_ready
    if not _mcr_ready:
        path = fetch("shared/medicare.parquet")
        con().execute(f"CREATE OR REPLACE TABLE mcr AS SELECT * FROM read_parquet('{path}')")
        _mcr_ready = True
    rows = _q(f"""SELECT hcpcs, coalesce(modifier, '') m, state, nonfacility_amount nf, facility_amount fa FROM mcr
                  WHERE hcpcs IN ({', '.join(_lit(c) for c in codes)}) AND state IN ({_lit(state)}, 'US')""")
    out: dict = {}
    for r in sorted(rows, key=lambda r: r["state"] != "US"):  # state rows win
        out[(r["hcpcs"], r["m"])] = (r["nf"] if r["nf"] and r["nf"] > 0 else None, r["fa"] if r["fa"] and r["fa"] > 0 else None)
    return out


def _with_medicare(rows: list[dict], state: str) -> list[dict]:
    if not rows:
        return rows
    m = _mcr(sorted({r["code"] for r in rows}), state)
    for r in rows:
        mods = (r.get("modifiers") or "").split(",")
        mod = "26" if "26" in mods else ("TC" if "TC" in mods else "")
        nf, fa = m.get((r["code"], mod), (None, None))
        pos = (r.get("pos") or "").split(",")
        fac = r.get("setting") == "inpatient" or any(x in FACILITY_POS[:5] for x in pos)
        med = fa if fac else nf
        prof = r.get("billing_class") == "professional" and r.get("negotiated_type") in DOLLAR_TYPES
        r["medicare"] = med if prof else None
        r["pct_of_medicare"] = round(100 * r["rate"] / med) if prof and med and r.get("rate") is not None else None
    return rows


def _quantiles(vals: list[float]) -> dict:
    v = sorted(vals)
    n = len(v)

    def q(p):
        if n == 0:
            return None
        k = (n - 1) * p
        lo, hi = int(k), min(int(k) + 1, n - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 2)
    return {"min": v[0] if n else None, "p10": q(.1), "p25": q(.25), "median": q(.5), "p75": q(.75), "p90": q(.9),
            "max": v[-1] if n else None, "mean": round(sum(v) / n, 2) if n else None}


# ------------------------------------------------------------------ tools

def lookup_rates(code, state, payer="all", network="", city="", zip_prefix="", specialty="", provider="",
                 billing_class="", limit=200):
    codes, state = _codes(code), _st(state)
    n = min(int(limit or 200), MAX_ROWS)
    rows = _for_payers(payer, lambda p: _rows(p, codes, state, None, network or None, city or None, zip_prefix or None,
                                              specialty or None, provider or None, billing_class or None, limit=n))
    rows = sorted(rows, key=lambda r: (r["payer"], r["product"] or "", r["negotiated_type"] or "", r["rate"] or 0))[:n]
    for r in rows:
        r.pop("pg", None)
    return _with_medicare(rows, state)


def _per_pg_sql(place: str, modifier: str) -> tuple[str, str]:
    where = (f"negotiated_type IN {DOLLAR_TYPES} AND rate IS NOT NULL AND " + _place_mask_sql(place, modifier))
    return where, "payer, product, billing_class, setting, code, pg, median(rate) AS rate"


def market_distribution(code, state, payer="all", network="", city="", zip_prefix="", specialty="",
                        billing_class="professional", group_by="payer", place="office", modifier=""):
    code, state = _code(code), _st(state)
    where, sel = _per_pg_sql(place, modifier)
    per = _for_payers(payer, lambda p: _rows(p, [code], state, None, network or None, city or None, zip_prefix or None,
                                             specialty or None, None, billing_class or None, where=where, select=sel,
                                             group="payer, product, billing_class, setting, code, pg"))
    keys = {"payer": ["payer"], "product": ["payer", "product"], "network": ["payer", "product"],
            "setting": ["payer", "billing_class", "setting"], "none": []}.get(group_by or "payer", ["payer"])
    groups: dict = {}
    for r in per:
        groups.setdefault(tuple(r[k] for k in keys), {}).setdefault(r["pg"], []).append(r["rate"])
    m = _mcr([code], state)
    mod = re.sub(r"[^A-Z0-9]", "", (modifier or "").upper())[:2]
    nf, fa = m.get((code, mod), (None, None))
    med = fa if place == "facility" else nf
    out = []
    for k, pgs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        vals = [sorted(v)[len(v) // 2] for v in pgs.values()]  # one value per provider group
        row = dict(zip(keys, k))
        row.update({"state": state, "code": code, "provider_groups": len(pgs), **_quantiles(vals), "medicare": med,
                    "place": place, "modifier": mod or "none"})
        row["median_pct_of_medicare"] = round(100 * row["median"] / med) if med and row["median"] else None
        out.append(row)
    return out


def provider_rates(provider, codes, state, payer="all", network=""):
    cs, state = _codes(codes), _st(state)
    rows = _for_payers(payer, lambda p: _rows(
        p, cs, state, None, network or None, None, None, None, provider, None,
        where=f"negotiated_type IN {DOLLAR_TYPES + ('per diem',)}",
        select="payer, tin, code, modifiers, negotiated_type, billing_class, rate, any_value(provider) AS provider, "
               "any_value(left(pos, 24)) AS pos, any_value(setting) AS setting, count(DISTINCT product) AS networks, "
               "list(DISTINCT product)[1:3] AS example_networks",
        group="payer, tin, code, modifiers, negotiated_type, billing_class, rate"))
    rows = sorted(rows, key=lambda r: (r["code"], r["payer"], r["modifiers"] or "", r["rate"] or 0))[:400]
    return _with_medicare(rows, state)


STATES = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA",
          "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR",
          "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR"]


def rank_providers(codes, state="US", payer="cigna,uhc", specialty="", weights="", place="office", modifier="",
                   min_codes=0, limit=25):
    cs = _codes(codes)[:20]
    ws = [float(x) for x in str(weights).split(",") if x.strip()] if weights else []
    ws = ws if len(ws) == len(cs) else [1.0] * len(cs)
    w = dict(zip(cs, ws))
    st = (state or "US").strip().upper()
    states = STATES if st in ("US", "ALL", "") else [_st(x) for x in st.split(",") if x.strip()]
    # placeholder amounts payers publish ($0.01, $99,999.xx, $999,999.xx) would top any ranking
    where = (f"negotiated_type IN {DOLLAR_TYPES} AND rate > 0.01 AND rate < 99999 AND rate_raw NOT LIKE '9999%' AND "
             + _place_mask_sql(place, modifier))
    pg_where = f"specialty ILIKE {_lit('%' + specialty.strip() + '%')}" if specialty else None
    payers = _payers(payer)
    jobs = [(p, s) for p in payers for s in states]
    t0 = time.time()

    def one(job):
        p, s = job
        if time.time() - t0 > 100:
            return [{"_skipped": f"{p}/{s}", "_state": s}]
        try:
            return _rows(p, cs, s, where=where, pg_where=pg_where,
                         select="payer, tin, any_value(provider) AS provider, any_value(specialty) AS specialty, code, "
                                "median(rate) AS rate", group="payer, tin, code")
        except Exception as e:
            return [{"_skipped": f"{p}/{s}: {e}"}]
    with ThreadPoolExecutor(2) as ex:  # a 2 GB function: more parallel joins ran it out of memory
        parts = list(ex.map(one, jobs))
    skipped = [r["_skipped"] for part in parts for r in part if "_skipped" in r]
    per: dict = {}
    for part in parts:
        for r in part:
            if "_skipped" in r:
                continue
            per.setdefault((r["payer"], r["tin"]), {"provider": r["provider"], "specialty": r["specialty"], "codes": {}})
            per[(r["payer"], r["tin"])]["codes"].setdefault(r["code"], []).append(r["rate"])
    mod = re.sub(r"[^A-Z0-9]", "", (modifier or "").upper())[:2]
    mcr = _mcr(cs, "US")
    need = int(min_codes or max(1, (len(cs) + 1) // 2))
    out = []
    for (py, tin), v in per.items():
        rates = {c: sorted(x)[len(x) // 2] for c, x in v["codes"].items()}
        if len(rates) < need:
            continue
        tw = sum(w[c] for c in rates)
        wavg = sum(w[c] * r for c, r in rates.items()) / tw
        pcts = {c: 100 * r / mcr[(c, mod)][0] for c, r in rates.items() if (c, mod) in mcr and mcr[(c, mod)][0]}
        wpct = sum(w[c] * x for c, x in pcts.items()) / sum(w[c] for c in pcts) if pcts else None
        out.append({"payer": py, "tin": tin, "provider": v["provider"], "specialty": v["specialty"],
                    "codes_with_rates": len(rates), "weighted_avg_rate": round(wavg, 2),
                    "weighted_pct_of_medicare": round(wpct) if wpct else None,
                    "rates": {c: round(r, 2) for c, r in sorted(rates.items())}})
    out.sort(key=lambda r: -(r["weighted_pct_of_medicare"] or 0))
    head = out[:min(int(limit or 25), 200)]
    left = sorted({r["_state"] for part in parts for r in part if "_state" in r})
    note = {"payer": "_summary", "groups_ranked": len(out), "states": len(states) - len(left), "codes": cs, "weights": ws,
            "states_not_done": ",".join(left) or None,
            "how_to_continue": "call again with state=<states_not_done> and merge" if left else None,
            "ranked_by": "weighted % of national Medicare (PFS)", "skipped": skipped[:20],
            "excluded": "placeholder amounts ($0.01, $9999x)"}
    return [note] + head


def compare_providers(codes, state, providers, payer="all", network="", place="office"):
    state = _st(state)
    out = []
    for pv in [x.strip() for x in providers.split(",") if x.strip()][:10]:
        rows = provider_rates(pv, codes, state, payer, network)
        rows = [r for r in rows if r["negotiated_type"] in DOLLAR_TYPES and _place_ok(r, place)]
        if not rows:
            out.append({"provider_query": pv, "result": "no published rate found"})
            continue
        grp: dict = {}
        for r in rows:
            grp.setdefault((r["code"], r["payer"], r["tin"], r["billing_class"]), []).append(r)
        for (c, py, tin, bc), g in sorted(grp.items()):
            vals = sorted(x["rate"] for x in g)
            med = g[0]["medicare"]
            mid = vals[len(vals) // 2]
            out.append({"provider_query": pv, "code": c, "payer": py, "tin": tin, "provider": g[0]["provider"],
                        "billing_class": bc, "median_rate": mid, "min_rate": vals[0], "max_rate": vals[-1],
                        "medicare": med, "pct_of_medicare": round(100 * mid / med) if med else None})
    return out


def _place_ok(r: dict, place: str) -> bool:
    if place == "any":
        return True
    if r.get("modifiers"):
        return False
    pos = (r.get("pos") or "")
    if pos == "" or pos.startswith("CSTM"):
        return True
    xs = pos.split(",")
    return any(x in FACILITY_POS for x in xs) if place == "facility" else "11" in xs


def benchmark_provider(provider, codes, state, payer="all", specialty="", network="", place="office"):
    state = _st(state)
    out = []
    mine_all = provider_rates(provider, codes, state, payer, network)
    for c in _codes(codes)[:20]:
        where, sel = _per_pg_sql(place, "")
        per = _for_payers(payer, lambda p: _rows(p, [c], state, None, network or None, None, None, specialty or None,
                                                 None, "professional", where=where, select=sel,
                                                 group="payer, product, billing_class, setting, code, pg"))
        if not per:
            out.append({"code": c, "result": "no published rates in this state"})
            continue
        by_pg: dict = {}
        for r in per:  # one value per provider group (its median across products)
            by_pg.setdefault(r["payer"], {}).setdefault(r["pg"], []).append(r["rate"])
        peers = {py: [sorted(v)[len(v) // 2] for v in g.values()] for py, g in by_pg.items()}
        mine = [r for r in mine_all if r["code"] == c and r["negotiated_type"] in DOLLAR_TYPES and _place_ok(r, place)
                and r["billing_class"] == "professional"]
        if not mine:
            out.append({"code": c, "result": f"no published rate for {provider} in {state}"})
            continue
        for py in sorted({r["payer"] for r in mine}):
            vals = sorted(r["rate"] for r in mine if r["payer"] == py)
            r0 = vals[len(vals) // 2]
            pr = sorted(peers.get(py, []))
            q = _quantiles(pr)
            med = next((r["medicare"] for r in mine if r["payer"] == py and r["medicare"]), None)
            out.append({"code": c, "payer": py, "provider": mine[0]["provider"], "tin": mine[0]["tin"], "your_rate": r0,
                        "peer_groups": len(pr), "peer_p25": q["p25"], "peer_median": q["median"], "peer_p75": q["p75"],
                        "percentile": round(100 * sum(1 for x in pr if x < r0) / len(pr)) if pr else None,
                        "medicare": med, "your_pct_of_medicare": round(100 * r0 / med) if med else None,
                        "peer_median_pct_of_medicare": round(100 * q["median"] / med) if med and q["median"] else None})
    return out


def network_breadth(state, specialty="", city="", zip_prefix="", payer="all", group_by="product"):
    state = _st(state)
    npp = fetch(f"shared/nppes/{state}.parquet")
    f = ["true"]
    if specialty:
        sp = _lit(f"%{specialty.strip()}%")
        f.append(f"(x.taxonomy ILIKE {sp} OR x.classification ILIKE {sp} OR x.specialization ILIKE {sp} "
                 f"OR x.taxonomy_code = {_lit(specialty.strip())})")
    if city:
        f.append(f"x.city ILIKE {_lit(city.strip())}")
    if zip_prefix:
        f.append(f"x.zip5 LIKE {_lit(zip_prefix.strip() + '%')}")
    cond = " AND ".join(f)
    total = _q(f"SELECT count(*) n FROM read_parquet('{npp}') x WHERE {cond}")[0]["n"]
    key = "l.label" if group_by == "network" else "l.product"

    def one(p):
        if not meta(p):
            return []
        got = fetch_many([f"{p}/state/{state}/{x}.parquet" for x in ("pgnpi", "pgnet", "pg")])
        if not all(got.values()):
            return []
        return _q(f"""SELECT '{p}' payer, {key} AS {"network" if group_by == "network" else "product"},
                        count(DISTINCT n.npi) AS clinicians, count(DISTINCT pg.tin) AS tins
                      FROM read_parquet('{got[f"{p}/state/{state}/pgnpi.parquet"]}') n
                      JOIN read_parquet('{npp}') x USING (npi)
                      JOIN read_parquet('{got[f"{p}/state/{state}/pgnet.parquet"]}') m USING (pg)
                      JOIN netlabel_{p} l USING (net)
                      JOIN read_parquet('{got[f"{p}/state/{state}/pg.parquet"]}') pg USING (pg)
                      WHERE {cond} GROUP BY ALL ORDER BY clinicians DESC""")
    rows = _for_payers(payer, one)
    for r in rows:
        r["nppes_clinicians_in_area"] = total
        r["share_of_area_pct"] = round(100 * r["clinicians"] / max(total, 1), 1)
    return rows


def _npi_state(npi: int) -> str | None:
    path = fetch(f"shared/npi/{str(npi)[:3]}.parquet")
    if not path:
        return None
    r = _q(f"SELECT state FROM read_parquet('{path}') WHERE npi = {int(npi)}")
    return r[0]["state"] if r else None


def provider_networks(provider, state=""):
    v = provider.strip()
    out = []
    for p in payers_loaded():
        if re.fullmatch(r"\d{2}-?\d{7}", v):
            tinp = fetch(f"{p}/tin.parquet")
            st = [state.upper()] if state else (_q(f"SELECT states FROM read_parquet('{tinp}') WHERE tin = '{v.replace('-', '')}'")
                                                or [{"states": []}])[0]["states"]
            cond = f"pg.tin = '{v.replace('-', '')}'"
        elif re.fullmatch(r"\d{10}", v):
            st = [state.upper()] if state else [s for s in [_npi_state(int(v))] if s]
            cond = None
        else:
            if not state:
                raise ValueError("searching by name needs a state")
            st, cond = [_st(state)], None
        for s in st[:10]:
            got = fetch_many([f"{p}/state/{s}/{x}.parquet" for x in ("pg", "pgnet", "pgnpi")] + [f"shared/nppes/{s}.parquet"])
            if not got.get(f"{p}/state/{s}/pg.parquet"):
                continue
            G = {k: f"read_parquet('{got[f'{p}/state/{s}/{k}.parquet']}')" for k in ("pg", "pgnet", "pgnpi")}
            if cond is None and re.fullmatch(r"\d{10}", v):
                c2 = f"pg.pg IN (SELECT pg FROM {G['pgnpi']} WHERE npi = {int(v)})"
            elif cond is None:
                c2 = (f"pg.pg IN (SELECT n.pg FROM {G['pgnpi']} n JOIN read_parquet('{got[f'shared/nppes/{s}.parquet']}') x "
                      f"USING (npi) WHERE x.name ILIKE {_lit('%' + v + '%')})")
            else:
                c2 = cond
            out += _q(f"""SELECT '{p}' payer, '{s}' state, l.product, count(DISTINCT l.net) AS networks,
                                 list(DISTINCT pg.tin)[1:5] AS tins, any_value(l.label) AS example_network
                          FROM {G['pg']} pg JOIN {G['pgnet']} m USING (pg) JOIN netlabel_{p} l USING (net)
                          WHERE {c2} GROUP BY ALL ORDER BY networks DESC""")
    return out


def find_plans(query, payer="all"):
    w = _lit(f"%{query.strip()}%")
    out = []
    for p in _payers(payer):
        out += _q(f"""SELECT payer, product, label, n_plans, list_filter(plan_names, z -> z ILIKE {w})[1:10] AS matching_plans,
                             file_names[1:3] AS files FROM netlabel_{p}
                      WHERE product ILIKE {w} OR label ILIKE {w} OR list_contains(list_transform(plan_names, z -> z ILIKE {w}), true)
                         OR list_contains(list_transform(file_names, z -> z ILIKE {w}), true)
                      ORDER BY product LIMIT 300""")
    return out


def list_products(payer="all"):
    out = []
    for p in _payers(payer):
        out += _q(f"SELECT payer, product, count(*) AS networks, sum(n_plans) AS plans FROM netlabel_{p} "
                  "GROUP BY ALL ORDER BY networks DESC")
    return out


def search_providers(name="", state="", specialty="", city="", npi="", limit=50):
    if npi:
        s = _npi_state(int(npi))
        if not s:
            return []
        state, f = s, [f"npi = {int(npi)}"]
    else:
        state = _st(state)
        f = ["true"]
        if name:
            f.append(f"name ILIKE {_lit('%' + name.strip() + '%')}")
        if specialty:
            sp = _lit(f"%{specialty.strip()}%")
            f.append(f"(taxonomy ILIKE {sp} OR classification ILIKE {sp} OR specialization ILIKE {sp})")
        if city:
            f.append(f"city ILIKE {_lit(city.strip())}")
    npp = fetch(f"shared/nppes/{state}.parquet")
    rows = _q(f"""SELECT npi, name, credential, entity_type, city, '{state}' AS state, zip5, taxonomy_code, classification,
                         specialization FROM read_parquet('{npp}') WHERE {' AND '.join(f)} LIMIT {min(int(limit or 50), 500)}""")
    if not rows:
        return rows
    npis = ", ".join(str(int(r["npi"])) for r in rows)
    tins: dict = {}
    for p in payers_loaded():
        got = fetch_many([f"{p}/state/{state}/pgnpi.parquet", f"{p}/state/{state}/pg.parquet"])
        if not all(got.values()):
            continue
        for r in _q(f"""SELECT n.npi, list(DISTINCT g.tin) tins FROM read_parquet('{got[f"{p}/state/{state}/pgnpi.parquet"]}') n
                        JOIN read_parquet('{got[f"{p}/state/{state}/pg.parquet"]}') g USING (pg)
                        WHERE n.npi IN ({npis}) GROUP BY 1"""):
            tins.setdefault(r["npi"], []).append(f"{p}: {','.join(sorted(r['tins'])[:6])}")
    for r in rows:
        r["tins_by_payer"] = "; ".join(tins.get(r["npi"], [])) or None
    return rows


def code_info(code):
    c = _code(code)
    out = []
    for p in payers_loaded():
        out += _q(f"SELECT '{p}' payer, billing_code_type, billing_code, any_value(name) AS name, sum(n) AS published_rows "
                  f"FROM codes_{p} WHERE billing_code = {_lit(c)} GROUP BY ALL")
    m = _mcr([c], "US")
    for (code_, mod), (nf, fa) in sorted(m.items()):
        out.append({"payer": "medicare (PFS, national)", "billing_code": code_, "modifier": mod or None,
                    "nonfacility_amount": nf, "facility_amount": fa})
    return out


def medicare_rate(codes, state="US"):
    cs = _codes(codes)
    st = (state or "US").strip().upper()
    _mcr(cs[:1], st)
    return _q(f"SELECT * FROM mcr WHERE hcpcs IN ({', '.join(_lit(c) for c in cs)}) AND state = {_lit(st)} "
              "ORDER BY hcpcs, modifier NULLS FIRST")


def data_status():
    out = {"data": BASE, "payers": {}}
    for p in PAYERS:
        m = meta(p)
        if m:
            out["payers"][p] = {"networks": len(m["networks"]), "codes": m.get("codes"), "built": m.get("built")}
    return out


# ------------------------------------------------------------------ custom SQL (sandboxed)

SQL_BUDGET = float(os.environ.get("RC_SQL_SECONDS", "240"))
SQL_MAX_BUILD_ROWS = int(os.environ.get("RC_SQL_BUILD_ROWS", "4000000"))
_RC_CALL = re.compile(r"\brc_(\w+)\s*\(((?:\s*'(?:[^']|'')*'\s*,?)*)\s*\)", re.I)
RATE_COLS = ("state, payer, pg, tin, provider, specialty, npis_in_area, tin_wide, code, negotiated_type, "
             "rate, rate_raw, billing_class, setting, modifiers, pos, expiration")


def _states_arg(x: str) -> list[str]:
    x = (x or "US").strip().upper()
    return list(STATES) if x in ("US", "ALL", "") else [_st(v) for v in x.split(",") if v.strip()]


def _rates_table(payers: str, states: str, codes: str, specialty: str = "", place: str = "any", deadline: float = 0,
                 out_dir: str = "", network: str = "", by_product: bool = False) -> tuple[list[str], int, list[str]]:
    """rc_rates: one Parquet file per payer x state under out_dir; returns (files, rows, notes)."""
    cs = _codes(codes)[:30]
    sts = _states_arg(states)
    where = "true" if (place or "any") == "any" else _place_mask_sql(place)
    pg_where = f"specialty ILIKE {_lit('%' + specialty.strip() + '%')}" if specialty else None
    jobs = [(p, st) for p in _payers(payers) for st in sts]
    files, notes, total = [], [], [0]
    os.makedirs(out_dir, exist_ok=True)

    def one(job):
        p, st = job
        if time.time() > deadline or total[0] > SQL_MAX_BUILD_ROWS:
            return job, None, "not loaded (time or size limit): run again for this state"
        f = f"{out_dir}/{p}-{st}.parquet"
        try:
            cols = RATE_COLS.replace("payer, pg,", "payer, product, pg,") if by_product else RATE_COLS
            n = _rows(p, cs, st, where=where, pg_where=pg_where, copy_to=f, select=f"'{st}' AS " + cols,
                      network=network or None, by_product=by_product)
            if n:
                total[0] += n
                return job, (f, n), None
            if os.path.exists(f):
                os.remove(f)
            return job, None, None
        except Exception as e:
            return job, None, f"error: {e}"[:200]
    with ThreadPoolExecutor(2 if len(jobs) > 4 else max(1, len(jobs))) as ex:
        for (p, st), got, err in ex.map(one, jobs):
            if err:
                notes.append(f"{p}/{st}: {err}")
            elif got:
                files.append(got[0])
    return files, total[0], notes


def run_sql(sql, max_rows=500):
    t0 = time.time()
    deadline = t0 + SQL_BUDGET - 45  # leave time for the query itself
    sql = str(sql or "").strip().rstrip(";")
    if not sql:
        raise ValueError("give a SELECT query")
    max_rows = max(1, min(int(max_rows or 500), 5000))
    calls: dict = {}

    def repl(m):
        fn = m.group(1).lower()
        args = tuple(a.replace("''", "'") for a in re.findall(r"'((?:[^']|'')*)'", m.group(2)))
        if (fn, args) not in calls:
            calls[(fn, args)] = f"rc_t{len(calls)}"
        return calls[(fn, args)]
    body = _RC_CALL.sub(repl, sql)
    if re.search(r"\brc_\w+\s*\(", body, re.I):
        raise ValueError("rc_* functions take only quoted string arguments, e.g. rc_rates('cigna', 'MO', '99213')")
    sb = duckdb.connect()
    sb.execute("SET enable_progress_bar = false")
    sb.execute(f"SET memory_limit = '{os.environ.get('RC_SQL_MEMORY', '1100MB')}'")
    sb.execute("SET threads = 4")
    os.makedirs("/tmp/rc-duck-sql", exist_ok=True)
    sb.execute("SET temp_directory = '/tmp/rc-duck-sql'")
    sb.execute("SET max_temp_directory_size = '120MB'")
    os.makedirs(CACHE, exist_ok=True)
    import shutil
    import uuid

    work = os.path.realpath(f"/tmp/rc-sql/{uuid.uuid4().hex}")
    os.makedirs(work)
    sb.execute(f"SET allowed_directories = ['{os.path.realpath(CACHE)}/', '{work}/']")
    notes, built, pins = [], {}, []

    def view(name, path_rel, where=""):
        f = fetch(path_rel)
        if not f:
            sb.execute(f"CREATE VIEW {name} AS SELECT NULL::INTEGER AS no_data WHERE false")
            notes.append(f"{path_rel}: no such file")
            return
        f = os.path.realpath(f)
        _pinned.add(f)
        pins.append(f)
        sb.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{f}') {where}")

    def views_union(name, rels, extra_cols: dict | None = None):
        got = fetch_many(rels)
        sels = []
        for r in rels:
            if got.get(r):
                f = os.path.realpath(got[r])
                _pinned.add(f)
                pins.append(f)
                cols = "".join(f", {_lit(v)} AS {k}" for k, v in (extra_cols or {}).get(r, {}).items())
                sels.append(f"SELECT *{cols} FROM read_parquet('{f}')")
        sb.execute(f"CREATE VIEW {name} AS " + (" UNION ALL BY NAME ".join(sels) if sels
                                                 else "SELECT NULL::INTEGER AS no_data WHERE false"))
    try:
        for (fn, args), name in calls.items():
            a = list(args) + [""] * 5
            if fn in ("rates", "rates_by_product"):
                if fn == "rates_by_product" and len(_states_arg(a[1])) > 3:
                    raise ValueError("rc_rates_by_product takes up to 3 states; use rc_rates for national questions")
                fs, n, nt = _rates_table(a[0] or "all", a[1], a[2], a[3], a[4] or "any", deadline, f"{work}/{name}",
                                         network=a[5], by_product=fn == "rates_by_product")
                notes += nt
                sb.execute(f"CREATE VIEW {name} AS " + (f"SELECT * FROM read_parquet({fs!r}, union_by_name = true)" if fs else
                           "SELECT NULL::VARCHAR AS state, NULL::VARCHAR AS payer, NULL::VARCHAR AS tin, NULL::VARCHAR AS code, "
                           "NULL::DOUBLE AS rate WHERE false"))
                built[f"rc_rates{args}"] = n
            elif fn in ("groups", "group_npis", "group_networks"):
                x = {"groups": "pg", "group_npis": "pgnpi", "group_networks": "pgnet"}[fn]
                rels, extra = [], {}
                for p in _payers(a[0] or "all"):
                    for st in _states_arg(a[1])[:60]:
                        r = f"{p}/state/{st}/{x}.parquet"
                        rels.append(r)
                        extra[r] = {"payer": p, "state": st}
                views_union(name, rels, extra)
            elif fn == "nppes":
                sts = _states_arg(a[0])
                if len(sts) > 6:
                    raise ValueError("rc_nppes takes up to 6 states at a time")
                views_union(name, [f"shared/nppes/{st}.parquet" for st in sts])
            elif fn == "medicare":
                st = (a[0] or "US").strip().upper()
                view(name, "shared/medicare.parquet", f"WHERE state = {_lit(st)}")
            elif fn in ("codes", "products"):
                fs = []
                for p in _payers(a[0] or "all"):
                    meta(p)
                    q = (f"SELECT '{p}' AS payer, billing_code_type, billing_code, name, n AS published_rows FROM codes_{p}"
                         if fn == "codes" else
                         f"SELECT '{p}' AS payer, net, product, label, n_plans, plan_names, file_names FROM netlabel_{p}")
                    fs.append(f"{work}/{name}-{p}.parquet")
                    con().execute(f"COPY ({q}) TO '{fs[-1]}' (FORMAT parquet)")
                sb.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet({fs!r}, union_by_name = true)")
            elif fn == "code_file":
                p = _payers(a[0])[0]
                cf = _code_files(p, [_code(a[1])], None)
                views_union(name, cf)
            else:
                raise ValueError(f"unknown function rc_{fn}; see the tool description")
        sb.execute("SET enable_external_access = false")
        sb.execute("SET lock_configuration = true")
        stmts = sb.extract_statements(body)
        if len(stmts) != 1 or stmts[0].type != duckdb.StatementType.SELECT:
            raise ValueError("only one read-only SELECT (or WITH ... SELECT) statement is allowed")
        left = max(15.0, t0 + SQL_BUDGET - time.time())
        timer = threading.Timer(left, sb.interrupt)
        timer.start()
        try:
            rel = sb.execute(f"SELECT * FROM ({body}) LIMIT {max_rows + 1}")
            cols = [d[0] for d in rel.description]
            data = rel.fetchall()
        except duckdb.InterruptException:
            raise ValueError(f"the query ran past {int(SQL_BUDGET)} s; narrow it (fewer states/codes, filters)")
        finally:
            timer.cancel()
    finally:
        for f in pins:
            _pinned.discard(f)
        sb.close()
        shutil.rmtree(work, ignore_errors=True)
    rows = [dict(zip(cols, r)) for r in data[:max_rows]]
    return {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": len(data) > max_rows,
            "built": built, "notes": notes[:30], "seconds": round(time.time() - t0, 1)}
