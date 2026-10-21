"""Hugging Face helpers. Every write needs HF_TOKEN (a fine-grained token with
write access to the project org), which lives only in CI secrets."""
from __future__ import annotations

import io
import json
import os
import time

from .config import Config


def _api():
    from huggingface_hub import HfApi

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN is not set")
    return HfApi(token=token)


def _retry(fn, tries: int = 5):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # concurrent commits from parallel jobs can collide
            if i == tries - 1:
                raise
            time.sleep(2 + 3 * i)
            last = e  # noqa: F841


def ensure(cfg: Config) -> dict:
    """Create the public dataset repos and the work bucket if missing."""
    from huggingface_hub import create_bucket

    api = _api()
    out = {"whoami": api.whoami().get("name")}
    for rid in (cfg.manifests_repo, cfg.ops_repo):
        url = _retry(lambda: api.create_repo(rid, repo_type="dataset", private=False, exist_ok=True))
        out[rid] = str(url)
    b = _retry(lambda: create_bucket(cfg.work_bucket, private=False, exist_ok=True,
                                     token=os.environ["HF_TOKEN"]))
    out[cfg.work_bucket] = str(getattr(b, "bucket_id", b))
    return out


def put_json(cfg: Config, path_in_repo: str, data, message: str) -> str:
    api = _api()
    payload = json.dumps(data, indent=2, default=str).encode()
    _retry(lambda: api.create_repo(cfg.ops_repo, repo_type="dataset", private=False, exist_ok=True))
    _retry(lambda: api.upload_file(path_or_fileobj=io.BytesIO(payload), path_in_repo=path_in_repo,
                                   repo_id=cfg.ops_repo, repo_type="dataset", commit_message=message))
    return f"https://huggingface.co/datasets/{cfg.ops_repo}/blob/main/{path_in_repo}"


def put_files(cfg: Config, prefix: str, paths: list[str], message: str) -> list[str]:
    """Upload report files (JSON, logs, anything small) to the ops repo in one commit."""
    from pathlib import Path

    from huggingface_hub import CommitOperationAdd

    api = _api()
    files = [Path(p) for p in paths if Path(p).is_file()]
    if not files:
        return []
    ops = [CommitOperationAdd(path_in_repo=f"{prefix}/{f.name}", path_or_fileobj=str(f)) for f in files]
    _retry(lambda: api.create_repo(cfg.ops_repo, repo_type="dataset", private=False, exist_ok=True))
    _retry(lambda: api.create_commit(cfg.ops_repo, operations=ops, commit_message=message, repo_type="dataset"))
    return [f"https://huggingface.co/datasets/{cfg.ops_repo}/blob/main/{prefix}/{f.name}" for f in files]


def bucket_roundtrip(cfg: Config, run_id: str) -> dict:
    """Write, list, read back and delete one small object in the work bucket."""
    from huggingface_hub import batch_bucket_files, download_bucket_files, list_bucket_tree

    token = os.environ["HF_TOKEN"]
    key = f"_smoke/{run_id}.txt"
    body = f"smoke {run_id} {time.time()}".encode()
    t0 = time.time()
    batch_bucket_files(cfg.work_bucket, add=[(body, key)], token=token)
    t_put = time.time() - t0
    listed = [i.path for i in list_bucket_tree(cfg.work_bucket, prefix="_smoke", token=token)]
    local = f"/tmp/{run_id}.txt"
    download_bucket_files(cfg.work_bucket, files=[(key, local)], token=token)
    ok = open(local, "rb").read() == body
    batch_bucket_files(cfg.work_bucket, delete=[key], token=token)
    return {"put_seconds": round(t_put, 2), "listed": key in listed, "read_back_ok": ok}
