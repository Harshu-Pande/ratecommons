"""Payer front doors, as measured on the October 2026 postings.

Each function returns (raw_files, entries):
  raw_files: {relative_name: bytes} exactly as the payer served them (archived as provenance)
  entries:   normalized dicts, one per file the payer lists
See the design doc's "Payer playbooks" tab for why each step exists.
"""
from __future__ import annotations

import json
import re
import urllib.parse

import requests

from .net import new_session

UHC_BLOBS = "https://transparency-in-coverage.uhc.com/api/v1/uhc/blobs/"
AETNA_BASE = "https://mrf.healthsparq.com/aetnacvs-egress.nophi.kyruushsq.com/prd/mrf/AETNACVS_I/"
# Brand codes that answered in October 2026. AETNACVS and TEXASFI returned nothing;
# they stay in the list so a revival is noticed.
AETNA_BRANDS = ["ALICSI", "ALICFI", "ALICUNDER100", "AFEHBPFI", "ASA", "ASH", "AETNACVS", "TEXASFI"]
CIGNA_LATEST = "https://www.cigna.com/static/mrf/latest.json"


def _get(s: requests.Session, url: str, timeout: float = 300) -> requests.Response:
    r = s.get(url, timeout=timeout)
    r.raise_for_status()
    return r


def _kind(name: str) -> str:
    n = name.lower()
    if "in-network" in n:
        return "in_network"
    if "allowed-amount" in n:
        return "allowed_amounts"
    if n.endswith("_index.json") or "index" in n:
        return "toc"
    if "prescription" in n:
        return "rx"
    return "other"


def uhc(s: requests.Session | None = None):
    s = s or new_session()
    raw = _get(s, UHC_BLOBS).content
    blobs = json.loads(raw)["blobs"]
    entries = []
    for b in blobs:
        name = b["name"]
        entries.append({
            "payer": "uhc", "kind": _kind(name), "name": name, "size": b.get("size"),
            "url": b["downloadUrl"], "key": name[11:] if name[:4].isdigit() else name,
        })
    return {"uhc/blobs.json": raw}, entries


def aetna(s: requests.Session | None = None):
    s = s or new_session()
    raw_files, entries = {}, []
    for brand in AETNA_BRANDS:
        url = f"{AETNA_BASE}{brand}/latest_metadata.json"
        r = s.get(url, timeout=300)
        if r.status_code != 200 or not r.content.lstrip().startswith(b"{"):
            raw_files[f"aetna/{brand}.missing.txt"] = f"{r.status_code} {url}".encode()
            continue
        raw_files[f"aetna/{brand}.json"] = r.content
        for f in json.loads(r.content).get("files", []):
            schema = f.get("fileSchema", "")
            entries.append({
                "payer": "aetna", "brand": brand,
                "kind": {"IN_NETWORK_RATES": "in_network", "ALLOWED_AMOUNTS": "allowed_amounts",
                         "TABLE_OF_CONTENTS": "toc"}.get(schema, "other"),
                "name": f.get("fileName"), "size": None,
                "url": f"{AETNA_BASE}{brand}/{f.get('filePath')}", "key": f.get("filePath"),
                "plans": f.get("reportingPlans", []),
                "reporting_entity": f.get("reportingEntityName"),
                "reporting_entity_type": f.get("reportingEntityType"),
                "last_updated_on": f.get("lastUpdatedOn"),
            })
    return raw_files, entries


def cigna(s: requests.Session | None = None):
    s = s or new_session()
    latest_raw = _get(s, CIGNA_LATEST).content
    latest = json.loads(latest_raw)
    raw_files = {"cigna/latest.json": latest_raw}
    entries = []
    for prog in latest.get("mrfs", []):
        for f in prog.get("files", []):
            toc_raw = _get(s, f["url"], timeout=600).content
            stem = f.get("file_name", "toc.json")
            raw_files[f"cigna/{stem}"] = toc_raw
            toc = json.loads(toc_raw)
            seen = set()
            for rs in toc.get("reporting_structure", []):
                files = [(x, "in_network") for x in rs.get("in_network_files", [])]
                if rs.get("allowed_amount_file"):
                    files.append((rs["allowed_amount_file"], "allowed_amounts"))
                for x, kind in files:
                    base = x["location"].split("?")[0]
                    if base in seen:
                        continue
                    seen.add(base)
                    entries.append({
                        "payer": "cigna", "kind": kind, "name": base.rsplit("/", 1)[-1],
                        "size": None, "url": x["location"], "key": base,
                        "host": urllib.parse.urlparse(base).netloc,
                    })
    return raw_files, entries


