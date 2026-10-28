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


# Payers whose whole release fits one runner's serving pack. The others get a common-services pack: the codes
# CareCompass prices plus flat all-services contracts (CSTM-ALL). Measured 2026-10-28: the full BCBS release has
# 3.7 billion provider set -> list links and Aetna's 41.8 billion; the common services are about 0.5% of the facts.
FULL_PACK = {"cigna"}


def common_codes() -> list[str]:
    from .shopcatalog import all_codes

    return sorted(set(all_codes()))


def _stream_files(repo: str, paths: list[str], dest: str, ahead: int = 3):
    """Download dataset files a few at a time, in order; yields (repo path, local path). The caller deletes each."""
    from concurrent.futures import ThreadPoolExecutor

    from huggingface_hub import hf_hub_download

    def get(path):
        for attempt in range(5):
            try:
                return hf_hub_download(repo, path, repo_type="dataset", local_dir=dest)
            except Exception as e:  # noqa: PERF203
                _log(f"download retry {attempt} {path}: {e!r}")
                import time

                time.sleep(15 * (attempt + 1))
        raise RuntimeError(f"download failed: {path}")

    with ThreadPoolExecutor(ahead) as ex:
        futs = [ex.submit(get, p) for p in paths[:ahead]]
        for i, path in enumerate(paths):
            local = futs[i].result()
            if i + ahead < len(paths):
                futs.append(ex.submit(get, paths[i + ahead]))
            yield path, local


