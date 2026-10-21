"""End-to-end check of a published release against one source file, parsed again from scratch.

Every fact in the file must be in the release with a network set that contains the file's
network, every fact the release assigns to that network must be in the file, and every
dimension ID the file produces must be published. Any nonzero count is a defect.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path


def verify_file(payer: str, release: str, repo: str, match: str, workdir: str = "/tmp/verify") -> dict:
    import duckdb
    from huggingface_hub import snapshot_download

    from .identity import _fetch
    from .net import new_session
    from .parse import parse_file
    from .pipeline import PAYERS

    t0 = time.time()
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    s = new_session()
    _, entries = PAYERS[payer](s)
    e = next(x for x in entries if x["kind"] == "in_network" and match in x["name"])
    res: dict = {"file": e["name"]}
    local = str(wd / "in.bin")
    res["download"] = _fetch(e["url"], local, s)
    out = str(wd / "parsed")
    core = os.environ.get("TIC_CORE")
    if core and os.path.exists(core):
        cp = subprocess.run([core, "map", local, out, str(max(1, (os.cpu_count() or 2) - 2))],
                            capture_output=True, text=True)
        res["parser"] = "rust" if cp.returncode == 0 else f"python (rust exit {cp.returncode})"
        if cp.returncode != 0:
            parse_file(local, out)
    else:
        res["parser"] = "python"
        parse_file(local, out)
    os.remove(local)
    pub = snapshot_download(repo, repo_type="dataset", local_dir=str(wd / "pub"),
                            allow_patterns=[f"release={release}/*"])
    base = f"{pub}/release={release}"
    con = duckdb.connect(str(wd / "v.db"))
    con.execute("SET preserve_insertion_order = false")
    nid = con.execute(f"SELECT network_id FROM '{base}/source_file.parquet' WHERE name = ?", [e["name"]]).fetchone()
    if nid is None:
        res["error"] = "file not in source_file"
        return res
    con.execute("CREATE TABLE me AS SELECT ?::BLOB AS network_id", [nid[0]])
    con.execute(f"""CREATE TABLE ns AS SELECT DISTINCT ns_id FROM '{base}/network_set/*.parquet'
                    WHERE list_contains(network_ids, (SELECT network_id FROM me))""")
    con.execute(f"CREATE TABLE lf AS SELECT DISTINCT fact_id FROM '{out}/rate_fact/*.parquet'")
    con.execute(f"CREATE VIEW pf AS SELECT fact_id, ns_id FROM '{base}/rate_fact/*.parquet'")
    checks = {
        "file_facts": "SELECT count(*) FROM lf",
        "missing_from_release": "SELECT count(*) FROM lf ANTI JOIN pf USING (fact_id)",
        "network_not_in_set": "SELECT count(*) FROM lf JOIN pf USING (fact_id) ANTI JOIN ns USING (ns_id)",
        "release_facts_for_network": "SELECT count(*) FROM pf SEMI JOIN ns USING (ns_id)",
        "in_release_not_in_file": "SELECT count(*) FROM pf SEMI JOIN ns USING (ns_id) ANTI JOIN lf USING (fact_id)",
    }
    for name, key, table in (("price_term", "pt_id", "price_term"), ("price_list", "pl_id", "price_list"),
                             ("provider_set", "ps_id", "provider_set"), ("provider_list", "pli_id", "provider_list"), ("code", "code_id", "code"),
                             ("provider_group", "pg_id", "provider_group")):
        src = f"'{base}/{table}.parquet'" if os.path.exists(f"{base}/{table}.parquet") else f"'{base}/{table}/*.parquet'"
        checks[f"{name}_missing"] = (f"SELECT count(*) FROM (SELECT DISTINCT {key} FROM '{out}/{table}.parquet') "
                                     f"ANTI JOIN (SELECT {key} FROM {src}) USING ({key})")
    res["checks"] = {k: con.execute(q).fetchone()[0] for k, q in checks.items()}
    bad = {k: v for k, v in res["checks"].items() if k not in ("file_facts", "release_facts_for_network") and v}
    res["ok"] = not bad and res["checks"]["file_facts"] == res["checks"]["release_facts_for_network"]
    res["seconds"] = round(time.time() - t0, 1)
    (wd / "verify.json").write_text(json.dumps(res, indent=2, default=str))
    return res