PAYERS = {"uhc": uhc, "aetna": aetna, "cigna": cigna}

# Blue Cross Blue Shield. Every Blue plan's index lists two kinds of in-network files:
#  - its own networks (HCSC: Azure blob `.../output/<date>_Blue-Cross-and-Blue-Shield-of-<State>_<network>_...`);
#  - the BlueCard files of every Blue plan, `<YYYY-MM>_<plan code>_<network prefix>_in-network-rates[_k_of_n]`
#    on `<plan>.mrf.bcbs.com` (CloudFront, signed ~1 month). The same BlueCard file is listed by every Blue plan
#    under its own subdomain; it is keyed by file name so it is fetched once. In October 2026 these were 113
#    networks of 56 Blue plans, 0.12 TB in all (Anthem Indiana 30 GB, BCBS North Carolina 19 GB, ...).
BCBS_LANDINGS = {
    "bcbsil": "https://www.bcbsil.com/member/machine-readable-files",
    "bcbstx": "https://www.bcbstx.com/member/machine-readable-files",
}


def _hcsc_index_urls(s: requests.Session, landing: str) -> list[str]:
    """Index URLs linked from an HCSC landing page. A page can name a dated index that is not there (Illinois, 2026-10-29:
    2026-10-23 answered 404), so a missing one is replaced by the newest index of the same name from the last 14 days."""
    import datetime
    import re

    html = _get(s, landing).text
    urls = sorted({u for u in re.findall(r'https://[A-Za-z0-9.-]+\.blob\.core\.windows\.net/toc/[^"\\ <>]+_index\.json', html)
                   if "Prescription" not in u})
    out = []
    for u in urls:
        if s.head(u, timeout=60).status_code == 200:
            out.append(u)
            continue
        m = re.match(r"(.*/)(\d{4}-\d{2}-\d{2})(_.*)$", u)
        for k in range(14) if m else []:
            v = f"{m.group(1)}{(datetime.date.today() - datetime.timedelta(days=k)).isoformat()}{m.group(3)}"
            if s.head(v, timeout=60).status_code == 200:
                out.append(v)
                break
        else:
            out.append(u)  # nothing better: the fetch reports it
    return out


BCBST_DIRECTORY = "https://d7k0rj9u1dp84.cloudfront.net/non_aso_directory.json"  # BCBS of Tennessee, linked from bcbst.com/tcr


def _bcbst_index_urls(s: requests.Session) -> list[str]:
    """BCBS of Tennessee's fully insured index (its ASO directory lists one index per employer, same networks).
    Some CloudFront edges serve a stale directory naming an index that is gone (403; a GitHub runner got the
    2026-09-27 one on 2026-10-28), so the directory is fetched with a cache-buster and, failing that, the newest
    dated index of the last 10 days is probed by name."""
    import datetime
    import time

    try:
        urls = list(_get(s, f"{BCBST_DIRECTORY}?t={int(time.time())}").json().get("TOC_Files", []))
        if urls and s.head(urls[0], timeout=60).status_code == 200:
            return urls
    except Exception:
        pass
    base = BCBST_DIRECTORY.rsplit("/", 1)[0] + "/TCR_TOC_Output/NON-ASO/{}_bcbst_index.json"
    for k in range(10):
        u = base.format((datetime.date.today() - datetime.timedelta(days=k)).isoformat())
        if s.head(u, timeout=60).status_code == 200:
            return [u]
    raise RuntimeError("no BCBST index found")


