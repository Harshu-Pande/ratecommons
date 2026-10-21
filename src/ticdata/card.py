"""Dataset card (README.md) for one payer's dataset repo, built from what is actually published."""
from __future__ import annotations

TABLES = [
    ("rate_fact", "One row per distinct rate fact: a billing code, a provider set and a price list, with "
                  "the set of networks it appears in (`ns_id`). Sorted by code. 16 parts by billing code."),
    ("network_set", "`ns_id` -> the sorted list of `network_id`s sharing those facts. One file per "
                    "`rate_fact` part, so a set can repeat across files."),
    ("network", "One row per derived network: distinct file content (size and gzip trailer)."),
    ("source_file", "One row per source file: name, URL, size, gzip fingerprint, header, counts, "
                    "parser flags, and its `network_id`."),
    ("code", "Billing codes as published (type, version, code, arrangement), keyed by `code_id`. "
             "Descriptor text is withheld where it is licensed (see below)."),
    ("provider_set", "`ps_id` -> the provider lists (`pli_ids`) a rate applies to. Its ID is the hash of "
                     "the flattened, sorted group list."),
    ("provider_list", "`pli_id` -> the provider groups (`pg_ids`) of one provider reference as published."),
    ("provider_group", "`pg_id` -> TIN (type, normalized value, raw values) and sorted NPI list; "
                       "`tin_wide` when the file lists NPI 0 (the whole TIN). Business names are hints only."),
    ("price_list", "`pl_id` -> the price terms (`pt_ids`) of one negotiated_prices list."),
    ("price_term", "`pt_id` -> one negotiated price: type, amount (`rate_e4` = dollars x 10,000, plus "
                   "`rate_raw` exactly as published), billing class, setting, service codes, modifiers, "
                   "expiration date, additional information, parsed revenue-code ranges and flags."),
]


def _stats(repo: str, release: str) -> dict:
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, HfFileSystem

    api, fs = HfApi(), HfFileSystem()
    out: dict = {}
    for f in api.list_repo_tree(repo, repo_type="dataset", recursive=True, path_in_repo=f"release={release}"):
        if getattr(f, "size", None) is None or not f.path.endswith(".parquet"):
            continue
        table = f.path.split("/")[1].removesuffix(".parquet")
        with fs.open(f"datasets/{repo}/{f.path}") as fh:
            rows = pq.ParquetFile(fh).metadata.num_rows
        t = out.setdefault(table, {"files": 0, "bytes": 0, "rows": 0})
        t["files"] += 1
        t["bytes"] += f.size
        t["rows"] += rows
    return out