def prefilter(payer: str, release: str, codes: list[str], dest: str, work: str, main: list | None = None) -> dict:
    """Write a release folder holding only the facts for `codes` (plus CSTM-ALL) and the dimension rows they
    use, streaming the published release one file at a time (the whole BCBS release is 110 GB, Aetna's 600 GB).
    build_pack then runs on it unchanged.
    main: network ids that keep EVERY code. A fact of another code is kept when its network set holds a main
    network, under a derived network set listing only its main networks (so other networks never look as if
    they had that code). Aetna's top 20 networks hold ~3% of its facts."""
    from huggingface_hub import HfApi

    from .serving import _duck

    repo = f"{ORG}/{payer}"
    root = f"release={release}"
    files = sorted(f.path for f in HfApi().list_repo_tree(repo, repo_type="dataset", path_in_repo=root, recursive=True)
                   if f.path.endswith(".parquet"))

    def table(t):
        return [f for f in files if f.startswith(f"{root}/{t}/") or f == f"{root}/{t}.parquet"]

    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    dl = f"{work}/dl"
    con = _duck(f"{work}/duck")
    res: dict = {"codes": len(codes)}

    def out_path(path):
        o = f"{dest}/{path[len(root) + 1:]}"
        os.makedirs(os.path.dirname(o), exist_ok=True)
        return o

    for t in ("source_file", "network", "code"):
        for path, local in _stream_files(repo, table(t), dl):
            shutil.move(local, out_path(path))
    cl = ", ".join("'" + c.replace("'", "''") + "'" for c in codes)
    common = f"(r.billing_code IN ({cl}) OR r.billing_code_type = 'CSTM-ALL')"
    ns_all = f"{work}/ns_all"
    if main:  # network sets holding a main network, and their derived "main networks only" twins
        os.makedirs(ns_all, exist_ok=True)
        con.execute("CREATE TABLE seen_ns (ns_id BLOB)")
        for path, local in _stream_files(repo, table("network_set"), dl):  # each set once (it repeats per fact slice)
            o = f"{ns_all}/{os.path.basename(path)}"
            con.execute(f"COPY (SELECT * FROM read_parquet('{local}') ANTI JOIN seen_ns USING (ns_id)) TO '{o}' "
                        "(FORMAT parquet, COMPRESSION zstd)")
            con.execute(f"INSERT INTO seen_ns SELECT ns_id FROM read_parquet('{o}')")
            os.remove(local)
        con.execute("DROP TABLE seen_ns")
        con.execute(f"""CREATE TABLE mainns AS SELECT ns_id, unhex(md5(hex(ns_id) || ':main')) AS d_id
                        FROM read_parquet('{ns_all}/*.parquet') WHERE list_has_any(network_ids, ?)""", [main])
        res["main_networks"] = len(main)
        res["main_network_sets"] = con.execute("SELECT count(*) FROM mainns").fetchone()[0]
        _log(f"main networks {len(main)}: {res['main_network_sets']:,} network sets hold one")
    n = 0
    for path, local in _stream_files(repo, table("rate_fact"), dl):
        o = out_path(path)
        if main:
            con.execute(f"""COPY (SELECT r.* REPLACE (CASE WHEN {common} THEN r.ns_id ELSE m.d_id END AS ns_id)
                                  FROM read_parquet('{local}') r LEFT JOIN mainns m ON m.ns_id = r.ns_id
                                  WHERE {common} OR m.ns_id IS NOT NULL) TO '{o}' (FORMAT parquet, COMPRESSION zstd)""")
        else:
            con.execute(f"COPY (SELECT * FROM read_parquet('{local}') r WHERE {common}) TO '{o}' "
                        "(FORMAT parquet, COMPRESSION zstd)")
        os.remove(local)
        n += con.execute(f"SELECT count(*) FROM read_parquet('{o}')").fetchone()[0]
    res["facts"] = n
    _log(f"facts kept: {n:,}")
    F = f"read_parquet('{dest}/rate_fact/*.parquet')"
    con.execute(f"CREATE TABLE k_ns AS SELECT DISTINCT ns_id FROM {F}")
    con.execute(f"CREATE TABLE k_pl AS SELECT DISTINCT pl_id FROM {F}")
    con.execute(f"CREATE TABLE k_ps AS SELECT DISTINCT ps_id FROM {F}")

    def keep(t, key, keys, then=None, once=False):
        """Copy the rows of table t whose key is in table `keys`; `then` = (new key table, SQL over the output).
        once: keep each key once across files (network_set is written per fact slice, so a set repeats in up to
        16 parts; unnesting the repeats ran Aetna's pack out of memory)."""
        outs = []
        if once:
            con.execute(f"CREATE TABLE seen_{t} AS SELECT * FROM {keys} WHERE false")
        for path, local in _stream_files(repo, table(t), dl):
            o = out_path(path)
            anti = f"ANTI JOIN seen_{t} USING ({key})" if once else ""
            con.execute(f"COPY (SELECT * FROM read_parquet('{local}') SEMI JOIN {keys} USING ({key}) {anti}) TO '{o}' "
                        "(FORMAT parquet, COMPRESSION zstd)")
            if once:
                con.execute(f"INSERT INTO seen_{t} SELECT DISTINCT {key} FROM read_parquet('{o}')")
            os.remove(local)
            outs.append(o)
        res[t] = con.execute(f"SELECT count(*) FROM read_parquet({outs!r})").fetchone()[0] if outs else 0
        _log(f"{t} kept: {res[t]:,}")
        if then and outs:
            con.execute(f"CREATE TABLE {then[0]} AS SELECT DISTINCT {then[1]} FROM read_parquet({outs!r})")

    if main:  # network sets from the local copy: the kept originals, plus derived twins listing main networks only
        os.makedirs(f"{dest}/network_set", exist_ok=True)
        con.execute(f"""COPY (SELECT * FROM read_parquet('{ns_all}/*.parquet') SEMI JOIN k_ns USING (ns_id))
                        TO '{dest}/network_set/part-00.parquet' (FORMAT parquet, COMPRESSION zstd)""")
        con.execute(f"""COPY (SELECT n.* REPLACE (m.d_id AS ns_id, list_filter(n.network_ids, x -> list_contains(?, x)) AS network_ids)
                              FROM read_parquet('{ns_all}/*.parquet') n JOIN mainns m USING (ns_id)
                              WHERE m.d_id IN (SELECT ns_id FROM k_ns))
                        TO '{dest}/network_set/part-01.parquet' (FORMAT parquet, COMPRESSION zstd)""", [main])
        shutil.rmtree(ns_all, ignore_errors=True)
        res["network_set"] = con.execute(f"SELECT count(*) FROM read_parquet('{dest}/network_set/*.parquet')").fetchone()[0]
        _log(f"network_set kept: {res['network_set']:,}")
    else:
        keep("network_set", "ns_id", "k_ns", once=True)
    keep("price_list", "pl_id", "k_pl", ("k_pt", "unnest(pt_ids) AS pt_id"))
    keep("price_term", "pt_id", "k_pt")
    keep("provider_set", "ps_id", "k_ps", ("k_pli", "unnest(pli_ids) AS pli_id"))
    keep("provider_list", "pli_id", "k_pli", ("k_pg", "unnest(pg_ids) AS pg_id"))
    keep("provider_group", "pg_id", "k_pg")
    con.close()
    shutil.rmtree(dl, ignore_errors=True)
    shutil.rmtree(f"{work}/duck", ignore_errors=True)
    return res


PRODUCT_MODE_NETWORKS = 2000  # above this many networks the app copy groups networks by product (Aetna: 6,219)


