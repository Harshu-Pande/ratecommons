# Decisions and lessons

The design doc is the blueprint; this file records where reality changed it.
Newest first. One entry per lesson: what we saw, what we changed.

## 2026-10-21

- **Workers are routed by what they can reach, not just by CPU.** The first Kaggle
  run (4 vCPU, 32.9 GB RAM, egress in Europe: CloudFront POP `CDG50`) showed:
  - UHC works: 80.5 MB/s from `mrfstorage.uhc.com`, faster than our US test box.
  - Cigna is geo-blocked: CloudFront answers 403 "configured to block access from
    your country" for the table of contents and every file behind it.
  - Aetna is unreachable: Kaggle's resolver returns `127.0.0.1` for
    `mrf.healthsparq.com`, so the connection is refused.
  So Kaggle takes UHC and UMR (the 89 TB bulk, all on UHC's host), and Cigna and
  Aetna go to US-based workers (GitHub Actions).
- **Kaggle benchmark (UHC P3 file, 4 vCPU).** rapidgzip produced 20.1 GB of JSON
  from 1.07 GB compressed in 61 s: 0.33 GB/s of JSON, ratio 18.7. Download alone ran
  at 84 MB/s, so decompression, not the network, is the limit (about 18 MB/s of
  compressed input). Each Kaggle session has 1.1 TB of free scratch disk (20.9 GB
  in `/kaggle/working`), so downloading whole files first is practical there.
  Consequence: UMR cannot be fully decompressed by brute force (about 1.7 PB of
  JSON); the tail-fingerprint dedup before download, and later the Rust splitter,
  carry the plan. Every report now records the
  worker's exit country (`machine().egress`) so this is checked, not assumed.
- **Lightning AI and Modal are out for now.** Lightning is not accepting new
  accounts; Modal requires a card. Neither is in the plan until that changes.
- **No `If-Range` on range requests.** Aetna's BunnyCDN reports ETag
  `"6ac42905-426438df"` (mtime-size), while a response that came from its Google
  Cloud origin reported `"-CI6x1vb2o5cDEAE="` for the same file. An `If-Range` the
  origin does not recognise turns a range request into a full-file `200`. Object
  identity is now checked by the total size in `Content-Range` (and the gzip tail
  fingerprint), never by ETag.
- **Never read a `200` body when a range was asked for.** UHC's Cloudflare front
  answered 6,209 of 7,312 first tail requests with the whole file; the second request
  returns `206`. `net.fetch_range` closes the connection at once and retries; the
  tests in `tests/test_net.py` simulate exactly this server.
- **One name, one config file.** Every Hugging Face repo and bucket name comes from
  `project.toml` so the project can be renamed without code changes.
- **Daily raw-manifest archive starts before any parsing.** Payers keep no history,
  so the indexes are archived from day 0; only changed sources are committed.
- **Workers report to Hugging Face, not to chat.** Every job writes JSON reports to
  `datasets/ratecommons/ops`, readable from any session.
