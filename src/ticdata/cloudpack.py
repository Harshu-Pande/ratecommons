"""Cloud pack: the serving pack re-cut into many small files a serverless function can fetch per query.

Layout under <prefix>/<payer>/ (prefix default serve/v1, in the public work bucket):

  meta.json                         networks (int id, product, label, plans), counts
  ns.parquet                        ns int -> net int
  codes.parquet                     billing_code_type, billing_code, key, rows: the index of code files
  code/<TYPE>/<key>.parquet         one billing code: ps, ns, price fields inline (negotiated_type, rate,
                                    rate_raw, billing_class, setting, modifiers, pos, expiration), sorted by ps
  state/<ST>/pspli/<TYPE>/<key[:3]>.parquet
                                    provider set -> provider list, only lists with a group practicing in ST and
                                    only sets priced for a code whose key starts with those 3 characters (a query
                                    fetches its codes' buckets, not the whole state: Aetna TX was 127 MB whole,
                                    the largest bucket ~1.4M rows); state/<ST>/pspli/_cstm_all.parquet for the
                                    sets of flat all-services codes (meta.json "pspli": "bucket3")
  state/<ST>/plipg.parquet          provider list -> provider group, only groups practicing in ST
  state/<ST>/pg.parquet             group display: tin, tin_wide, name, n_npi, cities, specialty, business_names
  state/<ST>/pgnpi.parquet          group -> NPI located in ST
  state/<ST>/pgnet.parquet          group -> network int (has any published rate in it)
  tin.parquet                       tin -> states (to find a group without knowing its state)

Shared, under <prefix>/shared/: nppes/<ST>.parquet (NPPES lite), medicare.parquet (PFS by state).
IDs are dense integers local to one payer and one build; files are rebuilt together.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import time

from .serving import _duck, _log

W = "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)"


def code_key(code: str) -> str:
    """File-safe key for a billing code; same rule as the SQL in build() (the index maps code -> key)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", (code or "").strip())[:80] or "_"


