"""Public provider identity sources -> Parquet on Hugging Face (track C).

NPPES first: the monthly full replacement file (every NPI, about 9 GB of CSV) plus its
practice-location, other-name and endpoint files, and the monthly deactivation report.
Every value is kept as published (strings); column names are snake_cased and the original
names are stored in the Parquet metadata and in a manifest.
"""
from __future__ import annotations

import json
import os
import re
import time
import zipfile
from pathlib import Path

import requests

from .net import USER_AGENT, download, new_session, resolve

NPPES_PAGE = "https://download.cms.gov/nppes/NPI_Files.html"
NPPES_BASE = "https://download.cms.gov/nppes/"
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}

TABLES = {  # zip member prefix -> table name
    "npidata_pfile": "npi",
    "pl_pfile": "practice_locations",
    "othername_pfile": "other_names",
    "endpoint_pfile": "endpoints",
}


def snake(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip()).strip("_").lower()
    return s or "col"


def nppes_links(s: requests.Session | None = None) -> dict:
    """Links on the NPPES download page; if the page gives none (bot wall, layout change),
    fall back to the documented name pattern for this month and last month."""
    s = s or new_session()
    page_note = None
    try:
        r = s.get(NPPES_PAGE, timeout=60, headers={"User-Agent": USER_AGENT})
        html = r.text
        page_note = f"HTTP {r.status_code}, {len(html)} chars"
    except Exception as ex:
        html, page_note = "", repr(ex)[:200]
    hrefs = sorted(set(re.findall(r"""href\s*=\s*["']?([^"' >]+\.zip)""", html, flags=re.I)))
    absu = lambda h: h if h.startswith("http") else NPPES_BASE + h.lstrip("./")  # noqa: E731
    full = [h for h in hrefs if re.search(r"NPPES_Data_Dissemination_[A-Za-z]+_\d{4}(_V\d)?\.zip$", h)]
    guessed = None
    if not full:
        names = {v: k for k, v in MONTHS.items()}
        y, m = int(time.strftime("%Y")), int(time.strftime("%m"))
        for _ in range(3):
            for suffix in ("_V2", ""):
                url = f"{NPPES_BASE}NPPES_Data_Dissemination_{names[m]}_{y}{suffix}.zip"
                try:
                    if s.head(url, timeout=30, allow_redirects=True,
                              headers={"User-Agent": USER_AGENT}).status_code == 200:
                        guessed = url
                        break
                except Exception:
                    pass
            if guessed:
                break
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        if not guessed:
            guessed = _nber_latest(s)
        if not guessed:
            raise RuntimeError(f"no monthly NPPES file: page {page_note}; first 300 chars {html[:300]!r}")
        full = [guessed]
    m = re.search(r"_([A-Za-z]+)_(\d{4})", full[-1])
    release = f"{m.group(2)}-{MONTHS.get(m.group(1).capitalize(), 0):02d}" if m else time.strftime("%Y-%m")
    return {"release": release, "full": absu(full[-1]),
            "deactivated": [absu(h) for h in hrefs if "Deactivated" in h],
            "weekly": [absu(h) for h in hrefs if "Weekly" in h], "page": page_note, "guessed": bool(guessed)}


NBER_ZIPS = "https://data.nber.org/npi/zip/"


def _nber_latest(s: requests.Session) -> str | None:
    """Newest monthly CMS zip on the NBER mirror (byte copies of the CMS source zips), used while
    the CMS download page is down."""
    try:
        html = s.get(NBER_ZIPS, timeout=60, headers={"User-Agent": USER_AGENT}).text
    except Exception:
        return None
    best = None
    for h in set(re.findall(r"""href\s*=\s*["']?([^"' >]*NPPES_Data_Dissemination_([A-Za-z]+)_(\d{4})(_V\d)?\.zip)""",
                            html, flags=re.I)):
        key = (int(h[2]), MONTHS.get(h[1].capitalize(), 0), h[3])
        if best is None or key > best[0]:
            best = (key, h[0])
    if not best:
        return None
    return best[1] if best[1].startswith("http") else NBER_ZIPS + best[1].split("/")[-1]