def _label_fn():
    """The app's own network labeler (cloud/api/_rc.py), so packs, the app and CareCompass name products alike."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("rcapi", os.path.join(os.path.dirname(__file__), "..", "..",
                                                                         "cloud", "api", "_rc.py"))
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    return rc._label


def network_products(payer: str, src: str, plans: dict | None) -> dict | None:
    """network_id -> product label, for payers with more than PRODUCT_MODE_NETWORKS networks; else None."""
    import duckdb

    rows = duckdb.sql(f"SELECT network_id, list(name ORDER BY name) FROM read_parquet('{src}/source_file.parquet') "
                      "GROUP BY 1").fetchall()
    if len(rows) <= PRODUCT_MODE_NETWORKS:
        return None
    label = _label_fn()
    out = {}
    for nid, names in rows:
        pl = [x for n in names for x in (plans or {}).get(n, [])]
        out[nid] = label(payer, names, pl)[0]
    _log(f"product mode: {len(rows)} networks -> {len(set(out.values()))} products")
    return out


MAIN_NETWORKS = int(os.environ.get("RC_MAIN_NETWORKS", "20"))


def main_networks(payer: str, release: str, plans: dict | None, n: int = MAIN_NETWORKS) -> list:
    """The networks that keep every code, as whole network families (a family is every network id carrying the same
    app label: BCBS Tennessee posts Network S as 32 part files, Anthem splits files into _01_04 parts, and each part
    is its own network id). Aetna: the n families used by the most employer plans. BCBS: every home family of the
    plans in RC_BCBS_MAIN_PLANS (default TN). Anthem: its n largest own families. Returns network ids."""
    import re

    import duckdb
    from huggingface_hub import hf_hub_download

    sf = hf_hub_download(f"{ORG}/{payer}", f"release={release}/source_file.parquet", repo_type="dataset")
    rows = duckdb.sql(f"SELECT network_id, list(name), sum(bytes) FROM read_parquet('{sf}') GROUP BY 1").fetchall()
    fam: dict = {}
    if payer == "aetna":  # one family per file group (a file name can carry two network ids, one without facts)
        for nid, names, b in rows:
            g = fam.setdefault(tuple(sorted(names)), {"ids": [], "score": set()})
            g["ids"].append(nid)
            g["score"].update(p for nm in names for p in (plans or {}).get(nm, []))
        ranked = sorted(fam.values(), key=lambda g: -len(g["score"]))[:n]
        return [i for g in ranked for i in g["ids"]]
    label = _label_fn()
    want = os.environ.get("RC_BCBS_MAIN_PLANS", "TN").split(",")
    for nid, names, b in rows:
        if payer == "bcbs":  # home networks only (BlueCard files are other plans' networks)
            if all(re.match(r"\d{4}-\d{2}_\d{3}_[0-9A-Z]{4}_", x) for x in names):
                continue
            x = " ".join(names)
            plan = "TN" if "_890_" in x else "IL" if "Illinois" in x else "TX" if "Texas" in x else "other"
            if plan not in want:
                continue
        elif payer == "anthem" and not any(re.match(r"[A-Z]{2}_", x) for x in names):
            continue
        g = fam.setdefault(label(payer, names, None)[1], {"ids": [], "score": 0})
        g["ids"].append(nid)
        g["score"] += b or 0
    ranked = sorted(fam.items(), key=lambda kv: -kv[1]["score"])
    if payer != "bcbs":
        ranked = ranked[:n]
    _log("main network families: " + "; ".join(f"{k} ({len(v['ids'])})" for k, v in ranked[:40]))
    return [i for _, g in ranked for i in g["ids"]]


def pack(payer: str, source: str, release: str, work: str = "/tmp/pack", upload: bool = True,
         states: list[str] | None = None, match: list[str] | None = None, codes: str | None = None) -> dict:
    """source: "dataset" (the published release) or "wave-N" (a reduce wave in the work bucket).
    codes: "all", "common" (common_codes() + CSTM-ALL, streamed from the release), or "auto" (all for FULL_PACK
    payers, common for the rest)."""
    from huggingface_hub import hf_hub_download, snapshot_download

    from .config import load

    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    codes = codes or os.environ.get("RC_PACK_CODES") or "auto"  # serve.yml passes a target's 5th field here
    if codes == "auto":
        codes = "all" if payer in FULL_PACK else "main"
    subset = None
    main = None
    if codes in ("common", "main") and source == "dataset":
        subset = common_codes()
        if codes == "main":
            main = main_networks(payer, release, aetna_plans() if payer == "aetna" else None)
            _log(f"main networks: {len(main)}")
        pre = prefilter(payer, release, subset, f"{work}/src/release={release}", f"{work}/pre", main=main)
        _log(f"prefilter: {json.dumps(pre)}")
        src = f"{work}/src/release={release}"
    elif source == "dataset":
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
    networks = None
    if match:  # only networks whose file name or plan names contain one of these
        import duckdb

        sf = duckdb.sql(f"SELECT name, network_id FROM read_parquet('{src}/source_file.parquet')").fetchall()
        networks = sorted({nid for name, nid in sf
                           if any(m.lower() in (name + " " + " ".join((plans or {}).get(name, []))).lower() for m in match)})
        _log(f"match {match}: {len(networks)} networks")
    products = network_products(payer, src, plans)
    res = build_pack(payer, src, f"{work}/out", nppes, irs, networks=networks, plans=plans, work=f"{work}/duck",
                     states=states, products=products)
    res.update({"source": source, "release": release, "states": states})
    if subset:  # the app says when a code is outside the pack instead of "no published rate"
        res["code_subset"] = {"name": "common services (CareCompass procedures + flat all-services contracts)",
                              "codes": subset, "all_codes_networks": [x.hex() for x in (main or [])]}
    json.dump(res, open(f"{work}/out/pack.json", "w"), indent=1, default=str)
    shutil.rmtree(f"{work}/src", ignore_errors=True)
    shutil.rmtree(f"{work}/duck", ignore_errors=True)
    if upload:
        _upload(f"{ORG}/{payer}", f"{work}/out", "serving", f"Serving pack from {source} {release}")
    return res
