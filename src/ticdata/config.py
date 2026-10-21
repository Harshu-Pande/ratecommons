"""Project names, read from project.toml when present, else these defaults.

Environment variables override everything (useful on Kaggle and Lightning, where
the package is installed from GitHub without the repo checkout):
  RC_HF_ORG, RC_MANIFESTS_REPO, RC_OPS_REPO, RC_WORK_BUCKET
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

_DEFAULTS = {
    "org": "ratecommons",
    "manifests_repo": "ratecommons/raw-manifests",
    "ops_repo": "ratecommons/ops",
    "work_bucket": "ratecommons/work",
}


@dataclass(frozen=True)
class Config:
    org: str
    manifests_repo: str
    ops_repo: str
    work_bucket: str


def _find_toml() -> Path | None:
    for base in [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parents[2]]:
        p = base / "project.toml"
        if p.is_file():
            return p
    return None


def load() -> Config:
    vals = dict(_DEFAULTS)
    p = _find_toml()
    if p:
        hf = tomllib.loads(p.read_text()).get("hf", {})
        vals.update({k: v for k, v in hf.items() if k in vals})
    env = {"org": "RC_HF_ORG", "manifests_repo": "RC_MANIFESTS_REPO",
           "ops_repo": "RC_OPS_REPO", "work_bucket": "RC_WORK_BUCKET"}
    for k, e in env.items():
        if os.environ.get(e):
            vals[k] = os.environ[e]
    return Config(**vals)
