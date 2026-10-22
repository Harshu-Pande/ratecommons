"""RateCommons query engine: DuckDB over the serving packs (ratecommons/<payer>/serving, identity/serving).

Every function returns a pandas DataFrame and is safe to expose: read-only, parameterized, row-capped.
Reading rules the answers follow: a missing rate means "no published rate", never "out of network";
percentages are not dollars; provider identity is TIN + NPI, names come from NPPES by NPI.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import Counter

import shutil

import duckdb
import pandas as pd

ORG = "ratecommons"
PAYERS = ["cigna", "aetna", "uhc"]
DATA = os.environ.get("RC_DATA", "/data" if os.path.isdir("/data") and os.access("/data", os.W_OK) else "/tmp/rc")
MAX_ROWS = 2000
DOLLAR_TYPES = ("negotiated", "fee schedule", "derived")

STATUS: dict = {"state": "starting", "payers": {}, "started": time.time(), "log": []}
_con: duckdb.DuckDBPyConnection | None = None
_lock = threading.Lock()


def _log(msg: str):
    STATUS["log"].append(f"{time.strftime('%H:%M:%S')} {msg}")
    print(msg, flush=True)


# ------------------------------------------------------------------ loading

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
    """(product, label) for a derived network (a distinct file)."""
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
                     ("Gppo", "GPPO"), ("Sar Ii", "SAR II"), (" Nj ", " NJ "), (" Fl ", " FL "), (" Az ", " AZ ")):
            t = re.sub(rf"\b{a.strip()}\b", b.strip(), t)
        return f"Cigna {t}", f"Cigna {t}"
    parts = stem.split("_")
    if payer == "uhc":
        prod = parts[2] if len(parts) > 2 else stem
        prod = prod.replace("-", " ").replace("Ppo", "PPO")
        return f"UHC {prod}", f"UHC {prod} ({' '.join(parts[0:2])} {parts[3] if len(parts) > 3 else ''})".strip()
    return payer, stem


def _pack_bytes(p: str) -> int:
    from huggingface_hub import HfApi

    try:
        return sum(getattr(f, "size", 0) or 0 for f in HfApi().list_repo_tree(
            f"{ORG}/{p}", repo_type="dataset", recursive=True, path_in_repo="serving"))
    except Exception:
        return 0


def _on_disk(d: str) -> int:
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs) if os.path.isdir(d) else 0


def load(download: bool = True):
    """Download the packs (if needed) and register views. Runs in a background thread at startup."""
    global _con
    from huggingface_hub import snapshot_download

    try:
        STATUS["state"] = "downloading"
        os.makedirs(DATA, exist_ok=True)
        if download:
            snapshot_download(f"{ORG}/identity", repo_type="dataset", local_dir=f"{DATA}/identity",
                              allow_patterns=["serving/*"])
        con = duckdb.connect(f"{DATA}/rc.duckdb")
        con.execute("SET enable_progress_bar = false")
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET temp_directory = '{DATA}/tmp'")
        con.execute(f"SET memory_limit = '{os.environ.get('RC_MEMORY', '10GB')}'")
        con.execute(f"SET max_temp_directory_size = '{os.environ.get('RC_TEMP_MAX', '3GB')}'")
        idir = f"{DATA}/identity/serving"
        con.execute(f"CREATE OR REPLACE VIEW nppes AS SELECT * FROM read_parquet('{idir}/nppes.parquet')")
        if os.path.exists(f"{idir}/medicare_pfs.parquet"):
            con.execute(f"CREATE OR REPLACE TABLE mcr AS SELECT * FROM read_parquet('{idir}/medicare_pfs.parquet')")
        else:
            con.execute("CREATE OR REPLACE TABLE mcr (hcpcs VARCHAR, modifier VARCHAR, status VARCHAR, state VARCHAR, "
                        "nonfacility_amount DOUBLE, facility_amount DOUBLE, conversion_factor DOUBLE, year VARCHAR)")
        labels = []
        for p in PAYERS:
            try:
                if download:
                    need = _pack_bytes(p)
                    have = _on_disk(f"{DATA}/{p}/serving")
                    free = shutil.disk_usage(DATA).free
                    floor = float(os.environ.get("RC_MIN_FREE_GB", "10")) * 1e9 + 3e9  # + DuckDB temp headroom
                    if need - have > free - floor:
                        _log(f"{p}: skipped, needs {(need - have) / 1e9:.1f} GB more but only "
                             f"{(free - floor) / 1e9:.1f} GB may be used (keeping {floor / 1e9:.0f} GB free)")
                        if not os.path.exists(f"{DATA}/{p}/serving/network.parquet"):
                            continue
                    else:
                        _log(f"downloading {p} ({need / 1e9:.1f} GB)")
                        snapshot_download(f"{ORG}/{p}", repo_type="dataset", local_dir=f"{DATA}/{p}",
                                      allow_patterns=["serving/*"])
                d = f"{DATA}/{p}/serving"
                if not os.path.exists(f"{d}/network.parquet"):
                    _log(f"{p}: no serving pack yet")
                    continue
                V = {"rate": f"read_parquet('{d}/rate/*.parquet')",
                     "pt": f"read_parquet('{d}/price_term.parquet')",
                     "ps_pli": f"read_parquet('{d}/ps_pli/*/*.parquet', hive_partitioning = true)",
                     "pli_pg": f"read_parquet('{d}/pli_pg.parquet')",
                     "pg": f"read_parquet('{d}/provider_group.parquet')",
                     "pg_npi": f"read_parquet('{d}/pg_npi/*/*.parquet', hive_partitioning = true)",
                     "ns": f"read_parquet('{d}/ns.parquet')",
                     "pgnet": f"read_parquet('{d}/pg_network.parquet')",
                     "code": f"read_parquet('{d}/code.parquet')"}
                for k, v in V.items():
                    con.execute(f"CREATE OR REPLACE VIEW {k}_{p} AS SELECT * FROM {v}")
                net = con.execute(f"SELECT network_id, file_names, plan_names FROM read_parquet('{d}/network.parquet')").fetchall()
                for nid, files, plans in net:
                    prod, lab = _label(p, files, plans)
                    labels.append((p, nid, prod, lab, len(plans or []), files, plans or []))
                STATUS["payers"][p] = {"networks": len(net)}
                _log(f"{p}: {len(net)} networks")
            except Exception as e:  # one payer failing must not take the app down
                _log(f"{p}: failed {e!r}")
        con.execute("CREATE OR REPLACE TABLE netlabel (payer VARCHAR, network_id BLOB, product VARCHAR, label VARCHAR, "
                    "n_plans INTEGER, file_names VARCHAR[], plan_names VARCHAR[])")
        if labels:
            con.executemany("INSERT INTO netlabel VALUES (?, ?, ?, ?, ?, ?, ?)", labels)
        _con = con
        STATUS["state"] = "ready"
        _log("ready")
    except Exception as e:
        STATUS["state"] = f"failed: {e!r}"
        _log(STATUS["state"])


def _shas() -> dict:
    from huggingface_hub import HfApi

    out = {}
    for p in PAYERS + ["identity"]:
        try:
            out[p] = HfApi().dataset_info(f"{ORG}/{p}").sha
        except Exception:
            out[p] = None
    return out


def start_background():
    """Load now; then every 15 minutes reload if a payer pack was published or updated."""
    def run():
        seen = _shas()
        load()
        while True:
            time.sleep(900)
            try:
                now = _shas()
                if now != seen:
                    _log("datasets changed; reloading")
                    seen = now
                    load()
            except Exception as e:
                _log(f"refresh check failed: {e!r}")
    threading.Thread(target=run, daemon=True).start()


def _q(sql: str, params: list | None = None) -> pd.DataFrame:
    if _con is None:
        raise RuntimeError(f"Data is still loading ({STATUS['state']}). Try again in a minute.")
    with _lock:
        cur = _con.cursor()
    return cur.execute(sql, params or []).df()


def payers_loaded() -> list[str]:
    return [p for p in PAYERS if p in STATUS["payers"]]


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


# ------------------------------------------------------------------ core

def _core_sql(p: str, code_types: str | None, network: str | None, city: str | None, zip_prefix: str | None,
              specialty: str | None, provider: str | None, billing_class: str | None) -> tuple[str, list]:
    """Rows: one per (product, provider group, price term) for one code in one state."""
    params: list = []
    ct = ""
    if code_types:
        ct = "AND r.billing_code_type = ?"
        params.append(code_types.upper())
    nf = ""
    if network:
        nf = ("AND (l.product ILIKE ? OR l.label ILIKE ? OR list_contains(list_transform(l.plan_names, x -> x ILIKE ?), true)"
              " OR list_contains(list_transform(l.file_names, x -> x ILIKE ?), true))")
    loc_f, loc_p = [], []
    if city:
        loc_f.append("x.city ILIKE ?"); loc_p.append(city.strip())
    if zip_prefix:
        loc_f.append("x.zip5 LIKE ?"); loc_p.append(zip_prefix.strip() + "%")
    if specialty:
        loc_f.append("(x.taxonomy ILIKE ? OR x.classification ILIKE ? OR x.specialization ILIKE ? OR x.taxonomy_code = ?)")
        loc_p += [f"%{specialty}%"] * 3 + [specialty.strip()]
    prov_f, prov_p = "", []
    if provider:
        pv = provider.strip()
        if re.fullmatch(r"\d{10}", pv):
            prov_f = "AND pg_id IN (SELECT pg_id FROM pg_npi_{p} WHERE npi = ?)"; prov_p = [int(pv)]
        elif re.fullmatch(r"\d{2}-?\d{7}", pv):
            prov_f = "AND tin_value = ?"; prov_p = [pv.replace("-", "")]
        else:
            prov_f = ("AND pg_id IN (SELECT n.pg_id FROM pg_npi_{p} n JOIN nppes x USING (npi) "
                      "WHERE n.state = $state AND x.state = $state AND x.name ILIKE ?)"); prov_p = [f"%{pv}%"]
    bc = ""
    if billing_class:
        bc = "AND pt.billing_class = ?"
    loc_where = (" AND " + " AND ".join(loc_f)) if loc_f else ""
    tin_wide_ok = "" if loc_f else " OR n.npi IS NULL"
    sql = f"""
    WITH f AS (SELECT r.billing_code_type, r.billing_code, r.ps_id, r.pt_id, r.ns_id FROM rate_{p} r
               WHERE r.billing_code = $code {ct}),
    nets AS (SELECT DISTINCT n.ns_id, l.product FROM ns_{p} n JOIN netlabel l
             ON l.payer = '{p}' AND l.network_id = n.network_id {nf}),
    f2 AS (SELECT f.*, nets.product FROM f JOIN nets USING (ns_id)),
    psx AS (SELECT DISTINCT ps_id, pli_id FROM ps_pli_{p} WHERE state = $state AND ps_id IN (SELECT ps_id FROM f2)),
    g AS (SELECT DISTINCT psx.ps_id, l.pg_id FROM psx JOIN pli_pg_{p} l USING (pli_id)),
    loc AS (SELECT n.pg_id, count(DISTINCT n.npi) n_npi,
                   CASE WHEN bool_or(x.entity_type = '2') THEN arg_max(x.name, CASE WHEN x.entity_type = '2' THEN 1 ELSE 0 END)
                        WHEN count(DISTINCT n.npi) > 1 THEN min(x.name) || ' +' || (count(DISTINCT n.npi) - 1) || ' clinicians'
                        ELSE min(x.name) END AS top_name,
                   list(DISTINCT x.city)[1:3] cities, mode(x.classification) specialty
            FROM pg_npi_{p} n LEFT JOIN (SELECT * FROM nppes WHERE state = $state) x USING (npi)
            WHERE n.state = $state AND (n.npi IS NULL OR x.npi IS NOT NULL) AND (true {loc_where}{tin_wide_ok})
              AND n.pg_id IN (SELECT pg_id FROM g)
            GROUP BY n.pg_id),
    rows AS (SELECT DISTINCT f2.product, g.pg_id, f2.pt_id, f2.billing_code_type, f2.billing_code
             FROM f2 JOIN g USING (ps_id))
    SELECT '{p}' AS payer, rows.product, pg.tin_value AS tin, coalesce(loc.top_name, pg.business_names[1]) AS provider,
           loc.n_npi AS npis_in_area, loc.cities, loc.specialty, pg.tin_wide,
           rows.billing_code_type AS code_type, rows.billing_code AS code,
           pt.negotiated_type, round(pt.rate_e4 / 1e4, 2) AS rate, pt.rate_raw, pt.billing_class, pt.setting,
           array_to_string(pt.billing_code_modifier, ',') AS modifiers, array_to_string(pt.service_code, ',') AS place_of_service,
           pt.expiration_date, hex(rows.pg_id) AS pg_id
    FROM rows JOIN loc USING (pg_id) JOIN pg_{p} pg USING (pg_id) JOIN pt_{p} pt USING (pt_id)
    WHERE true {bc} {prov_f.replace('{p}', p)}
    """
    # DuckDB positional parameters in order of appearance; $code/$state are named, so use named for all
    return sql, params, loc_p, prov_p, nf, bc


def _run_core(code: str, state: str, payer: str | None = None, code_type: str | None = None, network: str | None = None,
              city: str | None = None, zip_prefix: str | None = None, specialty: str | None = None,
              provider: str | None = None, billing_class: str | None = None, wrap: str | None = None,
              medicare: bool = True) -> pd.DataFrame:
    """`wrap` is a SQL template over the base rows ({base}); it runs inside DuckDB (aggregates, limits)."""
    code, state = _code(code), _st(state)
    frames = []
    for p in _payers(payer):
        sql, ct_p, loc_p, prov_p, nf, bc = _core_sql(p, code_type, network, city, zip_prefix, specialty, provider,
                                                      billing_class)
        # turn every ? into a named parameter in order of appearance
        # code and state are validated above; inlined so DuckDB prunes partitions and row groups
        sql = sql.replace("$code", f"'{code}'").replace("$state", f"'{state}'")
        named: dict = {}
        order = list(ct_p) + ([f"%{network}%"] * 4 if nf else []) + loc_p + ([billing_class.lower()] if bc else []) + prov_p
        i = 0

        def repl(_m):
            nonlocal i
            i += 1
            return f"$p{i}"
        sql2 = re.sub(r"\?", repl, sql)
        for k, v in enumerate(order, 1):
            named[f"p{k}"] = v
        if wrap:
            sql2 = wrap.replace("{base}", f"({sql2})")
        frames.append(_q(sql2, named or None))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return _with_medicare(df, state) if medicare and "code" in df.columns else df


def _mcr(codes: list[str], state: str) -> pd.DataFrame:
    """PFS amounts for the state (mean locality GPCI) or national ("US"), one row per code and modifier."""
    m = _q("""SELECT hcpcs AS code, coalesce(modifier, '') AS mod, state, nonfacility_amount, facility_amount FROM mcr
              WHERE hcpcs IN (SELECT unnest(?::VARCHAR[])) AND state IN (?, 'US')""", [codes, state])
    if m.empty:
        return m
    for c in ("nonfacility_amount", "facility_amount"):
        m[c] = m[c].where(m[c] > 0)
    m["pref"] = (m["state"] != "US").astype(int)
    return m.sort_values("pref").groupby(["code", "mod"]).tail(1).drop(columns=["pref", "state"])


def _with_medicare(df: pd.DataFrame, state: str = "US") -> pd.DataFrame:
    if df.empty:
        return df
    m = _mcr(sorted(df["code"].astype(str).unique().tolist()), state)
    if m.empty:
        df["medicare"] = None
        if "rate" in df.columns and "negotiated_type" in df.columns:
            df["pct_of_medicare"] = None
        return df
    if "negotiated_type" not in df.columns:  # aggregated rows: unmodified code, non-facility
        mm = m[m["mod"] == ""][["code", "nonfacility_amount"]].rename(columns={"nonfacility_amount": "medicare"})
        return df.merge(mm, on="code", how="left")
    mods = df["modifiers"].fillna("")
    df["mod"] = mods.map(lambda x: "26" if "26" in x.split(",") else ("TC" if "TC" in x.split(",") else ""))
    df = df.merge(m, on=["code", "mod"], how="left")
    prof = (df["billing_class"] == "professional") & df["negotiated_type"].isin(DOLLAR_TYPES)
    fac = df["setting"].eq("inpatient") | df["place_of_service"].fillna("").str.contains(r"\b(?:19|21|22|23|24)\b")
    med = pd.to_numeric(df["nonfacility_amount"], errors="coerce").where(~fac, pd.to_numeric(df["facility_amount"], errors="coerce"))
    df["medicare"] = med.where(prof)
    df["pct_of_medicare"] = (100 * df["rate"] / df["medicare"]).round(0).where(prof & (df["medicare"] > 0))
    return df.drop(columns=["nonfacility_amount", "facility_amount", "mod"])


# ------------------------------------------------------------------ tools

def lookup_rates(code: str, state: str, payer: str = "all", network: str = "", city: str = "", zip_prefix: str = "",
                 specialty: str = "", provider: str = "", billing_class: str = "", limit: int = 200) -> pd.DataFrame:
    n = min(int(limit or 200), MAX_ROWS)
    df = _run_core(code, state, payer, None, network or None, city or None, zip_prefix or None, specialty or None,
                   provider or None, billing_class or None,
                   wrap="SELECT * FROM {base} ORDER BY product, negotiated_type, rate LIMIT " + str(n))
    if df.empty:
        return df
    return df.sort_values(["payer", "product", "rate"]).drop(columns=["pg_id"]).head(n)


FACILITY_POS = ("19", "21", "22", "23", "24", "26", "31", "34", "41", "42", "51", "52", "53", "56", "61")


def _place_sql(place: str) -> str:
    """Comparable "base" rates: no modifiers (52/55/56/26/TC... change the amount) and the place of service asked for.
    office: rates that apply in an office (POS 11) or to any place (CSTM-00 / none listed); facility: facility POS."""
    pos = "string_split(coalesce(place_of_service, ''), ',')"
    anyplace = "(coalesce(place_of_service, '') = '' OR place_of_service LIKE 'CSTM%')"
    if place == "any":
        return "true"
    if place == "facility":
        return f"coalesce(modifiers, '') = '' AND (list_has_any({pos}, {list(FACILITY_POS)}) OR {anyplace})"
    return f"coalesce(modifiers, '') = '' AND (list_contains({pos}, '11') OR {anyplace})"


def _place_mask(df: pd.DataFrame, place: str) -> pd.Series:
    if place == "any" or df.empty:
        return pd.Series(True, index=df.index)
    mods = df["modifiers"].fillna("") == ""
    pos = df["place_of_service"].fillna("")
    anyplace = (pos == "") | pos.str.startswith("CSTM")
    sets = pos.str.split(",")
    if place == "facility":
        return mods & (sets.map(lambda xs: any(x in FACILITY_POS for x in xs)) | anyplace)
    return mods & (sets.map(lambda xs: "11" in xs) | anyplace)


def per_pg(place: str = "office") -> str:
    return ("SELECT payer, product, billing_class, setting, pg_id, code, median(rate) AS rate FROM {base} "
            "WHERE negotiated_type IN ('negotiated', 'fee schedule', 'derived') AND rate IS NOT NULL AND "
            + _place_sql(place) + " GROUP BY ALL")


PER_PG = per_pg("office")


def market_distribution(code: str, state: str, payer: str = "all", network: str = "", city: str = "",
                        zip_prefix: str = "", specialty: str = "", billing_class: str = "professional",
                        group_by: str = "payer", place: str = "office") -> pd.DataFrame:
    keys = {"payer": ["payer"], "product": ["payer", "product"], "network": ["payer", "product"],
            "setting": ["payer", "billing_class", "setting"], "none": []}.get(group_by or "payer", ["payer"])
    k = ", ".join(keys)
    wrap = (f"SELECT {k + ', ' if k else ''}code, count(DISTINCT pg_id) AS provider_groups, min(rate) AS min, "
            "quantile_cont(rate, 0.1) AS p10, quantile_cont(rate, 0.25) AS p25, median(rate) AS median, "
            "quantile_cont(rate, 0.75) AS p75, quantile_cont(rate, 0.9) AS p90, max(rate) AS max, avg(rate) AS mean "
            f"FROM ({per_pg(place)}) GROUP BY ALL")
    df = _run_core(code, state, payer, None, network or None, city or None, zip_prefix or None, specialty or None,
                   None, billing_class or None, wrap=wrap)
    if df.empty:
        return df
    if group_by == "none" and len(df) > 1:  # several payers: recompute over the union
        per = _run_core(code, state, payer, None, network or None, city or None, zip_prefix or None,
                        specialty or None, None, billing_class or None, wrap=per_pg(place), medicare=False)
        r = per["rate"]
        df = pd.DataFrame([{"code": code.upper(), "provider_groups": per["pg_id"].nunique(), "min": r.min(),
                            "p10": r.quantile(.1), "p25": r.quantile(.25), "median": r.median(), "p75": r.quantile(.75),
                            "p90": r.quantile(.9), "max": r.max(), "mean": r.mean()}])
        df = _with_medicare(df, state.upper())
    if place == "facility":
        m = _mcr([code.upper()], state.upper())
        f = m[m["mod"] == ""]["facility_amount"]
        df["medicare"] = f.iloc[0] if len(f) else None
    df.insert(0, "state", state.upper())
    df["place"] = place
    for c in ("min", "p10", "p25", "median", "p75", "p90", "max", "mean"):
        df[c] = df[c].astype(float).round(2)
    df["medicare"] = pd.to_numeric(df.get("medicare"), errors="coerce")
    df["median_pct_of_medicare"] = (100 * df["median"] / df["medicare"]).round(0)
    return df


def compare_providers(codes: str, state: str, providers: str, payer: str = "all", network: str = "",
                      place: str = "office") -> pd.DataFrame:
    """codes: comma-separated; providers: comma-separated TINs, NPIs or names."""
    rows = []
    for c in [x.strip() for x in codes.split(",") if x.strip()][:20]:
        for pv in [x.strip() for x in providers.split(",") if x.strip()][:10]:
            df = _run_core(c, state, payer, None, network or None, None, None, None, pv, None)
            df = df[df["negotiated_type"].isin(DOLLAR_TYPES) & _place_mask(df, place)] if not df.empty else df
            if df.empty:
                rows.append({"provider_query": pv, "code": c.upper(), "result": "no published rate found"})
                continue
            for (py, prod, tin, bc), g in df.groupby(["payer", "product", "tin", "billing_class"], dropna=False):
                rows.append({"provider_query": pv, "code": c.upper(), "payer": py, "product": prod, "tin": tin,
                             "provider": g["provider"].iloc[0], "billing_class": bc,
                             "median_rate": round(g["rate"].median(), 2), "min_rate": g["rate"].min(),
                             "max_rate": g["rate"].max(), "medicare": g["medicare"].iloc[0],
                             "pct_of_medicare": round(100 * g["rate"].median() / g["medicare"].iloc[0])
                             if pd.notna(g["medicare"].iloc[0]) and g["medicare"].iloc[0] else None})
    return pd.DataFrame(rows)


def benchmark_provider(provider: str, codes: str, state: str, payer: str = "all", specialty: str = "",
                       network: str = "", place: str = "office") -> pd.DataFrame:
    """A provider's rates vs. peers in the same state (optionally the same specialty): percentile rank."""
    out = []
    for c in [x.strip() for x in codes.split(",") if x.strip()][:20]:
        mine = _run_core(c, state, payer, None, network or None, None, None, None, provider, "professional")
        per = _run_core(c, state, payer, None, network or None, None, None, specialty or None, None, "professional",
                        wrap=per_pg(place), medicare=False)
        if per.empty:
            out.append({"code": c.upper(), "result": "no published rates in this state"}); continue
        mine = mine[mine["negotiated_type"].isin(DOLLAR_TYPES) & _place_mask(mine, place)] if not mine.empty else mine
        if mine.empty:
            out.append({"code": c.upper(), "result": f"no published rate for {provider} in {state.upper()}",
                        "market_median": per["rate"].median()}); continue
        for (py, prod), g in mine.groupby(["payer", "product"]):
            peers = per[(per["payer"] == py) & (per["product"] == prod)]["rate"]
            r = g["rate"].median()
            med = g["medicare"].iloc[0]
            out.append({"code": c.upper(), "payer": py, "product": prod, "provider": g["provider"].iloc[0],
                        "tin": g["tin"].iloc[0], "your_rate": round(r, 2), "peer_groups": int(len(peers)),
                        "peer_p25": round(peers.quantile(.25), 2), "peer_median": round(peers.median(), 2),
                        "peer_p75": round(peers.quantile(.75), 2), "percentile": round(100 * (peers < r).mean()),
                        "medicare": med, "your_pct_of_medicare": round(100 * r / med) if pd.notna(med) and med else None,
                        "peer_median_pct_of_medicare": round(100 * peers.median() / med) if pd.notna(med) and med else None})
    return pd.DataFrame(out)


