"""Smoke tests and first benchmarks (experiment E2 in the design doc).

Run on every new worker platform: they prove the payer hosts are reachable from
it, that guarded range reads behave, and how fast it downloads and decompresses.
"""
from __future__ import annotations

import os
import platform
import re
import time
import zlib

from . import discover
from .net import HttpFile, Stats, download, fetch_range, new_session, resolve, tail_fingerprint


def egress() -> dict:
    """Where this worker's traffic exits (country and Cloudflare POP). Payer CDNs geo-block."""
    try:
        import requests

        t = requests.get("https://www.cloudflare.com/cdn-cgi/trace", timeout=10).text
        kv = dict(line.split("=", 1) for line in t.splitlines() if "=" in line)
        return {"loc": kv.get("loc"), "colo": kv.get("colo")}
    except Exception as ex:  # informational only
        return {"error": repr(ex)[:200]}


def machine() -> dict:
    info = {"python": platform.python_version(), "cpus": os.cpu_count(), "platform": platform.platform()}
    try:
        mem = open("/proc/meminfo").read()
        info["mem_gb"] = round(int(re.search(r"MemTotal:\s+(\d+)", mem).group(1)) / 1e6, 1)
        cpu = open("/proc/cpuinfo").read()
        m = re.search(r"model name\s*:\s*(.+)", cpu)
        info["cpu_model"] = m.group(1).strip() if m else None
    except OSError:
        pass
    disks = {}
    for d in ("/", "/tmp", "/kaggle/working", os.environ.get("RUNNER_TEMP", "")):
        try:
            if d and os.path.isdir(d):
                st = os.statvfs(d)
                disks[d] = round(st.f_bavail * st.f_frsize / 1e9, 1)
        except OSError:
            pass
    info["disk_free_gb"] = disks
    info["egress"] = egress()
    for k in ("GITHUB_ACTIONS", "KAGGLE_KERNEL_RUN_TYPE", "LIGHTNING_CLOUDSPACE_HOST", "MODAL_TASK_ID"):
        if os.environ.get(k):
            info["runner"] = k
    return info


def _pick(entries: list[dict], payer: str) -> dict:
    inn = [e for e in entries if e["kind"] == "in_network"]
    if payer == "uhc":
        p3 = [e for e in inn if e["name"].endswith("_P3_in-network-rates.json.gz")]
        return (p3 or sorted(inn, key=lambda e: -(e["size"] or 0)))[0]
    if payer == "cigna":
        oap = [e for e in inn if "national-oap_in-network" in e["name"]]
        return (oap or inn)[0]
    return inn[0]


def _throughput(url: str, nbytes: int) -> dict:
    f = HttpFile(url, window=16 << 20, prefetch=4)
    t0 = time.time()
    got = 0
    while got < nbytes:
        chunk = f.read(min(8 << 20, nbytes - got))
        if not chunk:
            break
        got += len(chunk)
    dt = time.time() - t0
    f.close()
    return {"bytes": got, "seconds": round(dt, 1), "mb_per_s": round(got / dt / 1e6, 1),
            "http": f.stats.as_dict()}


def net(throughput_mb: int = 512) -> dict:
    s = new_session()
    report = {"machine": machine(), "payers": {}}
    for payer, fn in discover.PAYERS.items():
        r: dict = {}
        try:
            t0 = time.time()
            raw, entries = fn(s)
            r["discovery_seconds"] = round(time.time() - t0, 1)
            r["raw_files"] = {k: len(v) for k, v in raw.items()}
            kinds: dict = {}
            for e in entries:
                kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
            r["entries"] = kinds
            e = _pick(entries, payer)
            r["sample"] = e["name"]
            rem = resolve(e["url"], s)
            r["size"] = rem.size
            r["host"] = rem.url.split("/")[2]
            st = Stats()
            crc, isize = tail_fingerprint(rem.url, rem.size, s, stats=st)
            r["tail"] = {"crc32": hex(crc), "isize": isize, "http": st.as_dict()}
            r["throughput"] = _throughput(e["url"], throughput_mb << 20)
        except Exception as ex:  # report, never crash the whole smoke run
            r["error"] = repr(ex)[:800]
        report["payers"][payer] = r
    return report


