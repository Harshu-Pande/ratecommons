"""Hospital price transparency files (45 CFR 180): discovery, download and normalization.

Discovery: since 2024 every hospital must publish `cms-hpt.txt` at the root of its website, listing each location's
name, the page that links its file, the machine-readable file URL and a contact. One system's file usually covers
all of its hospitals (bjc.org lists 15). We seed website domains from every source we have (DoltHub's 2023
hospital list with homepage and chargemaster URLs, the domains of files already found, and the contact e-mail
domains inside cms-hpt.txt files, which often name the system's main site), fetch cms-hpt.txt from each domain and
its www. variant, and keep every entry as published. Aggregator link lists (PatientRightsAdvocate, Turquoise,
Trilliant) are cross-checks only: the hospital's own cms-hpt.txt is the source of truth.

Identity: a file names its hospital by EIN (often in the file name), the `type_2_npi` list (required since
2026-01-01; these are the same NPIs payers use as TINs, e.g. Barnes-Jewish 1649299827 in Anthem's files), license
number and addresses. Those join to payer files and to the site registry; names never decide identity.

Normalization (v1, CMS JSON schema v2/v3): one row per item x code x setting x payer/plan with the published
dollar amount, percentage, algorithm, methodology, the 2026 median / 10th / 90th percentile allowed amounts and
their count (actual paid claims: direct evidence that a rate is real), gross charge and discounted cash price.
CSV layouts (tall and wide) come next.
"""
from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import urlparse

from .serving import _log

DOLT_NOTE = "DoltHub's 2023 hospital list and Wikidata seed the crawl; each round adds domains found inside cms-hpt.txt files"

UA = "RateCommons/1.0 (+https://ratecommons.org; public price transparency research)"
DOLT = "https://www.dolthub.com/api/v1alpha1/dolthub/hospital-price-transparency-v3/main"


def _domain(u: str | None) -> str | None:
    if not u:
        return None
    try:
        h = urlparse(u if "://" in u else "https://" + u).hostname
    except Exception:
        return None
    if not h or "." not in h:
        return None
    h = h.lower()
    return h[4:] if h.startswith("www.") else h


def parse_hpt(text: str) -> list[dict]:
    """cms-hpt.txt: blank-line separated blocks of 'key: value' lines."""
    out, cur = [], {}
    for line in text.splitlines():
        line = line.strip().lstrip("﻿")
        if not line:
            if cur:
                out.append(cur)
                cur = {}
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().lower()
            if k in ("location-name", "source-page-url", "mrf-url", "contact-name", "contact-email"):
                if k == "location-name" and "location-name" in cur:
                    out.append(cur)
                    cur = {}
                cur[k] = v.strip()
    if cur:
        out.append(cur)
    return [e for e in out if e.get("mrf-url")]


def _get_hpt(domain: str) -> tuple[str, list[dict], str]:
    import requests

    for host in (f"https://{domain}", f"https://www.{domain}"):
        try:
            r = requests.get(f"{host}/cms-hpt.txt", timeout=25, headers={"User-Agent": UA}, allow_redirects=True)
        except Exception as e:
            last = repr(e)[:120]
            continue
        ct = r.headers.get("content-type", "")
        if r.status_code == 200 and "html" not in ct.lower() and "mrf-url" in r.text.lower():
            return domain, parse_hpt(r.text), f"{host}/cms-hpt.txt"
        last = f"{r.status_code} {ct[:40]}"
    return domain, [], last


def seed_domains(extra: list[str] | None = None) -> list[str]:
    import requests

    doms = set(extra or [])
    off = 0
    while True:
        q = ("SELECT homepage_url, chargemaster_url FROM hospitals ORDER BY cms_certification_num "
             f"LIMIT 1000 OFFSET {off}")
        try:
            rows = requests.get(DOLT, params={"q": q}, timeout=120).json().get("rows", [])
        except Exception as e:
            _log(f"dolt: {e!r}")
            break
        for r in rows:
            for u in (r.get("homepage_url"), r.get("chargemaster_url")):
                d = _domain(u)
                if d:
                    doms.add(d)
        if len(rows) < 1000:
            break
        off += 1000
    # Wikidata: every US hospital with an official website (about 2,700)
    try:
        q = ("SELECT DISTINCT ?site WHERE { ?h wdt:P31/wdt:P279* wd:Q16917; wdt:P17 wd:Q30; wdt:P856 ?site. }")
        r = requests.get("https://query.wikidata.org/sparql", params={"query": q}, timeout=180,
                         headers={"Accept": "text/csv", "User-Agent": UA})
        for line in r.text.splitlines()[1:]:
            d = _domain(line.strip())
            if d:
                doms.add(d)
    except Exception as e:
        _log(f"wikidata: {e!r}")
    return sorted(doms)