def bcbs(s: requests.Session | None = None):
    """Blue plans: HCSC (IL, TX) indexes plus BCBS of Tennessee's. Each index lists the plan's own networks and the
    BlueCard files of every Blue plan (`<YYYY-MM>_<plan code>_<prefix>_in-network-rates...` on `*.mrf.bcbs.com`),
    kept once by file name. BCBST lists next month's BlueCard files (2026-11 in Oct 2026); those are skipped, since
    the release takes BlueCard files from HCSC's listing for the same month. Its own files (`TCR_Output_JSON/<net>/
    <date>_890_<prefix>_...`) are kept, including Networks S and P that also appear as BlueCard files 890_58A0/B0."""
    import re

    s = s or new_session()
    raw_files, entries, seen, bc_months = {}, [], set(), []
    try:
        for toc_url in _bcbst_index_urls(s):
            raw = _get(s, toc_url, timeout=600).content
            raw_files[f"bcbs/{toc_url.rsplit('/', 1)[1]}"] = raw
            for rs in json.loads(raw).get("reporting_structure", []):
                for x in rs.get("in_network_files", []):
                    base = x["location"].split("?")[0]
                    name = base.rsplit("/", 1)[-1]
                    if ".mrf.bcbs.com" in base or base in seen or not name.endswith((".json.gz", ".json")):
                        continue
                    seen.add(base)
                    entries.append({"payer": "bcbs", "kind": "in_network", "name": name, "size": None,
                                    "url": x["location"], "key": base, "host": urllib.parse.urlparse(base).netloc,
                                    "listed_by": "bcbst", "description": x.get("description")})
    except Exception as e:  # BCBST's site down: the HCSC part still plans
        import sys
        print("bcbst index unavailable:", repr(e)[:300], file=sys.stderr)
    for plan, landing in BCBS_LANDINGS.items():
        for toc_url in _hcsc_index_urls(s, landing):
            raw = _get(s, toc_url, timeout=600).content
            raw_files[f"bcbs/{toc_url.rsplit('/', 1)[1]}"] = raw
            toc = json.loads(raw)
            for rs in toc.get("reporting_structure", []):
                for x in rs.get("in_network_files", []):
                    base = x["location"].split("?")[0]
                    name = base.rsplit("/", 1)[-1]
                    bluecard = ".mrf.bcbs.com" in base
                    key = name if bluecard else base
                    if key in seen or not name.endswith((".json.gz", ".json")):
                        continue
                    seen.add(key)
                    m = re.match(r"\d{4}-\d{2}_(\d{3})_([0-9A-Z]{4})_", name)
                    if bluecard:
                        bc_months.append(name[:7])
                    entries.append({
                        "payer": "bcbs", "kind": "in_network", "name": name, "size": None, "url": x["location"],
                        "key": key, "host": urllib.parse.urlparse(base).netloc, "listed_by": plan,
                        "bluecard_plan": m and m.group(1), "bluecard_prefix": m and m.group(2),
                    })
    month = max(set(bc_months), key=bc_months.count) if bc_months else None
    names = {e["name"] for e in entries}
    for company, toc_urls_or_files in _blue_own_sources(s):
        for kind, url, raw in toc_urls_or_files:
            if raw is not None:
                raw_files[f"bcbs/{company}/{url.split('?')[0].rsplit('/', 1)[-1]}"] = raw
            for x in ([{"location": url}] if kind == "file" else _toc_in_network(raw)):
                base = x["location"].split("?")[0]
                name = urllib.parse.unquote(base.rsplit("/", 1)[-1])
                bluecard = bool(BLUECARD_NAME.match(name))
                if bluecard and month and not name.startswith(month):
                    continue  # another month's BlueCard file (the release takes the HCSC listing's month)
                key = name if bluecard else base
                if key in seen or not name.endswith((".json.gz", ".json", ".json.zip")):  # Excellus posts .json.zip
                    continue
                seen.add(key)
                # a file's map key comes from its name: two companies' different files with one name (Highmark PA and
                # Highmark Blue Shield PA list 59 such pairs) get the company in front; the listed name is kept
                listed = name
                if name in names:
                    name = f"{company}_{name}"
                names.add(name)
                entries.append({"payer": "bcbs", "kind": "in_network", "name": name, "size": None,
                                "url": x["location"], "key": key, "host": urllib.parse.urlparse(base).netloc,
                                "listed_by": company, "description": x.get("description"),
                                **({"listed_name": listed} if listed != name else {})})
    return raw_files, entries


