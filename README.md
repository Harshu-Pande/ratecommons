# ratecommons (working name)

A free, public, deduplicated dataset of the negotiated rates that UnitedHealthcare,
Aetna and Cigna publish under the federal Transparency in Coverage rule, plus free
tools to query it. Everything here runs on free, no-card services.

- Design doc (the blueprint): https://claude.ai/artifact/7d81McCZzQwiNqL6i28pNK
- Decisions and lessons learned while building: [docs/DECISIONS.md](docs/DECISIONS.md)
- What happens next: [docs/NEXT.md](docs/NEXT.md)

**Status:** day 0, infrastructure ready (GitHub, Hugging Face, Kaggle measured). No rate data is published yet.

## What runs where

| Job | Runs on | When | Writes to |
| --- | --- | --- | --- |
| `archive-manifests` | GitHub Actions | daily 09:17 UTC, by hand, or edit `ops/archive-request.txt` | `datasets/ratecommons/raw-manifests` |
| `smoke` | GitHub Actions | by hand, or edit `ops/smoke-request.txt` | `datasets/ratecommons/ops` |
| `kaggle` | Kaggle, launched from GitHub Actions | by hand, or edit `ops/kaggle-request.txt` (last line = job folder) | `datasets/ratecommons/ops` |

GitHub writes to Hugging Face through Trusted Publishers (short-lived tokens, nothing
stored). Kaggle sessions exit in Europe or the US. From Europe they reach only UHC/UMR,
because Cigna geo-blocks Europe and Aetna is unreachable there, so workers check which
payers they can reach before taking jobs.

## Where the data lives (Hugging Face)

| Name | Kind | Holds |
| --- | --- | --- |
| `ratecommons/raw-manifests` | dataset | each payer's raw index files as served, daily, changes only |
| `ratecommons/ops` | dataset | run reports from every worker |
| `ratecommons/work` | bucket | scratch space for the processing stages |

All names live in `project.toml`, so a rename is a one-file change.

## Secrets (repo Settings → Secrets and variables → Actions)

Only `KAGGLE_API_TOKEN` (for the `kaggle` workflow). Hugging Face needs no secret:
each dataset and bucket trusts this repo's `main` branch as a Trusted Publisher, and
a new dataset or bucket must be given the same setting. The Kaggle user name is in
`project.toml`. Tokens never go in code or issues.

## Local use

```bash
pip install -e ".[dev]"
pytest
ticdata --help
ticdata smoke-net --mb 64     # reach all three payers, probe byte ranges
ticdata fingerprint <url>     # gzip-tail fingerprint of one file
```

## Layout

```
src/ticdata/net.py        guarded range reads, resumable seekable HTTP file
src/ticdata/discover.py   payer front doors (UHC blob list, Aetna brand manifests, Cigna ToC)
src/ticdata/archive.py    daily raw-manifest archive
src/ticdata/smoke.py      platform smoke tests and the download/decompress benchmark
src/ticdata/hfio.py       Hugging Face repos, bucket, reports
kaggle/smoke/             Kaggle kernel generator for the smoke test
.github/workflows/        smoke, archive-manifests
```

## License

Code: Apache-2.0. Data license to be decided before the first data release.