def discover(work: str = "/tmp/hpt", upload_to: str | None = "ratecommons/work", prefix: str = "hospitals/index",
             rounds: int = 3, threads: int = 48) -> dict:
    """Crawl cms-hpt.txt files. Each round adds the domains found inside the files already read (mrf-url hosts that
    are hospital sites, contact e-mail domains), until nothing new turns up."""
    from concurrent.futures import ThreadPoolExecutor

    t0 = time.time()
    os.makedirs(work, exist_ok=True)
    tried: dict = {}
    entries: list[dict] = []
    todo = seed_domains()
    for rnd in range(rounds):
        todo = [d for d in todo if d not in tried]
        if not todo:
            break
        _log(f"round {rnd}: {len(todo)} domains")
        with ThreadPoolExecutor(threads) as ex:
            for dom, ents, how in ex.map(_get_hpt, todo):
                tried[dom] = how if not ents else "ok"
                for e in ents:
                    e["domain"], e["hpt_url"] = dom, how
                    entries.append(e)
        new = set()
        for e in entries:
            for d in (_domain(e.get("mrf-url")), _domain(e.get("source-page-url")),
                      (e.get("contact-email") or "").split("@")[-1].lower() or None):
                if d and d not in tried:
                    new.add(d)
        todo = sorted(new)
    # one row per (mrf-url, location-name)
    seen, rows = set(), []
    for e in entries:
        k = (e.get("mrf-url"), e.get("location-name"))
        if k in seen:
            continue
        seen.add(k)
        m = re.search(r"(?<!\d)(\d{2}-?\d{7})(?!\d)", os.path.basename(urlparse(e["mrf-url"]).path))
        rows.append({"location_name": e.get("location-name"), "mrf_url": e.get("mrf-url"),
                     "source_page_url": e.get("source-page-url"), "contact_email_domain": (e.get("contact-email") or "").split("@")[-1],
                     "domain": e["domain"], "hpt_url": e["hpt_url"], "ein_in_name": m.group(1).replace("-", "") if m else None})
    os.makedirs(f"{work}/out", exist_ok=True)
    import duckdb

    con = duckdb.connect()
    con.execute(f"CREATE TABLE t AS SELECT * FROM read_json_auto('{_dump(rows, f'{work}/rows.json')}')")
    con.execute(f"COPY t TO '{work}/out/cms_hpt_index.parquet' (FORMAT parquet)")
    json.dump(tried, open(f"{work}/out/domains_tried.json", "w"))
    res = {"domains_tried": len(tried), "domains_with_file": sum(1 for v in tried.values() if v == "ok"),
           "locations": len(rows), "mrf_urls": len({r["mrf_url"] for r in rows}), "seconds": round(time.time() - t0)}
    json.dump(res, open(f"{work}/out/discover.json", "w"))
    _log(json.dumps(res))
    if upload_to:
        from .cloudpack import upload

        res["uploaded"] = upload(f"{work}/out", prefix, upload_to)
    return res


def _dump(rows, path):
    json.dump(rows, open(path, "w"))
    return path


