"""Hospital price transparency tools: each hospital's own published standard charges (45 CFR 180), every code.

Data: BASE/hospital/ (built by src/ticdata/hospack.py from the dataset ratecommons/hospitals):
  hospitals.parquet          one row per hospital file: fid, ccns, ein, npis, name, address, city, state, zip5, url, ...
  codes.parquet              code, code_type, hospitals, states, rows, hospitals_with_charges, example_description
  rates/<md5(code)[:3]>.parquet    per hospital x code x setting x payer/plan: dmin/dmax (dollars), pct (% of charges),
                             est (pct x the item's gross charge), alg, med/p10/p90 (allowed amounts on claims), claims, ...
  charges/<md5(code)[:3]>.parquet  per hospital x code x setting: descr, gross (chargemaster), cash (discounted cash)

The insurer files (lookup_rates & co.) and these hospital files describe the same contracts from two sides; the
hospital_vs_insurer tool puts them next to each other.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading

import _rc as E

H = "hospital"
_lock = threading.Lock()
_state: dict = {}
CARRIERS = ("aetna", "cigna", "uhc", "anthem", "bcbs", "humana", "kaiser", "centene", "molina", "oscar", "devoted",
            "clover", "alignment", "caresource", "tricare", "medicare", "multiplan", "amerihealth", "medica",
            "healthpartners", "upmc")
PROGRAMS = ("commercial", "medicare_advantage", "medicaid", "medicare", "tricare", "va", "workers_comp", "self_pay")
PLACEHOLDER = 9_999_999  # some hospitals publish 99,999,999 for "not applicable"


def _norm_code(c: str) -> str:
    c = E._code(c)
    return c.lstrip("0").zfill(3) if c.isdigit() and len(c) <= 4 and len(c.lstrip("0")) <= 3 else c


def _bucket(c: str) -> str:
    return hashlib.md5(c.encode()).hexdigest()[:3]


def meta() -> dict | None:
    with _lock:
        if "meta" in _state:
            return _state["meta"]
    p = E.fetch(f"{H}/meta.json")
    m = json.load(open(p)) if p else None
    if m:
        hp, cp = E.fetch(f"{H}/hospitals.parquet"), E.fetch(f"{H}/codes.parquet")
        cur = E.con()
        # a hospital often posts the same file at two URLs: keep one copy (identical counts and date)
        cur.execute(f"""CREATE OR REPLACE TABLE hosp AS SELECT *, coalesce(ccns[1], fid) AS hid,
                          row_number() OVER (PARTITION BY coalesce(ccns[1], fid), rates, charges, last_updated
                                             ORDER BY fid) > 1 AS dup
                        FROM read_parquet('{hp}')""")
        cur.execute(f"CREATE OR REPLACE TABLE hcodes AS SELECT * FROM read_parquet('{cp}')")
    with _lock:
        _state["meta"] = m
    return m


def refresh_if_changed() -> bool:
    """Persistent server: a new pack (meta.json changed) drops the cached hospital files and tables."""
    if not _state.get("meta"):
        return False
    try:
        r = E._http.get(f"{E.BASE}/{H}/meta.json")
        old = E._local(f"{H}/meta.json")
        if r.status_code != 200 or (os.path.exists(old) and open(old, "rb").read() == r.content):
            return False
    except Exception:
        return False
    with _lock:
        _state.clear()
        shutil.rmtree(E._local(H), ignore_errors=True)
    return True


def _need() -> dict:
    m = meta()
    if not m:
        raise ValueError("the hospital price files are not loaded on this server yet")
    return m


def _codes(code: str, code_type: str = "") -> tuple[list[str], str]:
    raw = [E._code(c) for c in str(code or "").split(",") if c.strip()][:10]
    cs = list(dict.fromkeys(x for c in raw for x in (c, _norm_code(c))))  # DRG "0470" is stored as "470"
    if not cs:
        raise ValueError("give at least one billing code (CPT/HCPCS, MS-DRG, APR-DRG or APC)")
    ct = (code_type or "").strip().upper().replace("MSDRG", "MS-DRG").replace("APRDRG", "APR-DRG")
    if ct in ("DRG",):
        ct = "MS-DRG"
    if ct and ct not in ("CPT", "HCPCS", "MS-DRG", "APR-DRG", "APC"):
        raise ValueError("code_type is one of CPT, HCPCS, MS-DRG, APR-DRG, APC")
    return cs, ct


def _files(kind: str, codes: list[str]) -> list[str]:
    got = E.fetch_many([f"{H}/{kind}/{_bucket(c)}.parquet" for c in codes])
    return [os.path.realpath(v) for v in got.values() if v]


def _hosp_where(hospital: str = "", state: str = "", city: str = "", zip_prefix: str = "") -> tuple[str, list[str]]:
    """SQL filter on table hosp (alias h), and a description of what was matched."""
    hv = (hospital or "").strip()
    f = ["true" if re.fullmatch(r"[0-9a-f]{16}", hv) else "NOT h.dup"]
    if state and state.strip().upper() not in ("US", "ALL"):
        f.append(f"h.state = {E._lit(E._st(state))}")
    if city:  # "St. Louis" = "SAINT LOUIS" = "ST LOUIS"
        c = re.sub(r"[^A-Z]", "", city.upper()).replace("SAINT", "ST")
        f.append(f"replace(regexp_replace(upper(h.city), '[^A-Z]', '', 'g'), 'SAINT', 'ST') = {E._lit(c)}")
    if zip_prefix:
        z = re.sub(r"\D", "", zip_prefix)[:5]
        if z:
            f.append(f"h.zip5 LIKE {E._lit(z + '%')}")
    if hv:
        if re.fullmatch(r"[0-9]{2}[0-9A-Z][0-9]{3}", hv.upper()):  # CMS Certification Number
            f.append(f"list_contains(h.ccns, {E._lit(hv.upper())})")
        elif re.fullmatch(r"\d{2}-?\d{7}", hv):  # EIN
            f.append(f"h.ein = {E._lit(hv.replace('-', ''))}")
        elif re.fullmatch(r"\d{10}", hv):  # type-2 NPI
            f.append(f"list_contains(h.npis, {E._lit(hv)})")
        elif re.fullmatch(r"[0-9a-f]{16}", hv):
            f.append(f"h.fid = {E._lit(hv)}")
        else:
            words = [w for w in re.split(r"[^A-Za-z0-9']+", hv) if len(w) > 1 and w.lower() not in ("the", "of", "and")]
            for w in words[:6]:
                lw = E._lit(f"%{w}%")
                f.append(f"(h.name ILIKE {lw} OR h.cms_name ILIKE {lw} OR array_to_string(h.locations, ' ') ILIKE {lw})")
    return " AND ".join(f), f


def _payer_where(payer: str, program: str) -> str:
    f = []
    p = (payer or "").strip().lower()
    if p and p not in ("all", "any"):
        toks = [t.strip().replace("unitedhealthcare", "uhc").replace("united", "uhc").replace("bluecross", "bcbs")
                for t in p.split(",") if t.strip()]
        known = [t for t in toks if t in CARRIERS]
        free = [t for t in toks if t not in CARRIERS]
        parts = []
        if known:
            parts.append(f"r.carrier IN ({', '.join(E._lit(t) for t in known)})")
        for t in free:
            parts.append(f"(coalesce(r.payer, '') || ' ' || coalesce(r.plan, '')) ILIKE {E._lit('%' + t + '%')}")
        f.append("(" + " OR ".join(parts) + ")")
    g = (program or "").strip().lower()
    if g and g not in ("all", "any"):
        progs = [x.strip() for x in g.split(",") if x.strip()]
        bad = [x for x in progs if x not in PROGRAMS]
        if bad:
            raise ValueError(f"program is one of {', '.join(PROGRAMS)} (or 'all')")
        f.append(f"r.program IN ({', '.join(E._lit(x) for x in progs)})")
    return " AND ".join(f) or "true"


def _setting_where(setting: str) -> str:
    s = (setting or "").strip().lower()
    if s in ("", "any", "all"):
        return "true"
    if s not in ("inpatient", "outpatient", "both"):
        raise ValueError("setting is 'inpatient', 'outpatient' or 'any'")
    return f"r.setting IN ({E._lit(s)}, 'both', '')"


AMOUNT = (f"CASE WHEN r.dmin > 0 AND r.dmin < {PLACEHOLDER} THEN r.dmin "
          f"WHEN r.est > 0 AND r.est < {PLACEHOLDER} THEN r.est "
          f"WHEN r.med > 0 AND r.med < {PLACEHOLDER} THEN r.med END")
BASIS = ("CASE WHEN r.dmin > 0 AND r.dmin < 9999999 THEN 'dollar amount' "
         "WHEN r.est > 0 AND r.est < 9999999 THEN 'percent of charges x gross charge (estimate)' "
         "WHEN r.med > 0 AND r.med < 9999999 THEN 'median allowed amount on claims' "
         "WHEN r.pct > 0 THEN 'percent of charges (no gross charge to convert)' "
         "WHEN r.alg IS NOT NULL THEN 'formula only (see algorithm)' END")


def _rates_sql(cs: list[str], ct: str, hw: str, pw: str, sw: str) -> str | None:
    rf, cf = _files("rates", cs), _files("charges", cs)
    if not rf and not cf:
        return None
    cl = ", ".join(E._lit(c) for c in cs)
    ctw = f" AND ct = {E._lit(ct)}" if ct else ""
    rates = (f"SELECT * FROM read_parquet({rf!r}, union_by_name = true) WHERE code IN ({cl}){ctw}" if rf else
             "SELECT NULL::VARCHAR AS fid, NULL::VARCHAR AS code, NULL::VARCHAR AS ct, NULL::VARCHAR AS setting WHERE false")
    charges = (f"SELECT * FROM read_parquet({cf!r}, union_by_name = true) WHERE code IN ({cl}){ctw}" if cf else
               "SELECT NULL::VARCHAR AS fid, NULL::VARCHAR AS code, NULL::VARCHAR AS ct, NULL::VARCHAR AS setting, "
               "NULL::VARCHAR AS descr, NULL::DOUBLE AS gross, NULL::DOUBLE AS cash WHERE false")
    return f"""WITH h AS (SELECT * FROM hosp h WHERE {hw}),
      ch AS (SELECT c.* FROM ({charges}) c JOIN h USING (fid)),
      chc AS (SELECT fid, code, ct, any_value(descr) AS descr, median(gross) AS gross, min(cash) AS cash FROM ch GROUP BY ALL),
      r AS (SELECT r.* FROM ({rates}) r JOIN h USING (fid) WHERE {pw} AND {sw})"""


def _compact(rows: list[dict]) -> list[dict]:
    """Drop empty fields: rows stay readable and many more fit in an AI assistant's context."""
    return [{k: v for k, v in r.items() if v is not None and v != []} for r in rows]


