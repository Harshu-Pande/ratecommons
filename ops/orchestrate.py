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


def gh(path, tries=4):
    import time

    for i in range(tries):
        try:
            return json.loads(subprocess.check_output(["gh", "api", path]))
        except subprocess.CalledProcessError:
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


def wave_done(payer, release, wave):
    prefix = f"reduced/{release}/{payer}/wave-{wave}/"
    paths = {i.path for i in list_bucket_tree("ratecommons/work", prefix=prefix, recursive=True)}
    parts = all(f"{prefix}rate_fact/part-{k:02d}.parquet" in paths for k in range(16))
    dims = all(any(x.startswith(f"{prefix}{t}") for x in paths)  # a dims job can fail while the facts succeed
               for t in ("provider_group", "provider_set", "provider_list", "price_term", "price_list"))
    return parts and dims and f"{prefix}code.parquet" in paths and f"{prefix}metas.json" in paths


def merge_done(payer, release):
    files = HfApi().list_repo_files(f"ratecommons/{payer}", repo_type="dataset")
    return all(f"release={release}/rate_fact/part-{k:02d}.parquet" in files for k in range(16)) and \
        f"release={release}/source_file.parquet" in files


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
    fs = HfFileSystem()
    for shard, path in status.items():
        failed = json.loads(fs.read_text(f"buckets/{BUCKET}/{path}"))["failed"]
        if failed and shard in done:
            print(f"{payer} shard {shard}: {len(failed)} failed file(s), e.g. {failed[0]}; not mapped until retried")
            done.discard(shard)
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
    """Delete the map output of every finished wave (its facts and dims are in reduced/<release>/<payer>/wave-N)."""
    from huggingface_hub import batch_bucket_files

    from ticdata import hfio

    folders = {}
    for w in waves:
        if w[2] == "merge" or not wave_done(w[0], w[1], w[2]):
            continue
        key = (w[0], w[1])
        folders[key] = folders.get(key) or map_folders(*key)
        a, b = map(int, w[3].split("-"))
        paths = [p for s in range(a, b + 1) for p in folders[key].get(s, [])]
        if paths:
            print(f"deleting map output of {w[0]} wave {w[2]} (shards {w[3]}): {len(paths)} files")
            token = hfio.token_for(hfio.bucket(BUCKET))
            for i in range(0, len(paths), 500):
                batch_bucket_files(BUCKET, delete=paths[i:i + 500], token=token)
            for s in range(a, b + 1):
                folders[key].pop(s, None)


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
        mine = [w for w in waves if w[0] == payer and w[2] != "merge"]
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
                nxt = w  # partly or not mapped: (re)run its whole range; finished shards are just rewritten
                break
        if nxt and in_flight < MAX_WAVES_IN_FLIGHT:
            print(f"starting map of {payer} wave {nxt[2]} (shards {nxt[3]})")
            subprocess.check_call(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/workflows/map.yml/dispatches",
                                   "-f", "ref=main", "-f", f"inputs[payer]={payer}", "-f", f"inputs[shards]={shards}",
                                   "-f", "inputs[limit]=", "-f", f"inputs[range]={nxt[3]}"])
            return
        print(f"{payer}: {in_flight} mapped wave(s) wait for reduce; next map: {nxt and nxt[2]}")


def packs(waves):
    """After a merge of an AUTO_PACK payer: serving pack, then cloud pack (each started once per release)."""
    def started(wf, title):
        runs = gh(f"repos/{REPO}/actions/workflows/{wf}/runs?per_page=50")["workflow_runs"]
        return [r for r in runs if title in (r.get("display_title") or "")]

    for payer in AUTO_PACK:
        rel = next((w[1] for w in waves if w[0] == payer), None)
        if not rel or not merge_done(payer, rel):
            continue
        serve = started("serve.yml", f"serve {payer}:dataset")
        if not serve:
            print(f"starting serving pack of {payer}")
            subprocess.check_call(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/workflows/serve.yml/dispatches",
                                   "-f", "ref=main", "-f", f"inputs[request]={payer}:dataset"])
            continue
        if serve[0]["status"] != "completed" or serve[0]["conclusion"] != "success":
            continue
        cloud = started("cloud.yml", f"cloud {payer} prefix=serve/v2")
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

    mapped = None
    for w in waves:
        payer, release = w[0], w[1]
        if w[2] == "merge":
            if merge_done(payer, release):
                continue
            if all(wave_done(payer, release, x[2]) for x in waves if x[0] == payer and x[2] != "merge"):
                req = f"{payer} {release} all merge"
            else:
                print("merge waits for the waves")
                return
        else:
            if wave_done(payer, release, w[2]):
                continue
            a, b = map(int, w[3].split("-"))
            mapped = mapped if mapped is not None else mapped_shards(payer, release)
            missing = [s for s in range(a, b + 1) if s not in mapped]
            if missing:
                print(f"wave {w[2]} waits for shards {missing[:10]}{'...' if len(missing) > 10 else ''}")
                return
            req = f"{payer} {release} all wave={w[2]} {w[3]}"
        print("dispatching:", req)
        subprocess.check_call(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/workflows/reduce.yml/dispatches",
                               "-f", "ref=main", "-f", f"inputs[request]={req}"])
        return
    print("nothing to do")


if __name__ == "__main__":
    sys.exit(main())