# ---- normalization --------------------------------------------------------------------------------------------------
def normalize_json(path: str, out_path: str, codes: set[str] | None = None) -> dict:
    """Stream a CMS JSON file (schema v2/v3) into a parquet of priced rows. `codes` limits to some billing codes."""
    import ijson
    import pyarrow as pa
    import pyarrow.parquet as pq

    head = {}
    with open(path, "rb") as f:
        for k, ev, v in ijson.parse(f):
            if k in ("hospital_name", "last_updated_on", "version") and ev in ("string", "number"):
                head[k] = v
            elif k in ("type_2_npi.item", "location_name.item", "hospital_address.item") and ev == "string":
                head.setdefault(k.split(".")[0], []).append(v)
            elif k == "standard_charge_information":
                break
    cols = {c: [] for c in ("description", "code", "code_type", "setting", "gross", "cash", "payer", "plan", "methodology",
                            "dollar", "percentage", "algorithm", "median_allowed", "p10", "p90", "count", "notes", "modifiers",
                            "billing_class")}
    n = 0
    with open(path, "rb") as f:
        for it in ijson.items(f, "standard_charge_information.item", use_float=True):
            ci = it.get("code_information") or []
            mine = [c for c in ci if not codes or str(c.get("code")) in codes]
            if not mine:
                continue
            for sc in it.get("standard_charges") or []:
                payers = sc.get("payers_information") or [{}]
                for p in payers:
                    for c in mine:
                        cols["description"].append(it.get("description"))
                        cols["code"].append(str(c.get("code")))
                        cols["code_type"].append(c.get("type"))
                        cols["setting"].append(sc.get("setting"))
                        cols["gross"].append(sc.get("gross_charge"))
                        cols["cash"].append(sc.get("discounted_cash"))
                        cols["payer"].append(p.get("payer_name"))
                        cols["plan"].append(p.get("plan_name"))
                        cols["methodology"].append(p.get("methodology"))
                        cols["dollar"].append(p.get("standard_charge_dollar"))
                        cols["percentage"].append(p.get("standard_charge_percentage"))
                        cols["algorithm"].append((p.get("standard_charge_algorithm") or None) and str(p.get("standard_charge_algorithm"))[:500])
                        cols["median_allowed"].append(p.get("median_amount", p.get("estimated_amount")))
                        cols["p10"].append(p.get("10th_percentile"))
                        cols["p90"].append(p.get("90th_percentile"))
                        cols["count"].append(None if p.get("count") is None else str(p.get("count")))
                        cols["notes"].append(p.get("additional_payer_notes"))
                        cols["modifiers"].append(",".join(sc.get("modifier_code") or it.get("modifier_code") or []) or None)
                        cols["billing_class"].append(sc.get("billing_class") or it.get("billing_class"))
                        n += 1
    for k in ("gross", "cash", "dollar", "percentage", "median_allowed", "p10", "p90"):
        cols[k] = [float(x) if isinstance(x, (int, float)) or (isinstance(x, str) and re.fullmatch(r"[\d.]+", x)) else None
                   for x in cols[k]]
    t = pa.table(cols)
    pq.write_table(t, out_path, compression="zstd")
    return {"rows": n, **{k: (v if not isinstance(v, list) else v[:20]) for k, v in head.items()}}


def normalize_csv_tall(path: str, out_path: str, codes: set[str] | None = None) -> dict:
    """CMS CSV 'tall' layout (one row per item x payer/plan): two header-block rows, then the column row."""
    import duckdb

    con = duckdb.connect()
    # null_padding needs the single-threaded reader on some files ("Parallel CSV Reader currently does not support")
    con.execute(f"""CREATE VIEW raw AS SELECT * FROM read_csv('{path}', skip = 2, header = true, all_varchar = true,
                    quote = '"', escape = '"', strict_mode = false, null_padding = true, parallel = false,
                    max_line_size = 20000000)""")
    cols = [c[0] for c in con.execute("DESCRIBE raw").fetchall()]
    if "payer_name" not in cols:
        return {"error": "not the tall layout", "columns": cols[:30]}
    q = lambda c: f'"{c}"' if c in cols else "NULL"
    code_slots = [i for i in range(1, 9) if f"code|{i}" in cols]
    want = ", ".join(f"'{c}'" for c in sorted(codes)) if codes else None
    parts = []
    for i in code_slots:
        parts.append(f"""SELECT {q('description')} AS description, "code|{i}" AS code, {q(f'code|{i}|type')} AS code_type,
               {q('setting')} AS setting, TRY_CAST({q('standard_charge|gross')} AS DOUBLE) AS gross,
               TRY_CAST({q('standard_charge|discounted_cash')} AS DOUBLE) AS cash, payer_name AS payer, {q('plan_name')} AS plan,
               {q('standard_charge|methodology')} AS methodology,
               TRY_CAST({q('standard_charge|negotiated_dollar')} AS DOUBLE) AS dollar,
               TRY_CAST({q('standard_charge|negotiated_percentage')} AS DOUBLE) AS percentage,
               left({q('standard_charge|negotiated_algorithm')}, 500) AS algorithm,
               TRY_CAST(coalesce({q('median_amount')}, {q('estimated_amount')}) AS DOUBLE) AS median_allowed,
               TRY_CAST({q('10th_percentile')} AS DOUBLE) AS p10, TRY_CAST({q('90th_percentile')} AS DOUBLE) AS p90,
               {q('count')} AS count, {q('additional_generic_notes')} AS notes, {q('modifiers')} AS modifiers,
               {q('billing_class')} AS billing_class
        FROM raw WHERE "code|{i}" IS NOT NULL {f'AND "code|{i}" IN ({want})' if want else ''}""")
    con.execute(f"COPY ({' UNION ALL '.join(parts)}) TO '{out_path}' (FORMAT parquet, COMPRESSION zstd)")
    n = con.execute(f"SELECT count(*) FROM '{out_path}'").fetchone()[0]
    return {"rows": n}


