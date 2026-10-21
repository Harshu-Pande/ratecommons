"""Command line entry point: `ticdata <command>`."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import config


def _write(data, out: str | None):
    text = json.dumps(data, indent=2, default=str)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text)
    print(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ticdata")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("archive", help="archive payer indexes (raw, as served)")
    p.add_argument("--payers", default="uhc,aetna,cigna")
    p.add_argument("--out", default="work/archive")
    p.add_argument("--upload", action="store_true")

    p = sub.add_parser("smoke-net", help="reach every payer host, probe ranges, measure download speed")
    p.add_argument("--mb", type=int, default=512)
    p.add_argument("--out")

    p = sub.add_parser("smoke-hf", help="create HF repos/bucket and round-trip one object")
    p.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    p.add_argument("--out")

    p = sub.add_parser("bench", help="download + rapidgzip decompression benchmark (experiment E2)")
    p.add_argument("--uhc-gb", type=float, default=20.0)
    p.add_argument("--out")

    p = sub.add_parser("put-report", help="upload JSON reports to the ops dataset")
    p.add_argument("files", nargs="+")
    p.add_argument("--prefix", required=True)

    p = sub.add_parser("bench-local", help="experiment E2b: whole-file download, then local rapidgzip")
    p.add_argument("--payers", default="cigna,uhc")
    p.add_argument("--out")

    p = sub.add_parser("nppes", help="NPPES monthly files -> Parquet (track C)")
    p.add_argument("--workdir", default="/tmp/nppes")
    p.add_argument("--upload", action="store_true", help="upload to the identity dataset")
    p.add_argument("--out")

    p = sub.add_parser("plan", help="assign a payer's in-network files to N shards")
    p.add_argument("--payer", required=True)
    p.add_argument("--shards", type=int, default=20)
    p.add_argument("--limit", type=int)
    p.add_argument("--out", required=True)

    p = sub.add_parser("parse-shard", help="download, parse and upload one shard of a plan")
    p.add_argument("plan")
    p.add_argument("--shard", type=int, required=True)
    p.add_argument("--upload", action="store_true", help="upload tables to the work bucket")
    p.add_argument("--out")

    p = sub.add_parser("parse-file", help="parse one local in-network file into a folder")
    p.add_argument("path")
    p.add_argument("outdir")

    p = sub.add_parser("identity", help="load a public identity CSV source (dac, irs_eo) -> Parquet")
    p.add_argument("source")
    p.add_argument("--upload", action="store_true")
    p.add_argument("--out")

    p = sub.add_parser("reduce", help="merge a payer-release's map outputs (one fact part, or dims)")
    p.add_argument("--payer", required=True)
    p.add_argument("--release", required=True)
    p.add_argument("--part", required=True,
                   help="0-15 for rate_fact parts, dims-<table> (provider_group, provider_set, price_term, "
                        "price_list, code, meta), or dims for all")
    p.add_argument("--publish", action="store_true", help="upload to datasets/<org>/<payer>")
    p.add_argument("--out")

    p = sub.add_parser("fetch", help="download one payer file (first name containing --match) to a path")
    p.add_argument("--payer", required=True)
    p.add_argument("--match", required=True)
    p.add_argument("--kind", default="in_network")
    p.add_argument("path")

    p = sub.add_parser("pair", help="map two files in one shard with the Rust core (dedup experiment)")
    p.add_argument("--payer", required=True)
    p.add_argument("--match", action="append", required=True)
    p.add_argument("--out")

    p = sub.add_parser("card", help="write the dataset card (README.md) of a payer dataset from what is published")
    p.add_argument("--payer", required=True)
    p.add_argument("--release", required=True)
    p.add_argument("--name", required=True, help="payer name as shown, e.g. Cigna")
    p.add_argument("--rows-in", type=int)

    p = sub.add_parser("fingerprint", help="tail fingerprint of one URL")
    p.add_argument("url")

    a = ap.parse_args(argv)
    cfg = config.load()

    if a.cmd == "archive":
        from . import archive

        out = Path(a.out)
        summary = archive.collect(out, a.payers.split(","))
        if a.upload:
            summary["upload"] = archive.upload(out, summary, cfg.manifests_repo)
        _write({k: v for k, v in summary.items() if k != "sha256"}, None)
    elif a.cmd == "smoke-net":
        from . import smoke

        _write(smoke.net(a.mb), a.out)
    elif a.cmd == "smoke-hf":
        from . import hfio

        res = {"ensure": hfio.ensure(cfg)}
        res["bucket_roundtrip"] = hfio.bucket_roundtrip(cfg, a.run_id)
        _write(res, a.out)
    elif a.cmd == "bench":
        from . import smoke

        _write(smoke.bench(a.uhc_gb), a.out)
    elif a.cmd == "put-report":
        from . import hfio

        for url in hfio.put_files(cfg, a.prefix, a.files, f"reports {a.prefix}"):
            print(url)
    elif a.cmd == "bench-local":
        from . import smoke

        _write(smoke.bench_local(tuple(a.payers.split(","))), a.out)
    elif a.cmd == "nppes":
        from . import identity

        _write(identity.nppes(a.workdir, cfg.identity_repo if a.upload else None), a.out)
    elif a.cmd == "plan":
        from . import pipeline

        _write(pipeline.plan(a.payer, a.shards, limit=a.limit), a.out)
    elif a.cmd == "parse-shard":
        from . import hfio, pipeline

        doc = json.loads(Path(a.plan).read_text())
        tok = (lambda: hfio.token_for(hfio.bucket(cfg.work_bucket))) if a.upload else None
        rtok = (lambda: hfio.token_for(hfio.bucket(cfg.restricted_bucket))) if a.upload else None
        _write(pipeline.run_shard(doc, a.shard, upload_bucket=cfg.work_bucket if a.upload else None,
                                  token=tok, restricted_bucket=cfg.restricted_bucket if a.upload else None,
                                  restricted_token=rtok), a.out)
    elif a.cmd == "parse-file":
        from .parse import parse_file

        _write(parse_file(a.path, a.outdir), None)
    elif a.cmd == "identity":
        from . import identity

        _write(identity.load_source(a.source, upload_repo=cfg.identity_repo if a.upload else None), a.out)
    elif a.cmd == "reduce":
        from . import hfio, identity, reduce

        tok = hfio.token_for(hfio.bucket(cfg.work_bucket))
        outdir = f"/tmp/reduce-out/{a.payer}/{a.release}"
        if a.part.startswith("dims"):
            table = a.part.split("-", 1)[1] if "-" in a.part else "all"
            res = reduce.reduce_dims(a.payer, a.release, cfg.work_bucket, outdir, token=tok, table=table)
        else:
            res = reduce.reduce_part(a.payer, a.release, int(a.part), cfg.work_bucket, outdir, token=tok)
        if a.publish:
            private = Path(reduce.restricted_dir(outdir)) / "code_text.parquet"
            if private.exists():  # private copy first, then the public tables
                from huggingface_hub import batch_bucket_files

                batch_bucket_files(cfg.restricted_bucket,
                                   add=[(str(private), f"release/{a.payer}/{a.release}/code_text.parquet")],
                                   token=hfio.token_for(hfio.bucket(cfg.restricted_bucket)))
                res["restricted"] = f"{cfg.restricted_bucket}/release/{a.payer}/{a.release}/code_text.parquet"
            repo = f"{cfg.org}/{a.payer}"
            res["published"] = identity.upload_folder(repo, outdir, f"release={a.release}",
                                                      f"{a.payer} {a.release}: reduce {a.part}")
        _write(res, a.out)
    elif a.cmd == "fetch":
        from .identity import _fetch
        from .net import new_session
        from .pipeline import PAYERS

        s = new_session()
        _, entries = PAYERS[a.payer](s)
        e = next(e for e in entries if e["kind"] == a.kind and a.match in e["name"])
        _write({"name": e["name"], **_fetch(e["url"], a.path, s)}, None)
    elif a.cmd == "pair":
        from .net import new_session
        from .pipeline import PAYERS, run_shard

        s = new_session()
        _, entries = PAYERS[a.payer](s)
        files = []
        for m in a.match:
            e = next(e for e in entries if e["kind"] == "in_network" and m in e["name"])
            files.append({"name": e["name"], "url": e["url"], "size": e.get("size")})
        res = run_shard({"payer": a.payer, "shards": [{"shard": 0, "files": files}]}, 0)
        for r in res["results"]:
            r.pop("traceback", None)
        _write(res, a.out)
    elif a.cmd == "card":
        from . import card, hfio

        repo = f"{cfg.org}/{a.payer}"
        text = card.publish(a.payer, a.release, repo, a.name, a.rows_in, token=hfio.token_for(hfio.dataset(repo)))
        _write({"repo": repo, "chars": len(text)}, None)
    elif a.cmd == "fingerprint":
        from .net import resolve, tail_fingerprint

        r = resolve(a.url)
        crc, isize = tail_fingerprint(r.url, r.size)
        _write({"size": r.size, "crc32": hex(crc), "isize": isize, "etag": r.etag}, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