def network_breadth(state: str, specialty: str = "", city: str = "", zip_prefix: str = "", payer: str = "all",
                    group_by: str = "product") -> pd.DataFrame:
    """Clinicians (NPIs) and TINs in an area that have any published rate in each network/product."""
    state = _st(state)
    frames = []
    for p in _payers(payer):
        f, prm = ["x.state = $state"], {"state": state}
        if specialty:
            f.append("(x.taxonomy ILIKE $sp OR x.classification ILIKE $sp OR x.specialization ILIKE $sp OR x.taxonomy_code = $spc)")
            prm["sp"], prm["spc"] = f"%{specialty}%", specialty.strip()
        if city:
            f.append("x.city ILIKE $city"); prm["city"] = city.strip()
        if zip_prefix:
            f.append("x.zip5 LIKE $zip"); prm["zip"] = zip_prefix.strip() + "%"
        key = "l.product" if group_by != "network" else "l.label"
        frames.append(_q(f"""
            SELECT '{p}' payer, {key} AS {'product' if group_by != 'network' else 'network'},
                   count(DISTINCT n.npi) AS clinicians, count(DISTINCT pg.tin_value) AS tins
            FROM pg_npi_{p} n JOIN nppes x USING (npi) JOIN pgnet_{p} USING (pg_id)
            JOIN netlabel l ON l.payer = '{p}' AND l.network_id = pgnet_{p}.network_id
            JOIN pg_{p} pg USING (pg_id)
            WHERE n.state = $state AND {' AND '.join(f)}
            GROUP BY ALL ORDER BY clinicians DESC""", prm))
    tot = _q("SELECT count(*) n FROM nppes x WHERE " + " AND ".join(
        ["x.state = $state"] + (["(x.taxonomy ILIKE $sp OR x.classification ILIKE $sp OR x.specialization ILIKE $sp OR x.taxonomy_code = $spc)"] if specialty else [])
        + (["x.city ILIKE $city"] if city else []) + (["x.zip5 LIKE $zip"] if zip_prefix else [])),
        {k: v for k, v in {"state": state, "sp": f"%{specialty}%" if specialty else None, "spc": specialty.strip() if specialty else None,
                           "city": city.strip() if city else None, "zip": zip_prefix.strip() + "%" if zip_prefix else None}.items() if v is not None})
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not df.empty:
        df["nppes_clinicians_in_area"] = int(tot["n"].iloc[0])
        df["share_of_area_pct"] = (100 * df["clinicians"] / max(int(tot["n"].iloc[0]), 1)).round(1)
    return df