def _fetch(url: str, path: str, s: requests.Session) -> dict:
    """Parallel ranged download when the server allows it, else one streaming GET."""
    try:
        r = resolve(url, s)
        if r.size and r.size > 64 << 20:
            return {"url": url, **download(r.url, path, r.size, threads=8, s=s)}
    except Exception as ex:  # fall through to a plain GET
        note = repr(ex)[:200]
    else:
        note = None
    t0 = time.time()
    n = 0
    with s.get(url, stream=True, timeout=(10, 300), headers={"User-Agent": USER_AGENT}) as resp:
        resp.raise_for_status()
        with open(path, "wb") as f:
            for chunk in resp.iter_content(8 << 20):
                f.write(chunk)
                n += len(chunk)
    dt = time.time() - t0
    return {"url": url, "bytes": n, "seconds": round(dt, 1), "mb_per_s": round(n / dt / 1e6, 1),
            "mode": "single GET", **({"range_note": note} if note else {})}


def csv_to_parquet(open_src, dest: str, meta: dict) -> dict:
    """Stream one CSV into ZSTD Parquet with every column read as a string.

    `open_src()` returns a fresh binary file object; it is called twice, once for the
    header (so no type is ever inferred: ZIP codes and IDs keep leading zeros).
    """
    import csv
    import io

    import pyarrow as pa
    import pyarrow.csv as pacsv
    import pyarrow.parquet as pq

    t0 = time.time()
    with open_src() as f:
        names = next(csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace")))
    src = open_src()
    reader = pacsv.open_csv(
        src,
        read_options=pacsv.ReadOptions(block_size=64 << 20),
        convert_options=pacsv.ConvertOptions(column_types={n: pa.string() for n in names},
                                             strings_can_be_null=True),
        parse_options=pacsv.ParseOptions(newlines_in_values=True),
    )
    new = [snake(n) for n in names]
    seen: dict[str, int] = {}
    for i, n in enumerate(new):  # keep names unique after snake-casing
        if n in seen:
            seen[n] += 1
            new[i] = f"{n}_{seen[n]}"
        else:
            seen[n] = 0
    schema = pa.schema([pa.field(n, pa.string()) for n in new],
                       metadata={"source_columns": json.dumps(names), **{k: str(v) for k, v in meta.items()}})
    rows = 0
    with pq.ParquetWriter(dest, schema, compression="zstd", compression_level=6,
                          use_dictionary=True, write_statistics=True) as w:
        for batch in reader:
            cols = [c.cast(pa.string()) for c in batch.columns]
            w.write_batch(pa.RecordBatch.from_arrays(cols, schema=schema), row_group_size=500_000)
            rows += batch.num_rows
    src.close()
    return {"rows": rows, "columns": len(new), "seconds": round(time.time() - t0, 1),
            "parquet_mb": round(os.path.getsize(dest) / 1e6, 1)}


def nppes(workdir: str = "/tmp/nppes", upload_repo: str | None = None) -> dict:
    """Download the monthly NPPES files, convert every CSV to Parquet, optionally upload."""
    s = new_session()
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    links = nppes_links(s)
    rel = links["release"]
    out: dict = {"release": rel, "links": links, "tables": {}}
    zpath = str(wd / "full.zip")
    out["download"] = _fetch(links["full"], zpath, s)
    outdir = wd / "parquet"
    outdir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        out["zip_members"] = [{"name": i.filename, "bytes": i.file_size} for i in z.infolist()]
        for info in z.infolist():
            low = info.filename.lower()
            if not low.endswith(".csv") or "fileheader" in low:
                continue
            table = next((t for p, t in TABLES.items() if low.startswith(p)), None) or snake(Path(low).stem)
            dest = str(outdir / f"{table}.parquet")
            out["tables"][table] = {"member": info.filename, "csv_bytes": info.file_size,
                                    **csv_to_parquet(lambda: z.open(info), dest,
                                                     {"release": rel, "source": links["full"],
                                                      "member": info.filename})}
    os.remove(zpath)
    for i, url in enumerate(links["deactivated"][:1]):
        p = str(wd / "deact.zip")
        out["deactivated_download"] = _fetch(url, p, s)
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                raw = outdir / f"deactivated_{snake(Path(info.filename).stem)}{Path(info.filename).suffix.lower()}"
                raw.write_bytes(z.read(info))  # kept as published (xlsx or csv)
                out["tables"][raw.name] = {"member": info.filename, "bytes": info.file_size}
        os.remove(p)
    (outdir / "manifest.json").write_text(json.dumps(out, indent=2, default=str))
    if upload_repo:
        out["uploaded"] = upload_folder(upload_repo, str(outdir), f"nppes/release={rel}",
                                        f"NPPES {rel}: {', '.join(out['tables'])}")
    return out


def upload_folder(repo_id: str, folder: str, path_in_repo: str, message: str) -> str:
    from huggingface_hub import HfApi

    from .hfio import _retry, dataset, token_for

    api = HfApi(token=token_for(dataset(repo_id)))
    _retry(lambda: api.upload_folder(repo_id=repo_id, repo_type="dataset", folder_path=folder,
                                     path_in_repo=path_in_repo, commit_message=message))
    return f"https://huggingface.co/datasets/{repo_id}/tree/main/{path_in_repo}"


# ---------------------------------------------------------------- other public identity files

CMS_PROVIDER_DATA = "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/{id}"
SOURCES = {
    # Doctors and Clinicians national downloadable file (one row per clinician x group x address)
    "dac": {"kind": "cms_provider_data", "id": "mj5m-pzi6"},
    # IRS exempt organizations business master file, four regional CSVs
    "irs_eo": {"kind": "urls", "urls": [f"https://www.irs.gov/pub/irs-soi/eo{i}.csv" for i in range(1, 5)]},
}


def _source_urls(name: str, s: requests.Session) -> tuple[str, list[str], dict]:
    src = SOURCES[name]
    if src["kind"] == "urls":
        return time.strftime("%Y-%m"), src["urls"], {}
    meta = s.get(CMS_PROVIDER_DATA.format(id=src["id"]), timeout=60,
                 headers={"User-Agent": USER_AGENT}).json()
    urls = [d["downloadURL"] for d in meta.get("distribution", []) if d.get("downloadURL")]
    rel = (meta.get("modified") or meta.get("issued") or time.strftime("%Y-%m-%d"))[:7]
    return rel, urls, {"title": meta.get("title"), "modified": meta.get("modified")}


def load_source(name: str, workdir: str = "/tmp/ident", upload_repo: str | None = None) -> dict:
    """Download a public identity CSV source and store it as Parquet (all strings), as published."""
    s = new_session()
    wd = Path(workdir) / name
    wd.mkdir(parents=True, exist_ok=True)
    rel, urls, info = _source_urls(name, s)
    out: dict = {"source": name, "release": rel, "info": info, "files": {}}
    outdir = wd / "parquet"
    outdir.mkdir(exist_ok=True)
    for url in urls:
        stem = snake(Path(url.split("?", 1)[0]).stem)
        local = str(wd / f"{stem}.csv")
        dl = _fetch(url, local, s)
        dest = str(outdir / f"{stem}.parquet")
        conv = csv_to_parquet(lambda: open(local, "rb"), dest, {"release": rel, "source": url})
        out["files"][stem] = {"url": url, "download": dl, **conv}
        os.remove(local)
    (outdir / "manifest.json").write_text(json.dumps(out, indent=2, default=str))
    if upload_repo:
        out["uploaded"] = upload_folder(upload_repo, str(outdir), f"{name}/release={rel}",
                                        f"{name} {rel}: {', '.join(out['files'])}")
    return out