PAYERS["bcbs"] = bcbs

# Other Blue companies' own networks (October 2026; method and sizes in DECISIONS). Fully insured indexes only: a
# self-funded employer's index repeats the company's networks. A company's BlueCard files (`<YYYY-MM>_<plan>_<prefix>_
# in-network-rates...`) are its own networks as other Blues see them; those already listed by HCSC are skipped by name,
# the rest are new networks. Each source returns the index URLs of the current month (or the files themselves).
BLUECARD_NAME = re.compile(r"^\d{4}-\d{2}_\d{3}_[0-9A-Z]{4}_in-network-rates")
HIGHMARK_HUB = "https://mrfdata.hmhs.com/files/{path}/inbound/local/{month}-01_{name}_index.json"
BLUE_OWN = {
    # HCSC's other states: same Azure blob indexes as IL and TX, linked from each landing page
    "bcbsok": ("hcsc", "https://www.bcbsok.com/member/machine-readable-files"),
    "bcbsnm": ("hcsc", "https://www.bcbsnm.com/member/machine-readable-files"),
    "bcbsmt": ("hcsc", "https://www.bcbsmt.com/member/machine-readable-files"),
    # Sapphire MRF hubs: tocs/<YYYYMM>/<YYYY-MM-01>_<slug>_index.json (fully insured slugs)
    "bcbsm": ("sapphire", "bcbsm", ["blue_cross_blue_shield_of_michigan"]),
    "bcbsla": ("sapphire", "bcbsla", ["hmola", "lahsic"]),
    "bluekc": ("sapphire", "bcbskc", ["blue-cross-and-blue-shield-of-kansas-city"]),
    "horizon": ("sapphire", "horizonblue", ["horizon-healthcare-services-i", "horizon-healthcare-services"]),
    # Highmark's hub (mrfdata.hmhs.com, a static page whose script builds these names); its "363/pa" entries for
    # other Blues are Highmark-administered alliance products, not those companies' networks
    "highmark_pa": ("highmark", "363/pa", "Highmark_Blue_Cross_Blue_Shield_of_Pennsylvania"),
    "highmark_bspa": ("highmark", "378/pa", "Highmark_Blue_Shield_of_Pennsylvania"),
    "highmark_de": ("highmark", "070/del", "Highmark_Blue_Cross_Blue_Shield_of_Delaware"),
    "highmark_wv": ("highmark", "443/wv", "Highmark_Blue_Cross_Blue_Shield_of_West_Virginia"),
    "highmark_wny": ("highmark", "301/wny", "Highmark_Blue_Shield_of_Western_New_York"),
    "highmark_neny": ("highmark", "800/nny", "Highmark_Blue_Shield_of_Northeastern_New_York"),
    "bcbsnd": ("highmark", "320/nd", "BlueCrossBlueShieldND"),
    "bcbswy": ("highmark", "460/wy", "Blue_Cross_Blue_Shield_of_Wyoming"),
    # HealthSparq (the same public egress Aetna uses): <INSURER>/<BRAND>/latest_metadata.json lists every file
    "bsca": ("healthsparq", "BSCA_I", "BSCA"),
    "premera": ("healthsparq", "PREMERA_I", "PREMERA"),
    "excellus": ("healthsparq", "EXC_I", "EXC"),
    "wellmark": ("healthsparq", "WMRK_I", "WELLMARK"),
    "capbc": ("healthsparq", "CAPBC_I", "CAPBC"),
    "bcbsaz": ("healthsparq", "BCBSAZ_I", "BCBSAZ"),
    "bcbsne": ("healthsparq", "BCBSNE_I", "BCBSNE"),
    # one company each
    "bcbsnc": ("dated", "https://mrfmftprod.bcbsnc.com/prod/etl/outbound/table-of-contents/non-aso/"
                        "{date}_blue-cross-and-blue-shield-of-north-carolina_index.json"),
    "ibx": ("monthly", [f"https://storage.googleapis.com/ihg-dart-edw-mrf-prod-public/{b}/{{month}}-01_{b}_index.json"
                        for b in ("qcc", "khpe", "iac")]),
    "floridablue": ("static", ["https://d1hgtx7rrdl2cn.cloudfront.net/mrf/toc/FloridaBlue_Health-Insurance-Issuer_index.json",
                               "https://d1hgtx7rrdl2cn.cloudfront.net/mrf/toc/FloridaBlue_Third-Party-Administrator_index.json"]),
    "carefirst": ("scrape", "https://individual.carefirst.com/individuals-families/mandates-policies/machine-readable-file.page",
                  r"https://stmrffilesprod001\.blob\.core\.windows\.net/mrf-files/[^\"<>]+?_index\.json"),
    "bcbsmn": ("monthly", ["https://mktg.bluecrossmn.com/mrf/{year}/{month}-01_Blue_Cross_and_Blue_Shield_of_Minnesota_index.json"]),
    "bcbsal": ("static", ["https://d3oz7y1cwsecds.cloudfront.net/member-prod/bcbsal"]),
    "arkansas": ("static", ["https://mrf.arkansasbluecross.com/mrf/us_abcbs_hii_arkbluecross_index"]),
    "bcbsms": ("static", ["https://tcr.bcbsms.com/Table_of_Contents/Local_TOC.json"]),
}