def provider_networks(provider: str, state: str = "") -> pd.DataFrame:
    """Which payers/products a provider (NPI, TIN or name) has published rates in."""
    pv = provider.strip()
    frames = []
    for p in payers_loaded():
        if re.fullmatch(r"\d{10}", pv):
            w, prm = "pg_id IN (SELECT pg_id FROM pg_npi_{p} WHERE npi = $v)", {"v": int(pv)}
        elif re.fullmatch(r"\d{2}-?\d{7}", pv):
            w, prm = "pg.tin_value = $v", {"v": pv.replace("-", "")}
        else:
            if not state:
                raise ValueError("searching by name needs a state")
            w, prm = ("pg_id IN (SELECT n.pg_id FROM pg_npi_{p} n JOIN nppes x USING (npi) WHERE n.state = $st AND x.name ILIKE $v)",
                      {"v": f"%{pv}%", "st": _st(state)})
        frames.append(_q(f"""SELECT '{p}' payer, l.product, count(DISTINCT l.network_id) AS networks,
                                    list(DISTINCT pg.tin_value)[1:5] tins, any_value(l.label) example_network
                             FROM pg_{p} pg JOIN pgnet_{p} USING (pg_id)
                             JOIN netlabel l ON l.payer = '{p}' AND l.network_id = pgnet_{p}.network_id
                             WHERE {w.replace('{p}', p)} GROUP BY ALL ORDER BY networks DESC""", prm))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def find_plans(query: str, payer: str = "all") -> pd.DataFrame:
    """Search networks by product, plan or employer name (Aetna lists plan names; others name files by product)."""
    q = f"%{query.strip()}%"
    return _q(f"""SELECT payer, product, label, n_plans,
                         list_filter(plan_names, x -> x ILIKE $q)[1:10] AS matching_plans, file_names[1:3] AS files
                  FROM netlabel WHERE payer IN (SELECT unnest($ps::VARCHAR[]))
                    AND (product ILIKE $q OR label ILIKE $q OR list_contains(list_transform(plan_names, x -> x ILIKE $q), true)
                         OR list_contains(list_transform(file_names, x -> x ILIKE $q), true))
                  ORDER BY payer, product LIMIT 300""", {"q": q, "ps": _payers(payer)})


