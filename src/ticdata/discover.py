"""Payer front doors, as measured on the October 2026 postings.

Each function returns (raw_files, entries):
  raw_files: {relative_name: bytes} exactly as the payer served them (archived as provenance)
  entries:   normalized dicts, one per file the payer lists
See the design doc's "Payer playbooks" tab for why each step exists.
"""
from __future__ import annotations

import json
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
