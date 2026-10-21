"""Hugging Face helpers.

Credentials, in order:
1. HF_TOKEN, a fine-grained token with write access to the project org (local use and setup).
2. In GitHub Actions without HF_TOKEN: Hugging Face Trusted Publishers. The job's GitHub
   OIDC id token is exchanged for a short-lived Hub token scoped to one repo or bucket, so
   no long-lived token is stored in GitHub. Each resource must list this GitHub repo as a
   trusted publisher in its Hugging Face settings, and the job needs
   `permissions: id-token: write`.
"""
from __future__ import annotations

import io
import json
import os
import time

from .config import Config


_TOKENS: dict[str, tuple[str, float]] = {}


def oidc_available() -> bool:
    return bool(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")) and not os.environ.get("HF_TOKEN")


def token_for(resource: str) -> str:
    """A write token for one resource: "datasets/<org>/<name>" or "buckets/<org>/<name>"."""
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    if not oidc_available():
        raise RuntimeError("No Hugging Face credentials: set HF_TOKEN, or run in GitHub Actions "
                           "with `permissions: id-token: write` and a trusted publisher configured")
    cached = _TOKENS.get(resource)
    if cached and time.time() < cached[1]:
        return cached[0]
    from huggingface_hub._oidc import oidc_login

    r = _retry(lambda: oidc_login(resource=resource))
    _TOKENS[resource] = (r["access_token"], time.time() + int(r.get("expires_in", 3600)) - 300)
    return r["access_token"]


def dataset(repo_id: str) -> str:
    return f"datasets/{repo_id}"


def bucket(bucket_id: str) -> str:
    return f"buckets/{bucket_id}"


def _api(resource: str):
    from huggingface_hub import HfApi

    return HfApi(token=token_for(resource))


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

    out: dict = {"auth": "oidc" if oidc_available() else "token"}
    if oidc_available():
        # Scoped tokens cannot create repos; the repos were created at setup. Check each one.
        for rid in (cfg.manifests_repo, cfg.ops_repo):
            info = _retry(lambda: _api(dataset(rid)).repo_info(rid, repo_type="dataset"))
            out[rid] = f"exists ({info.sha[:8]})"
        return out
    api = _api(dataset(cfg.ops_repo))
    out["whoami"] = api.whoami().get("name")
    for rid in (cfg.manifests_repo, cfg.ops_repo):
        url = _retry(lambda: api.create_repo(rid, repo_type="dataset", private=False, exist_ok=True))
        out[rid] = str(url)
    b = _retry(lambda: create_bucket(cfg.work_bucket, private=False, exist_ok=True,
                                     token=token_for(bucket(cfg.work_bucket))))
    out[cfg.work_bucket] = str(getattr(b, "bucket_id", b))
    return out


def put_json(cfg: Config, path_in_repo: str, data, message: str) -> str:
    api = _api(dataset(cfg.ops_repo))
    payload = json.dumps(data, indent=2, default=str).encode()
    _retry(lambda: api.upload_file(path_or_fileobj=io.BytesIO(payload), path_in_repo=path_in_repo,
                                   repo_id=cfg.ops_repo, repo_type="dataset", commit_message=message))
    return f"https://huggingface.co/datasets/{cfg.ops_repo}/blob/main/{path_in_repo}"


def put_files(cfg: Config, prefix: str, paths: list[str], message: str) -> list[str]:
    """Upload report files (JSON, logs, anything small) to the ops repo in one commit."""
    from pathlib import Path

    from huggingface_hub import CommitOperationAdd

    api = _api(dataset(cfg.ops_repo))
    files = [Path(p) for p in paths if Path(p).is_file()]
    if not files:
        return []
    ops = [CommitOperationAdd(path_in_repo=f"{prefix}/{f.name}", path_or_fileobj=str(f)) for f in files]
    _retry(lambda: api.create_commit(cfg.ops_repo, operations=ops, commit_message=message, repo_type="dataset"))
    return [f"https://huggingface.co/datasets/{cfg.ops_repo}/blob/main/{prefix}/{f.name}" for f in files]


def bucket_roundtrip(cfg: Config, run_id: str) -> dict:
    """Write, list, read back and delete one small object in the work bucket."""
    from huggingface_hub import batch_bucket_files, download_bucket_files, list_bucket_tree

    token = token_for(bucket(cfg.work_bucket))
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