def _hosp_cols(prefix: str = "h") -> str:
    return (f"{prefix}.name AS hospital, {prefix}.ccns[1] AS ccn, {prefix}.city, {prefix}.state, {prefix}.zip5, "
            f"{prefix}.ein, {prefix}.fid")


# ------------------------------------------------------------------ tools

def search_hospitals(name="", state="", city="", zip_prefix="", ccn="", ein="", npi="", limit=50):
    _need()
    hv = ccn or ein or npi or name
    if not (hv or state or city or zip_prefix):
        raise ValueError("give a hospital name, state, city, ZIP prefix, CCN, EIN or NPI")
    hw, _ = _hosp_where(hv, state, city, zip_prefix)
    return _compact(E._q(f"""SELECT h.name AS hospital, h.cms_name, h.ccns, h.ein, h.npis, h.address, h.city, h.state, h.zip5,
                           h.kind, h.last_updated, h.version AS schema_version, h.rates AS rate_rows, h.attached_by,
                           h.shared_file, h.url AS file_url, h.fid
                    FROM hosp h WHERE {hw} ORDER BY h.state, h.name LIMIT {min(int(limit or 50), 500)}"""))


def hospital_prices(code, state="", hospital="", city="", zip_prefix="", payer="all", program="", setting="",
                    code_type="", group_by="", sort="", limit=200):
    _need()
    cs, ct = _codes(code, code_type)
    if not (hospital or state):
        raise ValueError("give a state (e.g. 'MO', or 'US' for every state) or a hospital")
    hw, _ = _hosp_where(hospital, state, city, zip_prefix)
    pw, sw = _payer_where(payer, program), _setting_where(setting)
    n = min(int(limit or 200), E.MAX_ROWS)
    gb = (group_by or ("row" if hospital else "hospital")).strip().lower()
    notes = []
    if gb == "hospital" and not (program or "").strip():  # Medicare Advantage / Medicaid rates would pull medians down
        program = "commercial"
        notes.append("plan amounts are commercial plans only (program='commercial'); pass program='all' or "
                     "'medicare_advantage' / 'medicaid' for others")
    pw = _payer_where(payer, program)
    head = _rates_sql(cs, ct, hw, pw, sw)
    if not head:
        return {"rows": [], "notes": [f"no hospital file publishes {', '.join(cs)}"]}
    if gb == "row":
        rows = E._q(f"""{head}
            SELECT {_hosp_cols()}, r.code, r.ct AS code_type, coalesce(c1.descr, c2.descr) AS description, r.setting,
                   r.bc AS billing_class, r.mods AS modifiers, r.payer, r.plan, r.carrier, r.program, r.meth AS methodology,
                   round({AMOUNT}, 2) AS amount, {BASIS} AS amount_basis,
                   CASE WHEN r.dmax > r.dmin AND r.dmax < {PLACEHOLDER} THEN r.dmax END AS amount_max_if_several,
                   r.pct AS percent_of_charges, r.alg AS algorithm, r.med AS median_allowed, r.p10 AS p10_allowed,
                   r.p90 AS p90_allowed, r.claims AS claims_count, coalesce(c1.gross, c2.gross) AS gross_charge,
                   coalesce(c1.cash, c2.cash) AS cash_price, r.n_items
            FROM r JOIN h USING (fid)
            LEFT JOIN ch c1 ON c1.fid = r.fid AND c1.code = r.code AND c1.ct = r.ct AND c1.setting = r.setting
            LEFT JOIN chc c2 ON c2.fid = r.fid AND c2.code = r.code AND c2.ct = r.ct
            ORDER BY h.name, r.code, r.program, r.carrier NULLS LAST, r.payer, r.plan, amount
            LIMIT {n}""")
        if not rows:  # a hospital may publish only its gross and cash prices for the code
            rows = E._q(f"""{head}
                SELECT {_hosp_cols()}, c.code, c.ct AS code_type, c.descr AS description, c.setting,
                       c.gross AS gross_charge, c.gross_min, c.gross_max, c.cash AS cash_price, c.cash_max
                FROM ch c JOIN h USING (fid) ORDER BY h.name, c.code LIMIT {n}""")
            if rows:
                notes.append("no payer/plan rate matches these filters; these rows are the hospital's gross charge and "
                             "cash price only")
        return {"rows": _compact(rows), "notes": notes} if notes else _compact(rows)
    if gb != "hospital":
        raise ValueError("group_by is 'hospital' (one row per hospital and code) or 'row' (every payer/plan row)")
    order = {"cash": "cash_price", "gross": "gross_charge", "name": "hospital", "plans": "plans DESC"}.get(
        (sort or "").strip().lower(), "median_amount")
    rows = E._q(f"""{head},
        per AS (SELECT fid, code, ct, count(DISTINCT coalesce(payer, '') || '|' || coalesce(plan, '')) AS plans,
                       min({AMOUNT}) AS min_amount, round(median({AMOUNT}), 2) AS median_amount, max({AMOUNT}) AS max_amount,
                       count(*) FILTER (WHERE r.med > 0) AS rows_with_claims_median,
                       string_agg(DISTINCT r.carrier, ',' ORDER BY r.carrier) AS carriers,
                       string_agg(DISTINCT r.program, ',' ORDER BY r.program) AS programs
                FROM r GROUP BY ALL),
        k AS (SELECT fid, code, ct FROM per UNION SELECT fid, code, ct FROM chc)
        SELECT {_hosp_cols()}, k.code, k.ct AS code_type, c.descr AS description, per.plans, per.min_amount,
               per.median_amount, per.max_amount, per.carriers, per.programs, per.rows_with_claims_median,
               c.gross AS gross_charge, c.cash AS cash_price
        FROM k JOIN h USING (fid) LEFT JOIN per USING (fid, code, ct) LEFT JOIN chc c USING (fid, code, ct)
        ORDER BY k.code, {order} NULLS LAST LIMIT {n}""")
    return {"rows": _compact(rows), "notes": notes} if notes else _compact(rows)