def build(payer: str, release: str, repo: str, payer_name: str, rows_in: int | None = None) -> str:
    st = _stats(repo, release)
    total_gb = sum(t["bytes"] for t in st.values()) / 1e9
    lines = [
        "---",
        f"pretty_name: RateCommons {payer_name} in-network rates",
        "license: other",
        "tags: [healthcare, price-transparency, transparency-in-coverage, insurance, parquet]",
        "configs:",
    ]
    for t, _ in TABLES:
        if t in st:
            pat = f"release={release}/{t}.parquet" if st[t]["files"] == 1 and t in ("code", "network", "source_file",
                                                                                 "provider_group") \
                else f"release={release}/{t}/*.parquet"
            lines += [f"- config_name: {t}", "  data_files:", f"  - split: release_{release.replace('-', '_')}",
                      f"    path: \"{pat}\""]
    lines += ["---", "",
              f"# RateCommons: {payer_name} in-network rates",
              "",
              f"Every in-network rate {payer_name} published under the Transparency in Coverage rule, parsed, "
              "deduplicated across files and stored as Parquet. Part of RateCommons, a free public dataset of "
              "negotiated health care prices. Code: https://github.com/Harshu-Pande/ratecommons",
              "",
              f"Release `{release}`: {st.get('source_file', {}).get('rows', '?'):,} source files, "
              f"{st.get('rate_fact', {}).get('rows', 0):,} distinct rate facts"
              + (f" from {rows_in:,} published rate rows" if rows_in else "")
              + f", {total_gb:.1f} GB.",
              "",
              "## Tables",
              "",
              "| Table | Rows | What it holds |",
              "| --- | ---: | --- |"]
    for t, desc in TABLES:
        if t in st:
            lines.append(f"| `{t}` | {st[t]['rows']:,} | {desc} |")
    base = f"hf://datasets/{repo}/release={release}"
    lines += [
        "",
        "## How the pieces fit",
        "",
        "IDs are content hashes (xxh3-128 over a canonical encoding of the values), so the same provider "
        "group, provider set, price term or price list gets the same ID in every file, release and payer. "
        "`code_id` also covers the payer's own wording (name, description, arrangement), so join codes "
        "across payers on `billing_code_type` and `billing_code`. A rate is the join",
        "",
        "```",
        "rate_fact -> code (code_id)",
        "          -> provider_set (ps_id) -> provider_list (pli_ids) -> provider_group (pg_ids)",
        "          -> price_list (pl_id)   -> price_term (pt_ids)",
        "          -> network_set (ns_id)  -> network / source_file (network_ids)",
        "```",
        "",
        "Example with DuckDB (reads only what the query needs):",
        "",
        "```sql",
        "INSTALL httpfs; LOAD httpfs;",
        f"CREATE VIEW fact AS SELECT * FROM '{base}/rate_fact/*.parquet';",
        f"CREATE VIEW ps AS SELECT DISTINCT s.ps_id, unnest(l.pg_ids) AS pg_id",
        f"  FROM (SELECT ps_id, unnest(pli_ids) AS pli_id FROM '{base}/provider_set/*.parquet') s",
        f"  JOIN '{base}/provider_list/*.parquet' l USING (pli_id);",
        f"CREATE VIEW pg AS SELECT * FROM '{base}/provider_group.parquet';",
        f"CREATE VIEW pl AS SELECT pl_id, unnest(pt_ids) AS pt_id FROM '{base}/price_list/*.parquet';",
        f"CREATE VIEW pt AS SELECT * FROM '{base}/price_term/*.parquet';",
        "",
        "SELECT pg.tin_value, pg.npis, pt.negotiated_type, pt.rate_e4 / 1e4 AS rate, pt.rate_raw,",
        "       pt.billing_class, pt.setting, pt.service_code, fact.ns_id",
        "FROM fact JOIN ps USING (ps_id) JOIN pg USING (pg_id) JOIN pl USING (pl_id) JOIN pt USING (pt_id)",
        "WHERE fact.billing_code_type = 'CPT' AND fact.billing_code = '99213'",
        "  AND pg.tin_value = '123456789';  -- a 9-digit EIN",
        "```",
        "",
        "`rate_fact` is split into 16 parts by `xxh3_64(billing_code_type + '\\x1f' + billing_code) % 16`, "
        "so a lookup by code can read one part. Files are ZSTD Parquet sorted by code, then provider set.",
        "",
        "## Reading it correctly",
        "",
        "- A missing rate means \"no published rate\", never \"out of network\".",
        "- A network here is a derived one: one distinct source file. `network_set` says which files carry "
        "a fact; `source_file.name` names the file (its product or region). Plan-to-file mappings are in "
        "the payer's table of contents, archived daily in `ratecommons/raw-manifests`.",
        "- Rates keep the published string (`rate_raw`) next to the integer amount (`rate_e4`, ten-thousandths "
        "of a dollar). `percentage` rates are percents, not dollars. Read `negotiated_type`, `billing_class` "
        "and `setting` before comparing amounts.",
        "- Provider identity is TIN plus NPI list. Names in payer files (`business_names`, network names) "
        "are not identities.",
        "- Nothing is dropped for being odd: deviations from the schema are kept and counted as flags "
        "(`price_term.flags`, `source_file.flags`), for example placeholder amounts of $0.01 or several "
        "amounts under identical terms.",
        "",
        "## Code descriptions",
        "",
        "Code numbers are published; descriptor text is not always ours to republish. Text is withheld "
        "(`code.text_withheld = true`, `name` and `description` empty) for CPT (AMA), CDT (ADA), revenue "
        "codes and proprietary DRG groupers, including descriptions inside `bundle`. HCPCS Level II, MS-DRG, "
        "ICD, APC, HIPPS, NDC and payer-defined codes keep their published text.",
        "",
        "## Provenance and license",
        "",
        f"Source: {payer_name}'s machine-readable files published under 45 CFR 147.212 (Transparency in "
        "Coverage). `source_file` lists every file with its URL and fingerprint. RateCommons makes no claim "
        "to the underlying rates. This is not medical, legal or financial advice; a published rate is not a "
        "quote of what a patient will pay.",
        "",
    ]
    return "\n".join(lines)


def publish(payer: str, release: str, repo: str, payer_name: str, rows_in: int | None = None,
            token: str | None = None) -> str:
    from huggingface_hub import HfApi

    text = build(payer, release, repo, payer_name, rows_in)
    HfApi(token=token).upload_file(path_or_fileobj=text.encode(), path_in_repo="README.md", repo_id=repo,
                                   repo_type="dataset", commit_message=f"Dataset card for release {release}")
    return text
