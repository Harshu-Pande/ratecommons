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
    elif a.cmd == "fingerprint":
        from .net import resolve, tail_fingerprint

        r = resolve(a.url)
        crc, isize = tail_fingerprint(r.url, r.size)
        _write({"size": r.size, "crc32": hex(crc), "isize": isize, "etag": r.etag}, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