def _quant(vals) -> dict:
    v = [x for x in vals if x is not None]
    return {"hospitals": len(v), **E._quantiles(v)}


def hospital_market(code, state, payer="all", program="commercial", setting="", code_type="", city="", zip_prefix=""):
    _need()
    cs, ct = _codes(code, code_type)
    hw, _ = _hosp_where("", state, city, zip_prefix)
    head = _rates_sql(cs, ct, hw, _payer_where(payer, program), _setting_where(setting))
    if not head:
        return {"codes": [], "notes": [f"no hospital file publishes {', '.join(cs)}"]}
    per = E._q(f"""{head},
        per AS (SELECT fid, code, ct, coalesce(carrier, 'other') AS carrier, median({AMOUNT}) AS amt FROM r GROUP BY ALL)
        SELECT p.code, p.ct, p.carrier, p.fid, p.amt, c.gross, c.cash FROM per p LEFT JOIN chc c USING (fid, code, ct)
        UNION ALL SELECT c.code, c.ct, NULL, c.fid, NULL, c.gross, c.cash FROM chc c""")
    out = []
    for c in cs:
        rows = [r for r in per if r["code"] == c]
        if not rows:
            out.append({"code": c, "hospitals": 0})
            continue
        neg = {}
        for r in rows:
            if r["carrier"] and r["amt"]:
                neg.setdefault(r["fid"], []).append(r["amt"])
        per_h = [sorted(v)[len(v) // 2] for v in neg.values()]
        gross = {r["fid"]: r["gross"] for r in rows if r["gross"]}
        cash = {r["fid"]: r["cash"] for r in rows if r["cash"]}
        by_carrier = {}
        for r in rows:
            if r["carrier"] and r["amt"]:
                by_carrier.setdefault(r["carrier"], {})[r["fid"]] = r["amt"]
        out.append({"code": c, "code_types": sorted({r["ct"] for r in rows}),
                    "hospitals_publishing": len({r["fid"] for r in rows}),
                    "negotiated_per_hospital_median": _quant(per_h),
                    "cash_price": _quant(cash.values()), "gross_charge": _quant(gross.values()),
                    "by_carrier": {k: _quant(v.values()) for k, v in sorted(by_carrier.items(), key=lambda kv: -len(kv[1]))[:12]}})
    return {"state": (state or "US").upper(), "program": program or "all", "codes": out,
            "notes": ["Per-hospital amount = median over the hospital's matching payer/plan rows (dollar amounts; "
                      "percent-of-charges rows converted with the item's gross charge; else the median allowed amount)."]}


def hospital_vs_insurer(hospital, codes, payer="all", state=""):
    """Hospital file vs insurer (TiC) file for the same hospital and codes."""
    _need()
    cs, _ = _codes(codes)
    hw, _ = _hosp_where(hospital, state)
    hs = E._q(f"SELECT * FROM hosp h WHERE {hw} ORDER BY rates DESC NULLS LAST LIMIT 3")
    hs = [x for i, x in enumerate(hs) if x["hid"] not in {y["hid"] for y in hs[:i]}]
    if not hs:
        raise ValueError(f"no hospital file matches {hospital!r}; try search_hospitals")
    h = hs[0]
    st = h["state"]
    ids = ([h["ein"]] if h.get("ein") else []) + list(h.get("npis") or [])[:3]
    if not ids:
        raise ValueError("this hospital's file names no EIN or type-2 NPI, so its insurer rates cannot be matched")
    pw = _payer_where(payer, "commercial")
    head = _rates_sql(cs, "", f"h.fid = {E._lit(h['fid'])}", pw, "true")
    hrows = E._q(f"""{head} SELECT r.code, r.carrier, r.payer, r.plan, r.setting, r.bc, round({AMOUNT}, 2) AS amount,
                               {BASIS} AS basis, r.med, r.claims FROM r""") if head else []
    tic_payers = [p for p in E.payers_loaded() if payer in ("", "all") or p in payer.lower()]
    trows = []
    for pid in ids:
        if not tic_payers:
            break
        try:
            got = E.lookup_rates(",".join(cs), st, ",".join(tic_payers), provider=pid, billing_class="institutional",
                                 limit=2000)
        except Exception:
            got = []
        if got:
            trows = got
            break
    out = []
    for c in cs:
        for carrier in sorted({r["carrier"] for r in hrows if r["code"] == c and r["carrier"]} |
                              {r["payer"] for r in trows if r["code"] == c}):
            hv = sorted(r["amount"] for r in hrows if r["code"] == c and r["carrier"] == carrier and r["amount"])
            tv = sorted(r["rate"] for r in trows if r["code"] == c and r["payer"] == carrier and r.get("rate")
                        and r.get("negotiated_type") in E.DOLLAR_TYPES and 0.01 < r["rate"] < 99999)
            hm = hv[len(hv) // 2] if hv else None
            tm = tv[len(tv) // 2] if tv else None
            out.append({"code": c, "payer": carrier,
                        "hospital_file": {"rows": len(hv), "min": hv[0] if hv else None, "median": hm,
                                          "max": hv[-1] if hv else None,
                                          "plans": sorted({f"{r['payer']} / {r['plan']}" for r in hrows
                                                           if r["code"] == c and r["carrier"] == carrier})[:8]},
                        "insurer_file": {"rows": len(tv), "min": tv[0] if tv else None, "median": tm,
                                         "max": tv[-1] if tv else None,
                                         "products": sorted({r.get("product") or "" for r in trows
                                                             if r["code"] == c and r["payer"] == carrier})[:8]},
                        "hospital_over_insurer": round(hm / tm, 2) if hm and tm else None})
    return {"hospital": h["name"], "ccn": (h.get("ccns") or [None])[0], "state": st, "matched_by": ids[0],
            "other_matches": [x["name"] for x in hs[1:]], "rows": out,
            "notes": ["hospital_file: the hospital's commercial payer/plan rows (dollar, or percent of charges x gross "
                      "charge, or median allowed); insurer_file: institutional dollar rates the insurer publishes for "
                      "the hospital's EIN/NPI in its Transparency in Coverage files. They often differ: different "
                      "contract terms (case rates vs fee schedules), plan coverage and file dates; a ratio near 1.0 "
                      "means the two sides agree."]}


def code_rows(code: str) -> list[dict]:
    """For code_info: how many hospitals publish a code."""
    if not meta():
        return []
    c = _norm_code(code)
    return E._q(f"SELECT 'hospital files' AS payer, code_type AS billing_code_type, code AS billing_code, "
                f"example_description AS name, hospitals, states, rows AS published_rows, hospitals_with_charges "
                f"FROM hcodes WHERE code = {E._lit(c)}")


def status() -> dict | None:
    m = meta()
    if not m:
        return None
    return {k: m.get(k) for k in ("release", "hospitals", "with_ccn", "states", "rate_rows", "codes", "last_updated_range")}


def sql_views(fn: str, a: list[str], work: str, name: str, sb) -> bool:
    """run_sql table functions: rc_hospitals('<states>'), rc_hospital_rates('<states>', '<codes>'),
    rc_hospital_charges('<states>', '<codes>'). Returns False when fn is not a hospital function."""
    if fn not in ("hospitals", "hospital_rates", "hospital_charges"):
        return False
    _need()
    sts = E._states_arg(a[0])
    stl = ", ".join(E._lit(s) for s in sts)
    hf = f"{work}/{name}-h.parquet"
    stw = "true" if len(sts) == len(E.STATES) else f"state IN ({stl})"
    E.con().execute(f"COPY (SELECT fid, name, cms_name, ccns, ein, npis, address, city, state, zip5, kind, last_updated, "
                    f"url, rates FROM hosp WHERE NOT dup AND {stw}) TO '{hf}' (FORMAT parquet)")
    if fn == "hospitals":
        sb.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{hf}')")
        return True
    cs, _ = _codes(a[1])
    kind = "rates" if fn == "hospital_rates" else "charges"
    fs = _files(kind, cs)
    out = f"{work}/{name}.parquet"
    cl = ", ".join(E._lit(c) for c in cs)
    if fs:
        E.con().execute(f"COPY (SELECT r.* EXCLUDE (state), h.state FROM read_parquet({fs!r}, union_by_name = true) r "
                        f"JOIN read_parquet('{hf}') h USING (fid) WHERE r.code IN ({cl})) TO '{out}' (FORMAT parquet)")
        sb.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{out}')")
    else:
        sb.execute(f"CREATE VIEW {name} AS SELECT NULL::VARCHAR AS fid, NULL::VARCHAR AS code WHERE false")
    return True


DOCS = {
    "hospital_prices": """Hospital prices from the HOSPITALS' OWN price files (federal hospital price transparency rule,
45 CFR 180): every hospital must publish, for every item and service, its gross (chargemaster) charge, its
discounted cash price, and the amount each insurance plan pays, by payer and plan, with (since 2026) the median and
10th/90th percentile allowed amounts from claims. ~3,200 hospital files, every code. Use this for facility /
hospital prices: what a hospital charges or is paid for an MRI, CT, surgery, ER visit, lab test, inpatient stay
(MS-DRG), a hospital's cash price, chargemaster, Medicare Advantage or Medicaid plan rates at a hospital, or
"cheapest hospital for X". For clinicians' and groups' negotiated rates use lookup_rates (insurer files).

Args:
    code: billing code(s), comma list up to 10: CPT/HCPCS "70553", MS-DRG "470" (3 digits), APR-DRG, APC
    state: two-letter state, or "US" for every state; required unless hospital is given
    hospital: optional hospital name (words, e.g. "Barnes Jewish"), CMS Certification Number (6 chars), EIN or
      type-2 NPI. Find exact matches with search_hospitals
    city: optional hospital city, e.g. "St. Louis"
    zip_prefix: optional ZIP prefix, e.g. "631"
    payer: "all" (default), a carrier ("aetna", "cigna", "uhc", "anthem", "bcbs", "humana", "kaiser", "centene",
      "molina", ...), a comma list, or any text matched against the payer/plan names the hospital published
    program: "commercial", "medicare_advantage", "medicaid", "medicare", "tricare", "va", "workers_comp", a comma
      list, or "all" (default)
    setting: "outpatient", "inpatient" or "any" (default)
    code_type: optional CPT, HCPCS, MS-DRG, APR-DRG or APC (3-digit codes match both DRG types otherwise)
    group_by: "hospital" (default without a hospital: one row per hospital and code with the cash price, gross
      charge and min/median/max plan amount) or "row" (default with a hospital: every payer/plan row)
    sort: for group_by "hospital": "median" (default, cheapest first), "cash", "gross", "plans", "name"
    limit: max rows (default 200)
Returns rows with hospital, ccn, city, state, code, description (the hospital's wording), payer, plan, carrier,
program, amount, amount_basis, percent_of_charges, algorithm, median_allowed, p10_allowed, p90_allowed,
claims_count, gross_charge, cash_price. amount_basis says where amount comes from: a dollar amount, a percent of
charges converted with the item's gross charge (estimate), or the median allowed amount on claims.""",
    "hospital_market": """Distribution of hospital prices for a code across the hospitals of a state (or the US), from
the hospitals' own price files: how many hospitals publish it, quantiles of the per-hospital plan amount, of cash
prices and of gross charges, and per insurance carrier. Use it for "what do hospitals in X charge / get paid for Y",
"is this hospital price high", or market comparisons of facility prices.

Args:
    code: billing code(s), comma list up to 10 (CPT/HCPCS, MS-DRG, APR-DRG, APC)
    state: two-letter state or "US"
    payer: "all" (default), a carrier (aetna, cigna, uhc, anthem, bcbs, humana, ...) or a comma list
    program: "commercial" (default), "medicare_advantage", "medicaid", ... or "all"
    setting: "outpatient", "inpatient" or "any" (default)
    code_type: optional CPT, HCPCS, MS-DRG, APR-DRG or APC
    city: optional hospital city
    zip_prefix: optional ZIP prefix
Returns per code: hospitals_publishing, negotiated_per_hospital_median (hospitals, min, p10, p25, median, p75, p90,
max, mean), cash_price, gross_charge and by_carrier.""",
    "search_hospitals": """Find hospitals that publish a price file, with their identifiers: name, CMS Certification
Number (CCN), EIN (tax ID, the TIN insurers use), type-2 NPIs, address, the file's date and URL. Use it to resolve a
hospital before hospital_prices or hospital_vs_insurer, or to list a city's hospitals with price files.

Args:
    name: optional hospital name words, e.g. "Mercy South"
    state: optional two-letter state
    city: optional city
    zip_prefix: optional ZIP prefix
    ccn: optional CMS Certification Number
    ein: optional EIN (9 digits)
    npi: optional type-2 NPI
    limit: max rows (default 50)
Returns hospital, cms_name, ccns, ein, npis, address, city, state, zip5, last_updated, rate_rows, attached_by,
file_url, fid.""",
    "hospital_vs_insurer": """Triangulate one hospital's prices from both sides: the hospital's own price file vs the
insurers' Transparency in Coverage files (institutional rates published for the hospital's EIN/NPI), per code and
insurer. Use it to check a hospital price, to see whether the two disclosures agree, or when a user asks which
number is right. Commercial plans only (the insurer files cover commercial plans).

Args:
    hospital: hospital name words, CCN, EIN or type-2 NPI (the best match is used; see search_hospitals)
    codes: billing code(s), comma list up to 10
    payer: "all" (default) or a comma list of cigna, aetna, uhc, bcbs, anthem
    state: optional two-letter state to disambiguate the hospital name
Returns per code x insurer: hospital_file (rows, min, median, max, plans), insurer_file (rows, min, median, max,
products) and hospital_over_insurer (ratio of medians).""",
}

SQL_DOC = """
  rc_hospitals('<states>')   hospitals with price files: fid, name, cms_name, ccns, ein, npis, address, city,
                             state, zip5, kind, last_updated, url, rates.
  rc_hospital_rates('<states>', '<codes>')   the hospitals' own payer/plan rates (up to 10 codes): fid, state, code,
                             ct (code type), setting, bc (billing class), mods, payer, plan, carrier, program, meth,
                             dmin/dmax (dollars), pct (% of charges), est (pct x gross charge), alg, med/p10/p90
                             (allowed amounts on claims), claims, n_items. Join rc_hospitals on fid. Exclude
                             placeholders with dmin < 9999999.
  rc_hospital_charges('<states>', '<codes>') per hospital x code x setting: descr, gross, gross_min, gross_max,
                             cash, cash_max."""

INSTRUCTIONS = """RateCommons: US healthcare prices from public price transparency files.
Two kinds of data, pick by the question:
- Insurer files (Transparency in Coverage; Cigna, Aetna, UnitedHealthcare, BCBS, Anthem): negotiated rates by
  provider group (TIN), clinician (NPI), network and code. Tools: lookup_rates, market_distribution,
  provider_rates, rank_providers, compare_providers, benchmark_provider, network_breadth, provider_networks.
  Best for physician/professional fees and groups, networks and plans.
- Hospital files (hospital price transparency, ~3,200 hospitals, every code): each hospital's gross charge, cash
  price and payer/plan rates incl. Medicare Advantage and Medicaid plans and claims-based median allowed amounts.
  Tools: hospital_prices, hospital_market, search_hospitals. Best for facility fees, hospital and ER prices, DRGs,
  cash prices, "cheapest hospital".
- Both sides for one hospital: hospital_vs_insurer. A patient's total for a procedure at a hospital is usually the
  facility fee (hospital files) plus the professional fee (insurer files, e.g. the radiologist).
- medicare_rate: Medicare physician fee schedule benchmark. run_sql: custom SQL over all of it (rc_* functions).
Prices are as published; say which file a number comes from and that a patient's cost depends on their plan."""