def _toc_in_network(raw: bytes) -> list[dict]:
    """in_network_files entries of a table of contents (gzip or not; one object or a list of objects)."""
    import gzip

    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    d = json.loads(raw)
    docs = d if isinstance(d, list) else [d]
    return [x for doc in docs if isinstance(doc, dict) for rs in doc.get("reporting_structure", [])
            for x in rs.get("in_network_files", []) if x.get("location")]


def _blue_own_sources(s: requests.Session, only: set | None = None):
    """(company, [(kind, url, raw)]) per Blue company; kind "toc" (raw = the index) or "file" (an in-network file).
    A company whose site fails is reported on stderr and skipped, so one broken site does not stop the payer."""
    import datetime
    import sys

    today = datetime.date.today()
    months = [today.strftime("%Y-%m"), (today.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")]

    def posted(urls_of):  # this month's index, or last month's while this month's is not posted yet
        for m in months:
            urls = urls_of(m)
            if urls and all(s.get(u, headers={"Range": "bytes=0-0"}, timeout=60).status_code in (200, 206) for u in urls):
                return urls
        return []

    for company, spec in BLUE_OWN.items():
        if only and company not in only:
            continue
        try:
            how, out = spec[0], []
            if how == "hcsc":
                urls = _hcsc_index_urls(s, spec[1])
            elif how == "sapphire":
                urls = posted(lambda m: [f"https://{spec[1]}.sapphiremrfhub.com/tocs/{m.replace('-', '')}/{m}-01_{slug}_index.json"
                                         for slug in spec[2]])
            elif how == "highmark":
                urls = posted(lambda m: [HIGHMARK_HUB.format(path=spec[1], month=m, name=spec[2])])
            elif how == "monthly":
                urls = posted(lambda m: [u.format(month=m, year=m[:4]) for u in spec[1]])
            elif how == "dated":  # the newest index of the last 14 days (missing dates answer 403/404)
                urls = []
                for k in range(14):
                    u = spec[1].format(date=(datetime.date.today() - datetime.timedelta(days=k)).isoformat())
                    if s.get(u, headers={"Range": "bytes=0-0"}, timeout=60).status_code in (200, 206):
                        urls = [u]
                        break
            elif how == "scrape":
                urls = sorted({u.replace(" ", "%20") for u in re.findall(spec[2], _get(s, spec[1]).text)})
            elif how == "static":
                urls = spec[1]
            elif how == "healthsparq":
                insurer, brand = spec[1], spec[2]
                base = f"https://mrf.healthsparq.com/{insurer[:-2].lower()}-egress.nophi.kyruushsq.com/prd/mrf/{insurer}/{brand}/"
                meta = _get(s, base + "latest_metadata.json").content
                out.append(("meta", base + "latest_metadata.json", meta))
                files = json.loads(meta).get("files", [])
                out += [("file", base + f["filePath"], None) for f in files if f.get("fileSchema") == "IN_NETWORK_RATES"]
                urls = [base + f["filePath"] for f in files if f.get("fileSchema") == "TABLE_OF_CONTENTS"] \
                    if not any(f.get("fileSchema") == "IN_NETWORK_RATES" for f in files) else []  # Excellus: TOCs only
            if not urls and how != "healthsparq":
                raise RuntimeError("no index found")
            out += [("toc", u, _get(s, u, timeout=900).content) for u in urls]
            yield company, out
        except Exception as e:
            print(f"bcbs {company}: index unavailable: {e!r}"[:400], file=sys.stderr)

ANTHEM_INDEX = "https://antm-pt-prod-dataz-nogbd-nophi-us-east1.s3.amazonaws.com/anthem/{date}_anthem_index.json.gz"


def anthem(s: requests.Session | None = None, exclude_names: set | None = None):
    """Anthem (Elevance): one index, 11.4 GB gzip (October 2026), every employer's plans repeating the same files.
    Streamed once with a regex for (description, location) pairs; in-network files only. Own networks live on
    Anthem's S3 bucket (`<ST>_<network code>MED<suffix>.json.gz`, 0.8 TB); BlueCard files of other Blue plans on
    `anthem*.mrf.bcbs.com`, labelled e.g. "BCBS Tennessee, Inc. : Network P". BlueCard files already listed by
    payer `bcbs` (exclude_names) are skipped, so each file is parsed once across payers."""
    import datetime
    import re
    import zlib

    s = s or new_session()
    today = datetime.date.today().replace(day=1)
    prev = (today - datetime.timedelta(days=1)).replace(day=1)
    url = None
    for d in (today, prev):
        u = ANTHEM_INDEX.format(date=d.isoformat())
        if s.head(u, timeout=60).status_code == 200:
            url = u
            break
    if url is None:
        raise RuntimeError("no Anthem index for this or last month")
    exclude_names = exclude_names if exclude_names is not None else {e["name"] for e in bcbs(s)[1]}
    pat = re.compile(rb'"description":"([^"]*)","location":"(https://[^"]+)"')
    seen, entries, n_refs = set(), [], 0
    d, tail = zlib.decompressobj(31), b""
    with s.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        for chunk in r.iter_content(8 << 20):
            buf = tail + d.decompress(chunk)
            last = 0
            for m in pat.finditer(buf):
                last = m.end()
                desc, loc = m.group(1).decode("utf8", "replace"), m.group(2).decode()
                n_refs += 1
                if "allowed" in desc.lower():
                    continue
                base = loc.split("?")[0]
                name = base.rsplit("/", 1)[-1]
                bluecard = ".mrf.bcbs.com" in base
                key = name if bluecard else base
                if key in seen or (bluecard and name in exclude_names) or "allowed-amounts" in name:
                    continue
                seen.add(key)
                m2 = re.match(r"\d{4}-\d{2}_(\d{3})_([0-9A-Z]{4})_", name)
                entries.append({
                    "payer": "anthem", "kind": "in_network", "name": name, "size": None, "url": loc, "key": key,
                    "host": urllib.parse.urlparse(base).netloc, "label": desc,
                    "bluecard_plan": m2 and m2.group(1), "bluecard_prefix": m2 and m2.group(2),
                })
            tail = buf[max(last, len(buf) - 65536):]
    summary = json.dumps({"index": url, "location_refs": n_refs, "files": len(entries)}).encode()
    return {"anthem/index-summary.json": summary}, entries


PAYERS["anthem"] = anthem
