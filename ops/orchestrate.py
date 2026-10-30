"""Run the next reduce wave when its shards are mapped (GitHub Actions cron, see orchestrate.yml).

Waits while any reduce run is queued or running, and stops after a failed reduce run until a
person looks. Done-ness comes from the work bucket (every fact part and dims of the wave) and,
for the merge, from the payer dataset.
"""
import json
import subprocess
import sys

from huggingface_hub import HfApi, list_bucket_tree

REPO = "Harshu-Pande/ratecommons"
BUCKET = "ratecommons/work"
# payers whose map runs the orchestrator starts itself, one wave at a time (value: shards in the map plan).
# Map output is ~1 GB per GB of gzip and the bucket has a few TB free, so UHC (93.8 TB) must flow
# map -> reduce -> delete map output wave by wave.
PIPELINE = {"uhc": 1024}
MAX_WAVES_IN_FLIGHT = 2
# payers whose serving pack (serve.yml) and cloud pack (cloud.yml) are built automatically once merged
AUTO_PACK = ["bcbs", "anthem"]
# payers whose reduced/ wave outputs are deleted once their merge is published (storage decision 2026-10-30;
# not bcbs: more Blue companies are merged into it). A later merge of these needs the waves reduced again.
DROP_REDUCED = {"aetna", "anthem"}
_REDUCED = {}  # (payer, release) -> reduced_state(), listed once per run


def gh(path, tries=4):
    import time

    for i in range(tries):
        try:
            return json.loads(subprocess.check_output(["gh", "api", path]))
        except subprocess.CalledProcessError:
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


def is_wave(w):
    """A waves.txt line that reduces shards (`<payer> <release> <wave> a-b`), not a part or the merge."""
    return w[2].isdigit()


def reduced_state(payer, release):
    """(paths under reduced/<release>/<payer>/, {wave: part} for waves held by a complete part,
    {wave: files} for waves deleted after the merge (dropped.json)), listed once per orchestrator run."""
    key = (payer, release)
    if key not in _REDUCED:
        from huggingface_hub import HfFileSystem

        from ticdata.reduce import unit_complete

        pre = f"reduced/{release}/{payer}/"
        paths = {i.path for i in list_bucket_tree(BUCKET, prefix=pre, recursive=True)}
        fs, covered, dropped = HfFileSystem(), {}, {}
        for u in sorted({p[len(pre):].split("/", 1)[0] for p in paths if "/" in p[len(pre):]}):
            if u.startswith("part-") and unit_complete(paths, f"{pre}{u}/"):
                covered.update({int(n): u for n in json.loads(fs.read_text(f"buckets/{BUCKET}/{pre}{u}/waves.json"))})
        if f"{pre}dropped.json" in paths:
            dropped = {int(k): v for k, v in json.loads(fs.read_text(f"buckets/{BUCKET}/{pre}dropped.json"))["waves"].items()}
        _REDUCED[key] = (paths, covered, dropped)
    return _REDUCED[key]


def wave_done(payer, release, wave):
    """The wave's reduced output is complete, or it is held by a complete part, or it was dropped after the merge."""
    from ticdata.reduce import unit_complete

    paths, covered, dropped = reduced_state(payer, release)
    return int(wave) in covered or int(wave) in dropped or \
        unit_complete(paths, f"reduced/{release}/{payer}/wave-{wave}/")


def part_done(payer, release, part):
    from ticdata.reduce import unit_complete

    return unit_complete(reduced_state(payer, release)[0], f"reduced/{release}/{payer}/part-{part}/")


def merge_done(payer, release, waves=None):
    """Every merged table is in the payer dataset (a failed merge job can leave the others published:
    BCBS's provider_set ran out of memory while rate_fact and source_file landed, 2026-10-28), and, given the waves,
    the release holds as many files as its waves (a wave added after the merge, e.g. more Blue companies, re-merges)."""
    files = HfApi().list_repo_files(f"ratecommons/{payer}", repo_type="dataset")
    r = f"release={release}/"
    tables = all(f"{r}rate_fact/part-{k:02d}.parquet" in files for k in range(16)) and \
        all(f"{r}{t}.parquet" in files for t in ("source_file", "network", "code", "provider_group")) and \
        all(any(f.startswith(f"{r}{t}/") for f in files) for t in ("provider_set", "provider_list", "price_list", "price_term"))
    if not tables or waves is None:
        return tables
    return merged_files(payer, release) >= expected_files(payer, release, waves)


