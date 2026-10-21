# ratecommons (working name)

A free, public, deduplicated dataset of the negotiated rates that UnitedHealthcare,
Aetna and Cigna publish under the federal Transparency in Coverage rule, plus free
tools to query it. Everything here runs on free, no-card services.

- Design doc (the blueprint): https://claude.ai/artifact/7d81McCZzQwiNqL6i28pNK
- Decisions and lessons learned while building: [docs/DECISIONS.md](docs/DECISIONS.md)
- What happens next: [docs/NEXT.md](docs/NEXT.md)

**Status:** day 0, infrastructure. No rate data is published yet.

## What runs where

| Job | Runs on | When | Writes to |
| --- | --- | --- | --- |
| `archive-manifests` | GitHub Actions | daily 09:17 UTC, or by hand | `datasets/ratecommons/raw-manifests` |
| `smoke` | GitHub Actions + Kaggle | by hand, or edit `ops/smoke-request.txt` | `datasets/ratecommons/ops` |

## Where the data lives (Hugging Face)

| Name | Kind | Holds |
| --- | --- | --- |
| `ratecommons/raw-manifests` | dataset | each payer's raw index files as served, daily, changes only |
| `ratecommons/ops` | dataset | run reports from every worker |
| `ratecommons/work` | bucket | scratch space for the processing stages |

All names live in `project.toml`, so a rename is a one-file change.

## Secrets (repo Settings → Secrets and variables → Actions)

`HF_TOKEN` (fine-grained, write access to the `ratecommons` org) and `KAGGLE_API_TOKEN`
(for workflows that launch Kaggle jobs). The Kaggle user name is in `project.toml`.
Tokens never go in code or issues. Later hardening: Hugging Face Trusted Publishers
(GitHub OIDC, one short-lived token per repo or bucket) can replace `HF_TOKEN`.

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
