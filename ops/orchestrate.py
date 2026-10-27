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
    """Shard numbers whose map output is complete in the work bucket (metas.json is written last).
    (It used to read recent map runs' job names, which mixed payers and broke when a run page failed.)"""
    import re

    prefix = f"map/{release}/{payer}/"
    done = set()
    for i in list_bucket_tree("ratecommons/work", prefix=prefix, recursive=True):
        m = re.search(r"/shard-(\d+)-\d+/metas\.json$", i.path)
        if m:
            done.add(int(m.group(1)))
    return done


def main():
    import os

    me = os.environ.get("SELF_RUN_ID")  # when called at the end of a reduce run, ignore that run
    runs = [r for r in gh(f"repos/{REPO}/actions/workflows/reduce.yml/runs?per_page=5")["workflow_runs"]
            if str(r["id"]) != me]
    if any(r["status"] != "completed" for r in runs):
        print("a reduce run is in progress; waiting")
        return
    # called at the end of a successful reduce run (SELF_RUN_ID), an older failure is not a reason to stop
    if runs and runs[0]["conclusion"] != "success" and not me:
        print(f"last reduce run {runs[0]['id']} ended {runs[0]['conclusion']}; stopping until someone looks")
        return
    waves = [l.split() for l in open("ops/waves.txt") if l.strip() and not l.startswith("#")]
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