def expected_files(payer, release, waves):
    """Files the payer's waves hold: from each wave's metas.json, or its part's (counted once), or dropped.json."""
    _, covered, dropped = reduced_state(payer, release)
    n, parts = 0, set()
    for w in waves:
        if w[0] != payer or w[1] != release or not is_wave(w):
            continue
        k = int(w[2])
        if k in dropped:
            n += dropped[k]
        elif k in covered:
            if covered[k] not in parts:
                parts.add(covered[k])
                n += wave_files(payer, release, covered[k])
        else:
            n += wave_files(payer, release, w[2])
    return n


def merged_files(payer, release):
    """Files in a merged release (rows of source_file.parquet)."""
    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem

    with HfFileSystem().open(f"datasets/ratecommons/{payer}/release={release}/source_file.parquet") as f:
        return pq.ParquetFile(f).metadata.num_rows


def wave_files(payer, release, wave):
    """Files reduced into a wave or a part ("part-P") (its metas.json lists one meta per file)."""
    from huggingface_hub import HfFileSystem

    unit = wave if str(wave).startswith("part-") else f"wave-{wave}"
    return len(json.loads(HfFileSystem().read_text(f"buckets/{BUCKET}/reduced/{release}/{payer}/{unit}/metas.json")))


def mapped_shards(payer, release):
    """Shard numbers whose map output is complete in the work bucket (metas.json is written last) and whose
    last run left no failed file (shard-NNN-status.json; shards mapped before it existed have none).
    (It used to read recent map runs' job names, which mixed payers and broke when a run page failed.)"""
    import re

    from huggingface_hub import HfFileSystem

    prefix = f"map/{release}/{payer}/"
    done, status = set(), {}
    for i in list_bucket_tree("ratecommons/work", prefix=prefix, recursive=True):
        m = re.search(r"/shard-(\d+)-\d+/metas\.json$", i.path)
        if m:
            done.add(int(m.group(1)))
        m = re.search(r"/shard-(\d+)-status\.json$", i.path)
        if m:
            status[int(m.group(1))] = i.path
    from ticdata.pipeline import STATUS_REQUIRED, unavailable

    fs, gone = HfFileSystem(), unavailable(payer)
    for shard, path in status.items():
        failed = [n for n in json.loads(fs.read_text(f"buckets/{BUCKET}/{path}"))["failed"] if n not in gone]
        if failed and shard in done:
            print(f"{payer} shard {shard}: {len(failed)} failed file(s), e.g. {failed[0]}; not mapped until retried")
            done.discard(shard)
    if payer in STATUS_REQUIRED:  # a running shard has metas.json for each chunk uploaded so far
        done &= set(status)
    return done


def map_folders(payer, release):
    """{shard: [file paths]} of map output in the work bucket."""
    import re

    out = {}
    for i in list_bucket_tree(BUCKET, prefix=f"map/{release}/{payer}/", recursive=True):
        m = re.search(r"/shard-(\d+)-\d+/", i.path)
        if m and getattr(i, "size", None) is not None:
            out.setdefault(int(m.group(1)), []).append(i.path)
    return out


def clean(waves):
    """Delete what a later step no longer needs: the map output of every finished wave (its facts and dims are in
    reduced/<release>/<payer>/wave-N), the reduced waves a complete part holds, and, for DROP_REDUCED payers
    whose merge is published, their reduced waves (dropped.json keeps each wave's file count)."""
    import os
    import tempfile

    from huggingface_hub import HfFileSystem, batch_bucket_files

    from ticdata import hfio

    def delete(paths, what):
        print(f"deleting {what}: {len(paths)} files")
        token = hfio.token_for(hfio.bucket(BUCKET))
        for i in range(0, len(paths), 500):
            batch_bucket_files(BUCKET, delete=paths[i:i + 500], token=token)

    folders = {}
    for w in waves:
        if not is_wave(w) or not wave_done(w[0], w[1], w[2]):
            continue
        key = (w[0], w[1])
        folders[key] = folders.get(key) or map_folders(*key)
        a, b = map(int, w[3].split("-"))
        paths = [p for s in range(a, b + 1) for p in folders[key].get(s, [])]
        if paths:
            delete(paths, f"map output of {w[0]} wave {w[2]} (shards {w[3]})")
            for s in range(a, b + 1):
                folders[key].pop(s, None)

    for payer, release in sorted({(w[0], w[1]) for w in waves}):
        pre = f"reduced/{release}/{payer}/"
        paths, covered, dropped = reduced_state(payer, release)
        held = sorted(p for p in paths if any(p.startswith(f"{pre}wave-{n}/") for n in covered))
        if held:  # the part is complete (reduced_state checks), so its waves are only a second copy
            delete(held, f"{payer} reduced waves {sorted(covered)} (held by {sorted(set(covered.values()))})")
            _REDUCED.pop((payer, release), None)
        if payer in DROP_REDUCED and not dropped and merge_done(payer, release, waves):
            files = {int(w[2]): wave_files(payer, release, w[2]) for w in waves
                     if w[0] == payer and w[1] == release and is_wave(w) and int(w[2]) not in covered}
            files.update({n: 0 for n in covered})  # (a part's files are counted through the part, gone too)
            parts = sorted(set(covered.values()))
            doc = {"waves": files, "parts": {p: wave_files(payer, release, p) for p in parts},
                   "reason": "storage decision 2026-10-30: reduced waves of a published merge"}
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, "dropped.json")
                with open(f, "w") as fh:
                    json.dump(doc, fh)
                batch_bucket_files(BUCKET, add=[(f, f"{pre}dropped.json")], token=hfio.token_for(hfio.bucket(BUCKET)))
            if json.loads(HfFileSystem().read_text(f"buckets/{BUCKET}/{pre}dropped.json")) != json.loads(json.dumps(doc)):
                raise RuntimeError(f"{pre}dropped.json did not read back; nothing deleted")
            gone = sorted(p for p in paths if p != f"{pre}dropped.json")
            if gone:
                delete(gone, f"{payer} reduced waves after its published merge")
            _REDUCED.pop((payer, release), None)