def list_products(payer: str = "all") -> pd.DataFrame:
    return _q("""SELECT payer, product, count(*) AS networks, sum(n_plans) AS plans FROM netlabel
                 WHERE payer IN (SELECT unnest($ps::VARCHAR[])) GROUP BY ALL ORDER BY payer, networks DESC""",
              {"ps": _payers(payer)})


def search_providers(name: str = "", state: str = "", specialty: str = "", city: str = "", npi: str = "",
                     limit: int = 50) -> pd.DataFrame:
    """NPPES search (by NPI, or name/specialty/city within a state), with the TINs payers list each NPI under."""
    f, prm = [], {}
    if npi:
        f.append("npi = $npi"); prm["npi"] = int(npi)
    else:
        f.append("state = $state"); prm["state"] = _st(state)
        if name:
            f.append("name ILIKE $name"); prm["name"] = f"%{name.strip()}%"
        if specialty:
            f.append("(taxonomy ILIKE $sp OR classification ILIKE $sp OR specialization ILIKE $sp)"); prm["sp"] = f"%{specialty}%"
        if city:
            f.append("city ILIKE $city"); prm["city"] = city.strip()
    df = _q(f"""SELECT npi, name, credential, entity_type, city, state, zip5, taxonomy_code, classification, specialization
                FROM nppes WHERE {' AND '.join(f)} LIMIT {min(int(limit or 50), 500)}""", prm)
    if df.empty:
        return df
    tins = []
    for p in payers_loaded():
        tins.append(_q(f"""SELECT n.npi, '{p}' payer, pg.tin_value FROM pg_npi_{p} n JOIN pg_{p} pg USING (pg_id)
                           WHERE n.npi IN (SELECT unnest($n::BIGINT[]))""", {"n": df["npi"].tolist()}))
    t = pd.concat(tins, ignore_index=True) if tins else pd.DataFrame(columns=["npi", "payer", "tin_value"])
    if not t.empty:
        agg = t.groupby("npi").apply(lambda g: "; ".join(f"{p}: {','.join(sorted(set(x.tin_value)))[:60]}"
                                                         for p, x in g.groupby("payer"))).rename("tins_by_payer")
        df = df.merge(agg, left_on="npi", right_index=True, how="left")
    return df


