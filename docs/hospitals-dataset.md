---
license: cc0-1.0
pretty_name: RateCommons hospital price files
tags: [healthcare, price-transparency, hospitals, cms]
---

# RateCommons hospital price files

Every US hospital must publish a machine-readable file of its standard charges (45 CFR 180), including the
amount each insurance plan pays, its gross charge and its discounted cash price. Since January 2026 the files
must also carry, per plan, the median and 10th/90th percentile of the amounts actually paid on claims and the
number of claims. RateCommons collects these files and publishes them in one schema.

## How the files are found

Hospitals must publish `cms-hpt.txt` at the root of their website, listing each location and its file. We crawl
those files, seeded by DoltHub's hospital list (2023) and Wikidata's US hospitals with an official website, and
add every domain named inside a `cms-hpt.txt` (file hosts, contact e-mail domains) until nothing new turns up.
November 2026: 4,242 locations, 3,516 distinct file URLs on 1,200 domains (about 70% of US hospitals).
Aggregator link lists are not used as sources.

## Layout

- `index/cms_hpt_index.parquet`: location name, file URL, source page, hpt.txt URL, EIN parsed from the file name.
- `full/<fid>.parquet` (one per file, `fid` = first 16 hex digits of md5(file URL)) and `full/<fid>.json` (the
  file's header: hospital name, date, schema version, locations, addresses, type-2 NPIs; format, size, errors).
- `fees/hospital_fees.json`: per hospital (CMS Certification Number) x payer family x code, the facility amount
  for the RateCommons patient-tool procedures; `fees/attach.json`: which file belongs to which hospital and how.

Columns of `full/*.parquet`, one row per item x code x setting x payer/plan, as published:
`description, code, code_type, setting, gross, cash, payer, plan, methodology, dollar, percentage, algorithm,
median_allowed, p10, p90, count, notes, modifiers, billing_class`.

## Attaching files to hospitals

A file belongs to a hospital when one of its type-2 NPIs has an NPPES address at a hospital site (CMS Provider of
Services file gives the site its CCN); else when an organization NPI with the EIN in the file name does; else when
the street address the file lists matches the hospital's. Names are never used. Files whose NPIs span more than
three hospitals are not attached (system-wide files). November 2026: 2,465 of 3,227 parsed files, 2,242 hospitals.

## Caveats

- Values are as the hospital published them; we do not correct them. Percentages are of the hospital's charges.
- `count` is text as published (e.g. "1 through 10").
- About 9% of discovered URLs could not be read (404, HTML pages instead of files, malformed CSV).
- The CPT descriptor text in `description` is the hospital's own wording.