def bench(uhc_gb: float = 20.0, payers: tuple[str, ...] = ("cigna", "uhc")) -> dict:
    """Download + decompress speed: one whole Cigna file, then the first part of a UHC file.

    Each payer is measured independently, so a blocked host does not hide the others.
    """
    import rapidgzip

    s = new_session()
    out = {"machine": machine(), "rapidgzip": rapidgzip.__version__ if hasattr(rapidgzip, "__version__") else "?"}
    threads = os.cpu_count() or 2

    def run(url: str, cap: int | None) -> dict:
        f = HttpFile(url, window=32 << 20, prefetch=max(4, threads))
        t0 = time.time()
        total = 0
        with rapidgzip.open(f, parallelization=threads) as g:
            while True:
                buf = g.read(64 << 20)
                if not buf:
                    break
                total += len(buf)
                if cap and total >= cap:
                    break
        dt = time.time() - t0
        compressed = f.stats.bytes
        f.close()
        return {"compressed_read_mb": round(compressed / 1e6), "json_gb": round(total / 1e9, 2),
                "seconds": round(dt, 1), "json_gb_per_s": round(total / dt / 1e9, 2),
                "ratio": round(total / max(compressed, 1), 1), "http": f.stats.as_dict()}

    if "cigna" in payers:
        try:
            _, cig = discover.cigna(s)
            c = _pick(cig, "cigna")
            out["cigna_whole_file"] = {"file": c["name"], **run(c["url"], None)}
            # single-thread zlib baseline on the first 256 MB of the same file
            rem = resolve(c["url"], s)
            data = b"".join(fetch_range(rem.url, i, min(i + (16 << 20), 256 << 20) - 1, s)
                            for i in range(0, 256 << 20, 16 << 20))
            t0 = time.time()
            n = len(zlib.decompressobj(31).decompress(data))
            dt = time.time() - t0
            out["zlib_single_thread"] = {"json_gb_per_s": round(n / dt / 1e9, 2), "ratio": round(n / len(data), 1)}
        except Exception as ex:
            out["cigna_error"] = repr(ex)[:800]

    if "uhc" in payers:
        try:
            _, uhc = discover.uhc(s)
            u = _pick(uhc, "uhc")
            out["uhc_partial"] = {"file": u["name"], **run(u["url"], int(uhc_gb * 1e9))}
        except Exception as ex:
            out["uhc_error"] = repr(ex)[:800]
    return out


def bench_local(payers: tuple[str, ...] = ("cigna", "uhc"), workdir: str = "/tmp/ticbench") -> dict:
    """Experiment E2b: download the whole file to local disk first, then rapidgzip the local file.

    Compares with `bench()`, which streams through the Python HTTP file object.
    """
    import shutil

    import rapidgzip

    os.makedirs(workdir, exist_ok=True)
    s = new_session()
    threads = os.cpu_count() or 2
    out: dict = {"machine": machine()}
    disc = {"cigna": discover.cigna, "uhc": discover.uhc, "aetna": discover.aetna}
    for p in payers:
        try:
            _, entries = disc[p](s)
            e = _pick(entries, p)
            rem = resolve(e["url"], s)
            free = shutil.disk_usage(workdir).free
            if rem.size > free * 0.9:
                out[p] = {"file": e["name"], "skipped": f"{rem.size/1e9:.1f} GB > free disk {free/1e9:.1f} GB"}
                continue
            path = os.path.join(workdir, "f.gz")
            dl = download(rem.url, path, rem.size, threads=8, s=s)
            res = {"file": e["name"], "download": dl}
            for par in sorted({1, threads}):
                t0 = time.time()
                n = 0
                with rapidgzip.open(path, parallelization=par) as g:
                    while True:
                        b = g.read(64 << 20)
                        if not b:
                            break
                        n += len(b)
                dt = time.time() - t0
                res[f"rapidgzip_p{par}"] = {"json_gb": round(n / 1e9, 2), "seconds": round(dt, 1),
                                           "json_gb_per_s": round(n / dt / 1e9, 2)}
            os.remove(path)
            out[p] = res
        except Exception as ex:
            out[p] = {"error": repr(ex)[:800]}
    return out