PAYER_FAMILY = [  # hospital payer/plan text -> our payer; Medicare Advantage and Medicaid plans are labelled apart
    ("medicare_advantage", r"MEDICARE|ADVANTAGE|ADVANTRA|HUMANA GOLD|ESSENCE|DEVOTED|WELLCARE|\bMA\b|DSNP|D-SNP"),
    ("medicaid", r"MEDICAID|HEALTHNET|HEALTHY BLUE|HOME STATE|COMMUNITY PLAN|MOLINA|CENTENE|AMBETTER"),
    ("aetna", r"AETNA"),
    ("cigna", r"CIGNA"),
    ("uhc", r"UNITED|UHC|\bUMR\b|OPTUM"),
    ("anthem", r"ANTHEM|BLUE CROSS|BLUECROSS|\bBCBS\b"),
]


def payer_family(payer: str | None, plan: str | None) -> str | None:
    t = f"{payer or ''} {plan or ''}".upper()
    for fam, rx in PAYER_FAMILY:
        if re.search(rx, t):
            return fam
    return None


def facility_fees(norm_paths: dict, codes: set[str]) -> list[dict]:
    """Per hospital (ccn) x payer family x code: the facility amount a patient's plan pays, chosen as the published
    dollar amount, else percentage x gross charge, else the median allowed amount; with the claim count when given.
    norm_paths: ccn -> normalized parquet."""
    import duckdb

    con = duckdb.connect()
    out = []
    for ccn, p in norm_paths.items():
        have = {c[0] for c in con.execute(f"DESCRIBE SELECT * FROM '{p}'").fetchall()}
        bcol = "billing_class" if "billing_class" in have else "NULL"
        rows = con.execute(f"""SELECT code, payer, plan, methodology, dollar, percentage, gross, cash, median_allowed, count,
                                      coalesce({bcol}, 'facility') AS bc, setting, modifiers
                               FROM '{p}' WHERE code IN ({", ".join(f"'{c}'" for c in codes)})""").fetchall()
        best: dict = {}
        cash: dict = {}
        for code, payer, plan, meth, dollar, pct, gross, csh, med, cnt, bc, setting, mods in rows:
            if (bc or "").lower() not in ("facility", "") or (mods or "").strip() not in ("", "None"):
                continue
            if setting and setting.lower() == "inpatient":
                continue
            if csh:
                cash[code] = csh
            fam = payer_family(payer, plan)
            if not fam:
                continue
            amt, how = None, None
            n = None
            try:
                n = int(str(cnt).split()[0]) if cnt and str(cnt)[0].isdigit() else None
            except Exception:
                n = None
            if n and med and med > 0:  # what was actually paid on this plan's claims, when the hospital reports it
                amt, how = med, "median_allowed"
            elif dollar and dollar > 0:
                amt, how = dollar, "dollar"
            elif pct and gross:
                amt, how = round(pct / 100.0 * gross, 2), "percent_of_charges"
            elif med and med > 0:
                amt, how = med, "median_allowed"
            if amt is None:
                continue
            k = (fam, code)
            best.setdefault(k, []).append((amt, how, med, n, (plan or payer or "")[:60]))
        for (fam, code), xs in best.items():
            paid = [x for x in xs if x[3]]  # plans with paid claims first: a rate nobody is billed under is a ghost
            xs = sorted(paid or xs, key=lambda x: x[0])
            mid = xs[(len(xs) - 1) // 2]
            out.append({"ccn": ccn, "payer": fam, "code": code, "rate": mid[0], "how": mid[1], "median_allowed": mid[2],
                        "count": max((x[3] or 0) for x in xs), "lo": xs[0][0], "hi": xs[-1][0], "plans": len(xs),
                        "cash": cash.get(code)})
    return out
