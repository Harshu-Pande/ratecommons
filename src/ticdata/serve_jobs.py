"""GitHub Actions entry points for serving packs (see serving.py). Published to the Hub:

  datasets/ratecommons/<payer>   serving/...           one pack per payer
  datasets/ratecommons/identity  serving/nppes.parquet, serving/medicare_pfs.parquet
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import shutil

from .serving import _log, build_medicare, build_nppes, build_pack

ORG = "ratecommons"
NUCC_URLS = [f"https://www.nucc.org/images/stories/CSV/nucc_taxonomy_{v}.csv" for v in (262, 261, 260, 252, 251, 250)]
PFS_URLS = [("2026", "https://www.cms.gov/files/zip/rvu26c-updated-06-30-2026.zip"),
            ("2026", "https://www.cms.gov/files/zip/rvu26c.zip"),
            ("2026", "https://www.cms.gov/files/zip/rvu26b.zip"),
            ("2026", "https://www.cms.gov/files/zip/rvu26a.zip")]


def _upload(repo: str, folder: str, path_in_repo: str, msg: str):
    from huggingface_hub import HfApi

    from .hfio import _retry, dataset, token_for

    api = HfApi(token=token_for(dataset(repo)))
    _retry(lambda: api.upload_folder(repo_id=repo, repo_type="dataset", folder_path=folder, path_in_repo=path_in_repo,
                                     commit_message=msg, delete_patterns=["**"]))


def _get(url: str, path: str) -> bool:
    import requests

    try:
        r = requests.get(url, timeout=600, headers={"User-Agent": "Mozilla/5.0 RateCommons"})
        if r.status_code != 200 or len(r.content) < 1000:
            _log(f"{url}: {r.status_code}")
            return False
        open(path, "wb").write(r.content)
        return True
    except Exception as e:
        _log(f"{url}: {e!r}")
        return False


def shared(work: str = "/tmp/shared", upload: bool = True) -> dict:
    from huggingface_hub import hf_hub_download

    os.makedirs(f"{work}/out", exist_ok=True)
    res: dict = {}
    src = hf_hub_download(f"{ORG}/identity", "nppes/release=2026-10/npi.parquet", repo_type="dataset", local_dir=work)
    nucc = None
    for u in NUCC_URLS:
        if _get(u, f"{work}/nucc.csv"):
            nucc, res["nucc"] = f"{work}/nucc.csv", u
            break
    res["nppes"] = build_nppes(src, f"{work}/out/nppes.parquet", nucc, work=f"{work}/duck")
    os.remove(src)
    for year, u in PFS_URLS:
        if _get(u, f"{work}/pfs.zip"):
            try:
                res["medicare"] = {"url": u, **build_medicare(f"{work}/pfs.zip", f"{work}/out/medicare_pfs.parquet", year)}
                break
            except Exception as e:
                res.setdefault("medicare_errors", []).append(f"{u}: {e!r}")
    json.dump(res, open(f"{work}/out/shared.json", "w"), indent=1, default=str)
    _log(json.dumps(res, default=str))
    if upload:
        _upload(f"{ORG}/identity", f"{work}/out", "serving", "Serving tables: NPPES lite, Medicare PFS")
    return res


def aetna_plans() -> dict[str, list[str]]:
    from huggingface_hub import HfApi, hf_hub_download

    files = sorted(f.path for f in HfApi().list_repo_tree(f"{ORG}/raw-manifests", repo_type="dataset", recursive=True,
                                                         path_in_repo="entries")
                   if f.path.endswith("aetna.jsonl.gz"))
    p = hf_hub_download(f"{ORG}/raw-manifests", files[-1], repo_type="dataset")
    out: dict[str, list[str]] = {}
    for line in gzip.open(p):
        e = json.loads(line)
        if e.get("kind") == "in_network":
            out.setdefault(e["name"], []).extend(x.get("planName", "") for x in e.get("plans") or [])
    return out


def pack(payer: str, source: str, release: str, work: str = "/tmp/pack", upload: bool = True,
         states: list[str] | None = None) -> dict:
    """source: "dataset" (the published release) or "wave-N" (a reduce wave in the work bucket)."""
    from huggingface_hub import hf_hub_download, snapshot_download

    from .config import load

    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    if source == "dataset":
        snapshot_download(f"{ORG}/{payer}", repo_type="dataset", local_dir=f"{work}/src",
                          allow_patterns=[f"release={release}/*"])
        src = f"{work}/src/release={release}"
    else:
        from .hfio import bucket, token_for
        from .reduce import _fetch, _list

        cfg = load()
        tok = token_for(bucket(cfg.work_bucket))
        prefix = f"reduced/{release}/{payer}/{source}"
        paths = _list(cfg.work_bucket, prefix, tok)
        _fetch(cfg.work_bucket, paths, f"{work}/src", prefix, tok)
        src = f"{work}/src"
    _log(f"source ready: {sum(os.path.getsize(p) for p in glob.glob(src + '/**/*.parquet', recursive=True)) / 1e9:.1f} GB")
    nppes = hf_hub_download(f"{ORG}/identity", "serving/nppes.parquet", repo_type="dataset", local_dir=f"{work}/id")
    irs = [hf_hub_download(f"{ORG}/identity", f"irs_eo/release={release}/eo{i}.parquet", repo_type="dataset",
                           local_dir=f"{work}/id") for i in range(1, 5)]
    plans = aetna_plans() if payer == "aetna" else None
    res = build_pack(payer, src, f"{work}/out", nppes, irs, plans=plans, work=f"{work}/duck", states=states)
    res.update({"source": source, "release": release, "states": states})
    json.dump(res, open(f"{work}/out/pack.json", "w"), indent=1, default=str)
    shutil.rmtree(f"{work}/src", ignore_errors=True)
    shutil.rmtree(f"{work}/duck", ignore_errors=True)
    if upload:
        _upload(f"{ORG}/{payer}", f"{work}/out", "serving", f"Serving pack from {source} {release}")
    return res