def build(payer: str, pack: str, out: str, nppes: str, work: str = "/tmp/cloudwork") -> dict:
    """`pack` is a downloaded serving pack (<payer>/serving); `nppes` the shared NPPES lite parquet."""
    t0 = time.time()
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    con = _duck(work)
    res: dict = {"payer": payer}

    # dense ids
    con.execute(f"CREATE TABLE net AS SELECT (row_number() OVER (ORDER BY network_id) - 1)::INTEGER net, * "
                f"FROM read_parquet('{pack}/network.parquet')")
    con.execute(f"CREATE TABLE nsx AS SELECT DISTINCT ns_id FROM read_parquet('{pack}/ns.parquet')")
    con.execute("CREATE TABLE nsi AS SELECT ns_id, (row_number() OVER (ORDER BY ns_id) - 1)::INTEGER ns FROM nsx")
    con.execute(f"""COPY (SELECT i.ns, n.net FROM read_parquet('{pack}/ns.parquet') x JOIN nsi i USING (ns_id)
                          JOIN net n USING (network_id) ORDER BY 1, 2) TO '{out}/ns.parquet' {W}""")
    con.execute(f"CREATE TABLE psi AS SELECT ps_id, (row_number() OVER (ORDER BY ps_id) - 1)::INTEGER ps FROM "
                f"(SELECT DISTINCT ps_id FROM read_parquet('{pack}/ps_pli/*/*.parquet', hive_partitioning = true))")
    con.execute(f"CREATE TABLE plii AS SELECT pli_id, (row_number() OVER (ORDER BY pli_id) - 1)::INTEGER pli FROM "
                f"(SELECT DISTINCT pli_id FROM read_parquet('{pack}/pli_pg.parquet'))")
    con.execute(f"CREATE TABLE pgi AS SELECT pg_id, (row_number() OVER (ORDER BY pg_id) - 1)::INTEGER pg FROM "
                f"(SELECT DISTINCT pg_id FROM read_parquet('{pack}/provider_group.parquet'))")
    for t in ("net", "nsi", "psi", "plii", "pgi"):
        res[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    _log(json.dumps(res))

    # one file per code, price fields inline. Rate parts are code-hash parts sorted by code, so a code is
    # in one part: partitioned writes per part never collide.
    con.execute(f"CREATE TABLE pt AS SELECT * FROM read_parquet('{pack}/price_term.parquet')")
    os.makedirs(f"{out}/code", exist_ok=True)
    con.execute("SET partitioned_write_max_open_files = 64")
    con.execute("CREATE TABLE cps (t VARCHAR, b VARCHAR, ps INTEGER)")  # (code bucket, provider set) pairs
    idx = []
    for f in sorted(glob.glob(f"{pack}/rate/*.parquet")):
        tmp = f"{work}/codes-tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        con.execute(f"""COPY (
            SELECT regexp_replace(coalesce(r.billing_code_type, '_'), '[^A-Za-z0-9._-]', '_', 'g') AS t, left(coalesce(nullif(regexp_replace(trim(r.billing_code), '[^A-Za-z0-9._-]', '_', 'g'), ''), '_'), 80) AS k, r.billing_code AS code,
                   p.ps, i.ns, pt.negotiated_type, pt.rate_e4 / 1e4 AS rate, pt.rate_raw, pt.billing_class, pt.setting,
                   array_to_string(pt.billing_code_modifier, ',') AS modifiers,
                   array_to_string(pt.service_code, ',') AS pos, pt.expiration_date AS expiration
            FROM read_parquet('{f}') r JOIN psi p USING (ps_id) JOIN nsi i USING (ns_id) JOIN pt USING (pt_id)
            ORDER BY t, k, p.ps)
            TO '{tmp}' (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (t, k), ROW_GROUP_SIZE 100000)""")
        n = 0
        for d in glob.glob(f"{tmp}/t=*/k=*"):
            t = d.split("/t=")[1].split("/")[0]
            k = d.split("/k=")[1]
            files = sorted(glob.glob(f"{d}/*.parquet"))
            dest = f"{out}/code/{t}/{k}.parquet"
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if len(files) == 1:
                shutil.move(files[0], dest)
            else:
                con.execute(f"COPY (SELECT * FROM read_parquet({files!r})) TO '{dest}' {W}")
            n += 1
        con.execute(f"""INSERT INTO cps SELECT DISTINCT
                            regexp_replace(coalesce(r.billing_code_type, '_'), '[^A-Za-z0-9._-]', '_', 'g') AS t,
                            CASE WHEN r.billing_code_type = 'CSTM-ALL' THEN '_cstm_all' ELSE
                            left(left(coalesce(nullif(regexp_replace(trim(r.billing_code), '[^A-Za-z0-9._-]', '_', 'g'), ''), '_'), 80), 3) END AS b,
                            p.ps FROM read_parquet('{f}') r JOIN psi p USING (ps_id)""")
        idx.append(con.execute(f"""SELECT billing_code_type, billing_code, regexp_replace(coalesce(billing_code_type, '_'), '[^A-Za-z0-9._-]', '_', 'g') t,
                                         left(coalesce(nullif(regexp_replace(trim(billing_code), '[^A-Za-z0-9._-]', '_', 'g'), ''), '_'), 80) k, count(*) n
                                  FROM read_parquet('{f}') GROUP BY ALL""").fetchall())
        _log(f"codes {os.path.basename(f)}: {n} files")
        if os.environ.get("RC_DELETE_INPUTS"):
            os.remove(f)  # runner disk: the part is no longer needed
    shutil.rmtree(f"{work}/codes-tmp", ignore_errors=True)
    allsvc = glob.glob(f"{out}/code/CSTM-ALL/*.parquet")
    if allsvc:  # flat all-services arrangements, fetched with every provider lookup
        con.execute(f"COPY (SELECT * FROM read_parquet({allsvc!r}, union_by_name = true)) TO '{out}/cstm_all.parquet' {W}")
    con.execute("CREATE TABLE cidx (billing_code_type VARCHAR, billing_code VARCHAR, t VARCHAR, k VARCHAR, n BIGINT)")
    con.executemany("INSERT INTO cidx VALUES (?, ?, ?, ?, ?)", [r for part in idx for r in part])
    con.execute(f"""COPY (SELECT c.*, any_value(CASE WHEN x.text_withheld THEN NULL ELSE x.name END) AS name
                          FROM cidx c LEFT JOIN read_parquet('{pack}/code.parquet') x
                            ON x.billing_code_type = c.billing_code_type AND x.billing_code = c.billing_code
                          GROUP BY ALL ORDER BY billing_code) TO '{out}/codes.parquet' {W}""")
    res["codes"] = con.execute("SELECT count(*) FROM cidx").fetchone()[0]
    res["code_rows"] = con.execute("SELECT sum(n) FROM cidx").fetchone()[0]

    # per state
    con.execute(f"CREATE TABLE pgx AS SELECT g.pg, x.* FROM read_parquet('{pack}/provider_group.parquet') x JOIN pgi g USING (pg_id)")
    con.execute(f"CREATE TABLE plpg AS SELECT i.pli, g.pg FROM read_parquet('{pack}/pli_pg.parquet') x "
                "JOIN plii i USING (pli_id) JOIN pgi g USING (pg_id)")
    con.execute(f"CREATE TABLE pgnet AS SELECT g.pg, n.net FROM read_parquet('{pack}/pg_network.parquet') x "
                "JOIN pgi g USING (pg_id) JOIN net n USING (network_id)")
    con.execute(f"CREATE VIEW nppes AS SELECT * FROM read_parquet('{nppes}')")
    states = sorted(os.path.basename(d).split("=")[1] for d in glob.glob(f"{pack}/pg_npi/state=*"))
    for st in states:
        d = f"{out}/state/{st}"
        os.makedirs(d, exist_ok=True)
        con.execute(f"""CREATE OR REPLACE TABLE gn AS SELECT g.pg, x.npi FROM read_parquet('{pack}/pg_npi/state={st}/*.parquet') x
                        JOIN pgi g USING (pg_id)""")
        con.execute(f"COPY (SELECT DISTINCT pg, npi FROM gn ORDER BY pg) TO '{d}/pgnpi.parquet' {W}")
        con.execute(f"""COPY (SELECT l.pli, l.pg FROM plpg l SEMI JOIN (SELECT DISTINCT pg FROM gn) USING (pg)
                              ORDER BY 1, 2) TO '{d}/plipg.parquet' {W}""")
        ps_files = glob.glob(f"{pack}/ps_pli/state={st}/*.parquet")
        if ps_files:
            con.execute(f"""CREATE OR REPLACE TABLE sp AS SELECT DISTINCT p.ps, i.pli FROM read_parquet({ps_files!r}) x
                            JOIN psi p USING (ps_id) JOIN plii i USING (pli_id)""")
            tmp = f"{work}/pspli-tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            con.execute(f"""COPY (SELECT c.t, c.b, s.ps, s.pli FROM cps c JOIN sp s USING (ps) ORDER BY c.t, c.b, s.ps, s.pli)
                            TO '{tmp}' (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (t, b), ROW_GROUP_SIZE 100000)""")
            for bd in glob.glob(f"{tmp}/t=*/b=*"):
                t = bd.split("/t=")[1].split("/")[0]
                b = bd.split("/b=")[1]
                dest = f"{d}/pspli/_cstm_all.parquet" if b == "_cstm_all" else f"{d}/pspli/{t}/{b}.parquet"
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                fs = sorted(glob.glob(f"{bd}/*.parquet"))
                if len(fs) == 1:
                    shutil.move(fs[0], dest)
                else:
                    con.execute(f"COPY (SELECT * FROM read_parquet({fs!r})) TO '{dest}' {W}")
            shutil.rmtree(tmp, ignore_errors=True)
        con.execute(f"""COPY (SELECT DISTINCT n.pg, n.net FROM pgnet n SEMI JOIN (SELECT DISTINCT pg FROM gn) USING (pg)
                              ORDER BY 1, 2) TO '{d}/pgnet.parquet' {W}""")
        con.execute(f"""COPY (
            SELECT p.pg, p.tin_value AS tin, p.tin_type, p.tin_wide, p.business_names, coalesce(a.n_npi, 0) AS n_npi,
                   coalesce(a.org_name, CASE WHEN a.n_npi > 1 THEN a.any_name || ' +' || (a.n_npi - 1) || ' clinicians'
                                             ELSE a.any_name END, p.business_names[1]) AS name,
                   a.cities, a.specialty
            FROM pgx p JOIN (SELECT DISTINCT pg FROM gn) USING (pg)
            LEFT JOIN (SELECT gn.pg, count(DISTINCT gn.npi) n_npi,
                              max(CASE WHEN x.entity_type = '2' THEN x.name END) org_name, min(x.name) any_name,
                              list(DISTINCT x.city)[1:3] cities, mode(x.classification) specialty
                       FROM gn LEFT JOIN (SELECT * FROM nppes WHERE state = '{st}') x USING (npi)
                       WHERE gn.npi IS NOT NULL GROUP BY gn.pg) a USING (pg)
            ORDER BY p.pg) TO '{d}/pg.parquet' {W}""")
    res["states"] = len(states)
    con.execute(f"""COPY (SELECT x.tin_value AS tin, list(DISTINCT s ORDER BY s) AS states
                          FROM pgx x, unnest(coalesce(x.states, ['XX'])) AS u(s) GROUP BY 1 ORDER BY 1)
                    TO '{out}/tin.parquet' {W}""")
    nets = con.execute("SELECT net, hex(network_id), file_names, plan_names, bytes FROM net ORDER BY net").fetchall()
    pj = f"{pack}/pack.json"  # a common-services serving pack says which codes it holds
    subset = (json.load(open(pj)).get("code_subset") if os.path.exists(pj) else None)
    meta = {"payer": payer, "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pspli": "bucket3", **res,
            **({"code_subset": subset} if subset else {}),
            "networks": [{"net": a, "network_id": b, "file_names": c, "plan_names": d or [], "bytes": e}
                         for a, b, c, d, e in nets]}
    json.dump(meta, open(f"{out}/meta.json", "w"), default=str)
    con.close()
    res["files"] = sum(1 for _ in glob.iglob(f"{out}/**/*.parquet", recursive=True))
    res["bytes"] = sum(os.path.getsize(p) for p in glob.iglob(f"{out}/**/*.parquet", recursive=True))
    res["seconds"] = round(time.time() - t0, 1)
    _log(json.dumps(res))
    return res


def build_shared(identity_serving: str, out: str, work: str = "/tmp/cloudwork") -> dict:
    os.makedirs(f"{out}/nppes", exist_ok=True)
    con = _duck(work)
    nppes = f"{identity_serving}/nppes.parquet"
    con.execute(f"""COPY (SELECT state, npi, name, entity_type, credential, city, zip5, taxonomy_code, taxonomy,
                                 classification, specialization FROM read_parquet('{nppes}') ORDER BY state, npi)
                    TO '{out}/nppes' (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (state), ROW_GROUP_SIZE 100000)""")
    for d in glob.glob(f"{out}/nppes/state=*"):
        st = d.split("=")[1]
        fs = glob.glob(f"{d}/*.parquet")
        shutil.move(fs[0], f"{out}/nppes/{st}.parquet")
        shutil.rmtree(d)
    shutil.copy(f"{identity_serving}/medicare_pfs.parquet", f"{out}/medicare.parquet")
    con.execute(f"""COPY (SELECT left(npi::VARCHAR, 3) AS p, npi, state FROM read_parquet('{nppes}') ORDER BY p, npi)
                    TO '{out}/npi' (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (p))""")
    for d in glob.glob(f"{out}/npi/p=*"):
        shutil.move(glob.glob(f"{d}/*.parquet")[0], f"{out}/npi/{d.split('=')[1]}.parquet")
        shutil.rmtree(d)
    con.close()
    return {"states": len(glob.glob(f"{out}/nppes/*.parquet"))}


def upload(folder: str, prefix: str, bucket: str = "ratecommons/work", batch: int = 2000) -> int:
    from huggingface_hub import batch_bucket_files

    from .hfio import bucket as bk, token_for

    tok = token_for(bk(bucket))
    files = [p for p in glob.iglob(f"{folder}/**/*", recursive=True) if os.path.isfile(p)]
    for i in range(0, len(files), batch):
        adds = [(p, f"{prefix}/{os.path.relpath(p, folder)}") for p in files[i:i + batch]]
        for attempt in range(5):
            try:
                batch_bucket_files(bucket, add=adds, token=tok)
                break
            except Exception as e:
                _log(f"upload retry {attempt}: {e!r}")
                time.sleep(10 * (attempt + 1))
                tok = token_for(bk(bucket))
        _log(f"uploaded {min(i + batch, len(files))}/{len(files)}")
    return len(files)


def job(payer: str, prefix: str = "serve/v1", work: str = "/tmp/cloudjob", upload_to: str | None = "ratecommons/work") -> dict:
    """GitHub Actions entry point: build a payer's cloud pack from its published serving pack and upload it."""
    from huggingface_hub import hf_hub_download, snapshot_download

    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    snapshot_download(f"ratecommons/{payer}", repo_type="dataset", local_dir=f"{work}/src", allow_patterns=["serving/*"])
    nppes = hf_hub_download("ratecommons/identity", "serving/nppes.parquet", repo_type="dataset", local_dir=f"{work}/id")
    # the rate parts come first in the code loop; reading them after it is done is not needed
    if os.environ.get("RC_DELETE_INPUTS") is None:
        os.environ["RC_DELETE_INPUTS"] = "1"
    res = build(payer, f"{work}/src/serving", f"{work}/out", nppes, work=f"{work}/duck")
    shutil.rmtree(f"{work}/src", ignore_errors=True)
    if upload_to:
        meta = f"{work}/out/meta.json"
        os.rename(meta, f"{work}/meta.json")
        res["uploaded"] = upload(f"{work}/out", f"{prefix}/{payer}", upload_to)
        os.makedirs(f"{work}/last", exist_ok=True)
        os.rename(f"{work}/meta.json", f"{work}/last/meta.json")
        upload(f"{work}/last", f"{prefix}/{payer}", upload_to)  # meta last: readers see a complete pack
    return res


def shared_job(prefix: str = "serve/v1", work: str = "/tmp/cloudshared", upload_to: str | None = "ratecommons/work") -> dict:
    from huggingface_hub import snapshot_download

    shutil.rmtree(work, ignore_errors=True)
    snapshot_download("ratecommons/identity", repo_type="dataset", local_dir=f"{work}/id", allow_patterns=["serving/*"])
    res = build_shared(f"{work}/id/serving", f"{work}/out", work=f"{work}/duck")
    if upload_to:
        res["uploaded"] = upload(f"{work}/out", f"{prefix}/shared", upload_to)
    return res