def code_info(code: str) -> pd.DataFrame:
    """A billing code: which payers publish it, code types, published text where licensable, Medicare PFS amounts."""
    c = _code(code)
    frames = []
    for p in payers_loaded():
        frames.append(_q(f"""SELECT '{p}' payer, billing_code_type, billing_code, any_value(CASE WHEN text_withheld THEN NULL ELSE name END) AS name,
                                    bool_or(text_withheld) AS text_withheld, count(*) AS code_variants
                             FROM code_{p} WHERE billing_code = $c GROUP BY ALL""", {"c": c}))
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    m = _q("SELECT hcpcs, modifier, status, nonfacility_amount, facility_amount, year FROM mcr WHERE hcpcs = $c AND state = 'US'", {"c": c})
    if not m.empty:
        m = m.assign(payer="medicare (PFS, national)")
        df = pd.concat([df, m], ignore_index=True)
    return df


def medicare_rate(codes: str, state: str = "US") -> pd.DataFrame:
    cs = [_code(x) for x in codes.split(",") if x.strip()][:100]
    st = (state or "US").strip().upper()
    return _q("SELECT * FROM mcr WHERE hcpcs IN (SELECT unnest($c::VARCHAR[])) AND state = $s "
              "ORDER BY hcpcs, modifier NULLS FIRST", {"c": cs, "s": st})