def start_maps(waves):
    """For PIPELINE payers: start the next wave's map run when no map run is going and few waves wait."""
    import os

    me = os.environ.get("SELF_RUN_ID")
    runs = [r for r in gh(f"repos/{REPO}/actions/workflows/map.yml/runs?per_page=20")["workflow_runs"]
            if str(r["id"]) != me and r["status"] != "completed"]
    for payer, shards in PIPELINE.items():
        # this payer's wave runs are dispatched and named "map <payer> <range>"; other payers' runs don't block it
        busy = [r for r in runs if (r.get("display_title") or "").startswith(f"map {payer} ")
                or (r.get("event") == "push" and f"{payer} " in (r.get("display_title") or "").lower())]
        if busy:
            print(f"{payer}: a map run is in progress ({busy[0]['id']})")
            continue
        mine = [w for w in waves if w[0] == payer and is_wave(w)]
        if not mine:
            continue
        mapped = mapped_shards(payer, mine[0][1])
        in_flight, nxt = 0, None
        for w in mine:
            a, b = map(int, w[3].split("-"))
            if wave_done(payer, w[1], w[2]):
                continue
            got = sum(1 for s in range(a, b + 1) if s in mapped)
            if got == b - a + 1:
                in_flight += 1
            elif nxt is None:
                # partly or not mapped: run only its missing shards (one failed download re-ran all 12, 2.5 hours)
                nxt = w + [",".join(str(x) for x in range(a, b + 1) if x not in mapped)]
                break
        if nxt and in_flight < MAX_WAVES_IN_FLIGHT:
            print(f"starting map of {payer} wave {nxt[2]} (shards {nxt[4]})")
            subprocess.check_call(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/workflows/map.yml/dispatches",
                                   "-f", "ref=main", "-f", f"inputs[payer]={payer}", "-f", f"inputs[shards]={shards}",
                                   "-f", "inputs[limit]=", "-f", f"inputs[range]={nxt[4]}"])
            return
        print(f"{payer}: {in_flight} mapped wave(s) wait for reduce; next map: {nxt and nxt[2]}")


def packs(waves):
    """After a merge of an AUTO_PACK payer: serving pack, then cloud pack, then CareCompass (once per merge run)."""
    import os

    def started(wf, title, after=""):
        runs = gh(f"repos/{REPO}/actions/workflows/{wf}/runs?per_page=50")["workflow_runs"]
        return [r for r in runs if title in (r.get("display_title") or "") and r["created_at"] > after]

    for payer in AUTO_PACK:
        rel = next((w[1] for w in waves if w[0] == payer), None)
        if not rel or not merge_done(payer, rel):
            continue
        # packs follow the newest successful merge run, so a re-merge (more files) is packed again
        # (called from the merge run's last job, which runs only when every part succeeded, it counts as done)
        merges = started("reduce.yml", f"reduce {payer} {rel} all merge")
        ok = merges and (str(merges[0]["id"]) == os.environ.get("SELF_RUN_ID")
                         or (merges[0]["status"] == "completed" and merges[0]["conclusion"] == "success"))
        if not ok:
            continue
        serve = started("serve.yml", f"serve {payer}:dataset", after=merges[0]["created_at"])
        if not serve:
            print(f"starting serving pack of {payer}")
            subprocess.check_call(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/workflows/serve.yml/dispatches",
                                   "-f", "ref=main", "-f", f"inputs[request]={payer}:dataset"])
            continue
        if serve[0]["status"] != "completed" or serve[0]["conclusion"] != "success":
            continue
        cloud = started("cloud.yml", f"cloud {payer} prefix=serve/v2", after=serve[0]["updated_at"])
        if not cloud:
            print(f"starting cloud pack of {payer}")
            subprocess.check_call(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/workflows/cloud.yml/dispatches",
                                   "-f", "ref=main", "-f", f"inputs[request]={payer} prefix=serve/v2"])
            continue
        if cloud[0]["status"] != "completed" or cloud[0]["conclusion"] != "success":
            continue
        # CareCompass picks up a payer when its cloud pack exists: rebuild every state once after the pack
        shop = gh(f"repos/{REPO}/actions/workflows/shop.yml/runs?per_page=20")["workflow_runs"]
        if not any(r["created_at"] > cloud[0]["updated_at"] for r in shop):
            print(f"rebuilding CareCompass data with {payer}")
            subprocess.check_call(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/workflows/shop.yml/dispatches",
                                   "-f", "ref=main", "-f", "inputs[request]=all"])
            return


def main():
    import os

    me = os.environ.get("SELF_RUN_ID")  # when called at the end of a reduce run, ignore that run
    waves = [l.split() for l in open("ops/waves.txt") if l.strip() and not l.startswith("#")]
    _REDUCED.clear()
    for step in (clean, start_maps, packs):  # independent of the reduce chain below; a failure here must not stop it
        try:
            step(waves)
        except Exception as e:
            print(f"{step.__name__} failed: {e!r}")
    runs = [r for r in gh(f"repos/{REPO}/actions/workflows/reduce.yml/runs?per_page=5")["workflow_runs"]
            if str(r["id"]) != me]
    if any(r["status"] != "completed" for r in runs):
        print("a reduce run is in progress; waiting")
        return
    # called at the end of a successful reduce run (SELF_RUN_ID), an older failure is not a reason to stop
    from_reduce = me and os.environ.get("SELF_KIND", "reduce") == "reduce"
    if runs and runs[0]["conclusion"] != "success" and not from_reduce:
        print(f"last reduce run {runs[0]['id']} ended {runs[0]['conclusion']}; stopping until someone looks")
        return

    # a payer waiting for shards (or for its waves, at the merge) holds only its own later lines: BCBS waves added
    # after the merge must not stall UHC, nor wait behind 86 UHC waves
    mapped, blocked = {}, set()
    for w in waves:
        payer, release = w[0], w[1]
        if payer in blocked:
            continue
        if w[2] == "merge":
            if merge_done(payer, release, waves):
                continue
            if all(wave_done(payer, release, x[2]) for x in waves if x[0] == payer and is_wave(x)):
                req = f"{payer} {release} all merge"
            else:
                print(f"{payer} merge waits for its waves")
                blocked.add(payer)
                continue
        elif w[2].startswith("part="):  # merge waves a-b into reduced/<release>/<payer>/part-P, then clean() drops them
            part = w[2][5:]
            if part_done(payer, release, part):
                continue
            a, b = map(int, w[3].split("-"))
            if not all(wave_done(payer, release, str(x)) for x in range(a, b + 1)):
                print(f"{payer} part {part} waits for waves {w[3]}")
                blocked.add(payer)
                continue
            req = f"{payer} {release} all part={part} {w[3]}"
        else:
            if wave_done(payer, release, w[2]):
                continue
            a, b = map(int, w[3].split("-"))
            if (payer, release) not in mapped:
                mapped[(payer, release)] = mapped_shards(payer, release)
            missing = [s for s in range(a, b + 1) if s not in mapped[(payer, release)]]
            if missing:
                print(f"{payer} wave {w[2]} waits for shards {missing[:10]}{'...' if len(missing) > 10 else ''}")
                blocked.add(payer)
                continue
            req = f"{payer} {release} all wave={w[2]} {w[3]}"
        print("dispatching:", req)
        subprocess.check_call(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/workflows/reduce.yml/dispatches",
                               "-f", "ref=main", "-f", f"inputs[request]={req}"])
        return
    print("nothing to do")


if __name__ == "__main__":
    sys.exit(main())