_FORBID = re.compile(r"\b(copy|attach|detach|install|load|pragma|set|reset|create|insert|update|delete|drop|alter|export|"
                     r"import|call|checkpoint|vacuum|read_csv|read_json|read_text|read_blob|glob|httpfs|getenv)\b|;", re.I)


def run_sql(sql: str, limit: int = 500) -> pd.DataFrame:
    """Read-only SQL (one SELECT/WITH statement) over the views: rate_<payer>, pt_<payer>, ps_pli_<payer>, pli_pg_<payer>,
    pg_<payer>, pg_npi_<payer>, ns_<payer>, pgnet_<payer>, code_<payer>, netlabel, nppes, mcr."""
    s = sql.strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", s) or _FORBID.search(s) or "read_parquet" in s.lower():
        raise ValueError("only a single SELECT/WITH query over the documented views is allowed")
    return _q(f"SELECT * FROM ({s}) LIMIT {min(int(limit or 500), MAX_ROWS)}")


def data_status() -> dict:
    st = dict(STATUS)
    st["uptime_s"] = round(time.time() - STATUS["started"])
    if _con is not None:
        try:
            st["products"] = list_products().to_dict("records")
        except Exception as e:
            st["products_error"] = repr(e)
    st["log"] = STATUS["log"][-20:]
    return st
