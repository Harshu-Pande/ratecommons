"""Parser v0 (track A): one in-network file -> normalized, content-addressed Parquet.

This is the "map" stage of the design's map/shuffle/reduce pipeline, in Python so the
model can be proven on Cigna before the Rust core exists. It follows the Parser rules tab:
accept any valid JSON, keep every raw value, normalize beside it, record deviations as flags.

Tables written per file (IDs are xxh3-128 content hashes, so every worker agrees):
  provider_group     pg_id = TIN + sorted NPI list (names never part of identity)
  provider_set       ps_id = sorted distinct pg_ids
  provider_reference file-local provider_group_id -> pg_ids, with network_name as published
  price_term         pt_id = one negotiated price, amount in ten-thousandths of a dollar
  price_list         pl_id = sorted distinct pt_ids
  code               code_id = billing code with its arrangement, name, description, bundle
  rate_fact          fact_id = (code_id, ps_id, pl_id): the rate, once
plus meta.json with the header, counts, flags and timings.

Two passes over the decompressed stream: pass 1 walks events for the header and
`provider_references` (small) and stops when `in_network` begins; pass 2 lets ijson's C
backend build each `in_network` item. The file is local, so a second pass costs only
decompression.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

import xxhash

SEP, LSEP = "\x1f", "\x1e"
E4 = Decimal(10000)
PLACEHOLDER_E4 = 100  # $0.01
HEADER_KEYS = ("reporting_entity_name", "reporting_entity_type", "plan_name", "plan_id_type",
               "plan_id", "plan_market_type", "issuer_name", "plan_sponsor_name",
               "plan_spsonser_name", "last_updated_on", "version")


# ---------------------------------------------------------------- hashing

def h(*parts) -> bytes:
    """xxh3-128 of a canonical encoding: fields joined by US, lists sorted and joined by RS."""
    enc = []
    for p in parts:
        if p is None:
            enc.append("\x00")
        elif isinstance(p, (list, tuple)):
            enc.append(LSEP.join(sorted(x.hex() if isinstance(x, bytes) else str(x) for x in p)))
        elif isinstance(p, bytes):
            enc.append(p.hex())
        else:
            enc.append(str(p))
    return xxhash.xxh3_128_digest(SEP.join(enc).encode("utf-8"))


def h_ids(tag: str, ids) -> bytes:
    """Hash of a set of 16-byte IDs (order-free): tag plus the sorted, distinct IDs."""
    return xxhash.xxh3_128_digest(tag.encode() + b"".join(sorted(set(ids))))


PRICE_KEYS = frozenset(("negotiated_type", "negotiated_rate", "expiration_date", "service_code",
                        "billing_class", "setting", "billing_code_modifier", "additional_information"))


# ---------------------------------------------------------------- opening files

def open_json_stream(path: str, threads: int | None = None):
    """Binary stream of the JSON inside a local file: gzip (any number of members), zip or plain."""
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic[:2] == b"\x1f\x8b":
        import rapidgzip

        return rapidgzip.open(path, parallelization=threads or os.cpu_count() or 1)
    if magic[:2] == b"PK":
        import zipfile

        z = zipfile.ZipFile(path)
        names = [i for i in z.infolist() if not i.is_dir()]
        member = max(names, key=lambda i: i.file_size)
        return z.open(member)
    return open(path, "rb")


# ---------------------------------------------------------------- normalizers

def norm_tin(tin: dict | None, flags: Counter) -> tuple[str | None, str | None, str | None]:
    """(type, normalized value, raw value)."""
    if not isinstance(tin, dict):
        flags["tin_missing"] += 1
        return None, None, None
    ttype = str(tin.get("type") or "").strip().lower() or None
    raw = tin.get("value")
    raw_s = None if raw is None else str(raw)
    v = (raw_s or "").strip().replace("-", "")
    if raw_s is not None and v != raw_s:
        flags["tin_trimmed"] += 1
    if ttype == "ein" and v.isdigit() and len(v) == 8:
        v = "0" + v
        flags["ein_left_padded"] += 1
    if ttype == "ein" and not (v.isdigit() and len(v) == 9):
        flags["ein_malformed"] += 1
    if ttype == "npi" and not (v.isdigit() and len(v) == 10):
        flags["tin_npi_malformed"] += 1
    return ttype, v or None, raw_s


def norm_npis(npis, flags: Counter) -> tuple[list[int], bool]:
    """(sorted distinct real NPIs, tin_wide). `[0]` or a stray 0 means the whole TIN."""
    out, tin_wide = set(), False
    for x in npis or []:
        if isinstance(x, str):
            flags["npi_as_string"] += 1
            x = x.strip()
        try:
            n = int(x)
        except (TypeError, ValueError):
            flags["npi_unparseable"] += 1
            continue
        if n == 0:
            tin_wide = True
            continue
        if not (1_000_000_000 <= n <= 9_999_999_999):
            flags["npi_out_of_range"] += 1
        out.add(n)
    if tin_wide and out:
        flags["npi_zero_mixed_in"] += 1
    if not npis:
        flags["npi_list_empty"] += 1
    return sorted(out), tin_wide


def norm_pos(codes, flags: Counter) -> list[str]:
    out = []
    for c in codes or []:
        s = str(c).strip()
        if s.isdigit() and len(s) == 1:
            s = s.zfill(2)
            flags["pos_padded"] += 1
        out.append(s)
    return sorted(set(out))


def norm_billing_code(ctype: str | None, code, flags: Counter) -> str | None:
    if code is None:
        return None
    s = str(code)
    t = s.strip()
    if t != s:
        flags["billing_code_trimmed"] += 1
    if (ctype or "").upper() == "RC" and t.isdigit() and len(t) < 4:
        t = t.zfill(4)
        flags["revenue_code_padded"] += 1
    if t.upper() == "CSTM":
        t = "CSTM-00"
        flags["cstm_normalized"] += 1
    return t


def to_e4(raw, flags: Counter) -> int | None:
    if raw is None:
        flags["rate_missing"] += 1
        return None
    try:
        d = raw if isinstance(raw, Decimal) else Decimal(str(raw))
        q = d * E4
        i = q.to_integral_value(rounding=ROUND_HALF_EVEN)
        if i != q:
            flags["rate_sub_e4_precision"] += 1
        return int(i)
    except (InvalidOperation, ValueError):
        flags["rate_unparseable"] += 1
        return None


RC_RE = re.compile(r"RC\[(\d{1,4})-(\d{1,4})\]")


def rc_ranges(info: str | None) -> list[str]:
    if not info:
        return []
    return [f"{a.zfill(4)}-{b.zfill(4)}" for a, b in RC_RE.findall(info)]


def raw_str(v) -> str | None:
    return None if v is None else str(v)


# ---------------------------------------------------------------- the parser

class FileParser:
    def __init__(self):
        self.flags: Counter = Counter()
        self.header: dict = {}
        self.extra_top: dict = {}
        self.layout: set[str] = set()
        self.pg: dict[bytes, dict] = {}
        self.ps: dict[bytes, list[bytes]] = {}
        self.refs: dict[str, dict] = {}
        self.pt: dict[bytes, dict] = {}
        self.pl: dict[bytes, list[bytes]] = {}
        self.codes: dict[bytes, dict] = {}
        self.fact_buf: list[tuple] = []   # flushed to Parquet in batches (files can hold 10^8 facts)
        self.fact_sink = None
        self.counts: Counter = Counter()
        self._refset: dict[tuple, bytes] = {}   # raw provider_references list -> ps_id
        self._ptraw: dict[tuple, bytes] = {}    # raw price fields -> pt_id
        self._plraw: dict[tuple, bytes] = {}    # sorted pt_ids -> pl_id

    # provider groups ------------------------------------------------------
    def provider_group(self, g: dict) -> bytes | None:
        if not isinstance(g, dict):
            self.flags["provider_group_not_object"] += 1
            return None
        ttype, tval, traw = norm_tin(g.get("tin"), self.flags)
        npis, tin_wide = norm_npis(g.get("npi"), self.flags)
        pid = h("pg", ttype, tval, npis, int(tin_wide))
        name = (g.get("tin") or {}).get("business_name") if isinstance(g.get("tin"), dict) else None
        cur = self.pg.get(pid)
        self.counts["provider_groups_seen"] += 1
        if cur is None:
            self.pg[pid] = {"pg_id": pid, "tin_type": ttype, "tin_value": tval, "tin_raw": traw,
                            "npis": npis, "npi_count": len(npis), "tin_wide": tin_wide,
                            "business_names": [name] if name else []}
        else:
            self.flags["provider_group_duplicate"] += 1
            if name and name not in cur["business_names"]:
                cur["business_names"].append(name)
        return pid

    def provider_set(self, pg_ids) -> bytes:
        ids = sorted(set(p for p in pg_ids if p is not None))
        sid = h_ids("ps", ids)
        if sid not in self.ps:
            self.ps[sid] = ids
        return sid

    def reference(self, ref: dict):
        rid = raw_str(ref.get("provider_group_id"))
        ids = [self.provider_group(g) for g in ref.get("provider_groups") or []]
        if "location" in ref:
            self.flags["remote_provider_reference"] += 1
        if rid in self.refs:
            self.flags["provider_reference_id_repeated"] += 1
        self.refs[rid] = {"provider_group_id": rid, "pg_ids": sorted(set(i for i in ids if i)),
                          "network_name": [str(n) for n in (ref.get("network_name") or [])],
                          "location": raw_str(ref.get("location"))}
        self.counts["provider_references"] += 1

    # prices -------------------------------------------------------------
    def price_term(self, p: dict) -> bytes:
        if p.keys() <= PRICE_KEYS:  # fast path: identical raw price seen before in this file
            sc, bm = p.get("service_code"), p.get("billing_code_modifier")
            rk = (p.get("negotiated_type"), str(p.get("negotiated_rate")), p.get("billing_class"),
                  p.get("setting"), tuple(sc) if isinstance(sc, list) else sc,
                  tuple(bm) if isinstance(bm, list) else bm, p.get("expiration_date"),
                  p.get("additional_information"))
            pid = self._ptraw.get(rk)
            if pid is None:
                pid = self._price_term(p)
                self._ptraw[rk] = pid
            return pid
        return self._price_term(p)

    def _price_term(self, p: dict) -> bytes:
        f = self.flags
        e4 = to_e4(p.get("negotiated_rate"), f)
        ntype = raw_str(p.get("negotiated_type"))
        setting = raw_str(p.get("setting"))
        if setting is None:
            f["setting_missing"] += 1
        pos = norm_pos(p.get("service_code"), f)
        mods = sorted(set(str(m).strip() for m in (p.get("billing_code_modifier") or [])))
        info = raw_str(p.get("additional_information"))
        key = (ntype, e4, raw_str(p.get("billing_class")), setting, pos, mods,
               raw_str(p.get("expiration_date")), info)
        pid = h("pt", *key)
        if pid not in self.pt:
            row_flags = []
            if e4 is not None and e4 <= PLACEHOLDER_E4 and (ntype or "").lower() != "percentage":
                row_flags.append("placeholder_amount")
                f["placeholder_amount"] += 1
            if e4 is not None and e4 <= 0:
                row_flags.append("non_positive_rate")
            extra = {k: v for k, v in p.items() if k not in (
                "negotiated_rate", "negotiated_type", "setting", "service_code", "billing_code_modifier",
                "additional_information", "billing_class", "expiration_date")}
            self.pt[pid] = {"pt_id": pid, "negotiated_type": ntype, "rate_e4": e4,
                            "rate_raw": raw_str(p.get("negotiated_rate")),
                            "billing_class": key[2], "setting": setting, "service_code": pos,
                            "service_code_raw": json.dumps(p.get("service_code"), default=str)
                            if p.get("service_code") is not None else None,
                            "billing_code_modifier": mods, "expiration_date": key[6],
                            "additional_information": info, "applies_to_revenue_codes": rc_ranges(info),
                            "extra": json.dumps(extra, default=str) if extra else None,
                            "flags": row_flags}
        return pid

    def price_list(self, prices) -> bytes:
        ids = tuple(sorted(set(self.price_term(p) for p in prices or [] if isinstance(p, dict))))
        lid = self._plraw.get(ids)
        if lid is not None:
            return lid
        lid = h_ids("pl", ids)
        self._plraw[ids] = lid
        if lid not in self.pl:
            self.pl[lid] = ids
            # several amounts with identical terms otherwise: kept as a set, flagged
            seen = Counter((t["negotiated_type"], t["billing_class"], t["setting"],
                            tuple(t["service_code"]), tuple(t["billing_code_modifier"]))
                           for t in (self.pt[i] for i in ids))
            if any(c > 1 for c in seen.values()):
                self.flags["price_list_multiple_amounts"] += 1
        return lid

    # in-network items ---------------------------------------------------
    def item(self, it: dict):
        f = self.flags
        ctype = raw_str(it.get("billing_code_type"))
        code_raw = raw_str(it.get("billing_code"))
        code = norm_billing_code(ctype, it.get("billing_code"), f)
        bundle = {k: it[k] for k in ("bundled_codes", "covered_services") if k in it}
        ckey = ("code", raw_str(it.get("negotiation_arrangement")), ctype,
                raw_str(it.get("billing_code_type_version")), code, raw_str(it.get("name")),
                raw_str(it.get("description")), raw_str(it.get("severity_of_illness")),
                json.dumps(bundle, sort_keys=True, default=str) if bundle else None)
        cid = h(*ckey)
        if cid not in self.codes:
            self.codes[cid] = {"code_id": cid, "negotiation_arrangement": ckey[1], "billing_code_type": ctype,
                               "billing_code_type_version": ckey[3], "billing_code": code,
                               "billing_code_raw": code_raw, "name": ckey[5], "description": ckey[6],
                               "severity_of_illness": ckey[7], "bundle": ckey[8]}
        self.counts["in_network_items"] += 1
        for nr in it.get("negotiated_rates") or []:
            if not isinstance(nr, dict):
                f["negotiated_rate_not_object"] += 1
                continue
            raw_refs = nr.get("provider_references")
            if raw_refs and not nr.get("provider_groups"):
                rk = tuple(raw_refs)
                sid = self._refset.get(rk)
                if sid is None:
                    sid = self._resolve_set(nr)
                    self._refset[rk] = sid
                self.layout.add("provider_references")
            else:
                sid = self._resolve_set(nr)
            lid = self.price_list(nr.get("negotiated_prices"))
            fid = xxhash.xxh3_128_digest(b"fact" + cid + sid + lid)  # ordered: code, set, list
            self.counts["negotiated_rates"] += 1
            self.fact_buf.append((fid, cid, sid, lid, ctype, code))
            if len(self.fact_buf) >= 500_000 and self.fact_sink:
                self.fact_sink(self.fact_buf)
                self.fact_buf = []

    def _resolve_set(self, nr: dict) -> bytes:
        pg_ids: list[bytes] = []
        for rid in nr.get("provider_references") or []:
            r = self.refs.get(raw_str(rid))
            if r is None:
                self.flags["provider_reference_unresolved"] += 1
                continue
            pg_ids.extend(r["pg_ids"])
        if nr.get("provider_groups"):
            self.layout.add("inline_provider_groups")
            pg_ids.extend(self.provider_group(g) for g in nr["provider_groups"])
        if nr.get("provider_references"):
            self.layout.add("provider_references")
        return self.provider_set(pg_ids)

    # passes ---------------------------------------------------------------
    def pass_header_and_refs(self, stream):
        """Events until `in_network` starts (or EOF): header scalars and provider_references."""
        import ijson
        from ijson.common import ObjectBuilder

        builder, depth_key = None, None
        refs_done = False
        for prefix, event, value in ijson.parse(stream, use_float=False):
            if builder is not None:
                builder.event(event, value)
                if prefix == "provider_references.item" and event == "end_map":
                    self.reference(builder.value)
                    builder = None
                continue
            if prefix == "provider_references.item" and event == "start_map":
                builder = ObjectBuilder()
                builder.event(event, value)
                continue
            if prefix == "provider_references" and event == "end_array":
                refs_done = True
                continue
            if prefix == "" and event == "map_key":
                depth_key = value
                self.header.setdefault("_keys", []).append(value)
                if value == "in_network":
                    if refs_done:
                        return True  # references read; pass 2 handles in_network at C speed
                    # in_network first, or no provider_references (schema 1): keep walking (slow, correct)
                    self.flags["in_network_before_provider_references_or_absent"] += 1
                continue
            if depth_key is not None and prefix == depth_key and event in ("string", "number", "boolean", "null"):
                (self.header if depth_key in HEADER_KEYS else self.extra_top)[depth_key] = raw_str(value)
        return refs_done

    def pass_items(self, stream):
        import ijson

        for it in ijson.items(stream, "in_network.item", use_float=False):
            self.item(it)


# ---------------------------------------------------------------- writing

FACT_COLS = ("fact_id", "code_id", "ps_id", "pl_id", "billing_code_type", "billing_code")


class FactWriter:
    """Streams rate_fact rows to Parquet in file order (grouped by billing code)."""

    def __init__(self, path: str):
        import pyarrow as pa
        import pyarrow.parquet as pq

        b16 = pa.binary(16)
        self.pa = pa
        self.schema = pa.schema([("fact_id", b16), ("code_id", b16), ("ps_id", b16), ("pl_id", b16),
                                 ("billing_code_type", pa.string()), ("billing_code", pa.string())])
        self.w = pq.ParquetWriter(path, self.schema, compression="zstd", compression_level=6)
        self.rows = 0
        self.path = path

    def __call__(self, buf: list[tuple]):
        cols = list(zip(*buf)) if buf else [[] for _ in FACT_COLS]
        self.w.write_table(self.pa.table([self.pa.array(c, type=t) for c, t in zip(cols, self.schema.types)],
                                         schema=self.schema), row_group_size=1_000_000)
        self.rows += len(buf)

    def close(self) -> dict:
        self.w.close()
        return {"rows": self.rows, "bytes": os.path.getsize(self.path)}


def _write_tables(fp: FileParser, outdir: str) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    b16 = pa.binary(16)
    lst = lambda t: pa.list_(t)  # noqa: E731
    specs = {
        "provider_group": (list(fp.pg.values()), pa.schema([
            ("pg_id", b16), ("tin_type", pa.string()), ("tin_value", pa.string()), ("tin_raw", pa.string()),
            ("npis", lst(pa.int64())), ("npi_count", pa.int32()), ("tin_wide", pa.bool_()),
            ("business_names", lst(pa.string()))])),
        "provider_set": ([{"ps_id": k, "pg_ids": v} for k, v in fp.ps.items()],
                         pa.schema([("ps_id", b16), ("pg_ids", lst(b16))])),
        "provider_reference": (list(fp.refs.values()), pa.schema([
            ("provider_group_id", pa.string()), ("pg_ids", lst(b16)), ("network_name", lst(pa.string())),
            ("location", pa.string())])),
        "price_term": (list(fp.pt.values()), pa.schema([
            ("pt_id", b16), ("negotiated_type", pa.string()), ("rate_e4", pa.int64()), ("rate_raw", pa.string()),
            ("billing_class", pa.string()), ("setting", pa.string()), ("service_code", lst(pa.string())),
            ("service_code_raw", pa.string()), ("billing_code_modifier", lst(pa.string())),
            ("expiration_date", pa.string()), ("additional_information", pa.string()),
            ("applies_to_revenue_codes", lst(pa.string())), ("extra", pa.string()), ("flags", lst(pa.string()))])),
        "price_list": ([{"pl_id": k, "pt_ids": v} for k, v in fp.pl.items()],
                       pa.schema([("pl_id", b16), ("pt_ids", lst(b16))])),
        "code": (list(fp.codes.values()), pa.schema([
            ("code_id", b16), ("negotiation_arrangement", pa.string()), ("billing_code_type", pa.string()),
            ("billing_code_type_version", pa.string()), ("billing_code", pa.string()),
            ("billing_code_raw", pa.string()), ("name", pa.string()), ("description", pa.string()),
            ("severity_of_illness", pa.string()), ("bundle", pa.string())])),
    }
    os.makedirs(outdir, exist_ok=True)
    sizes = {}
    for name, (rows, schema) in specs.items():
        t = pa.Table.from_pylist(rows, schema=schema)
        path = os.path.join(outdir, f"{name}.parquet")
        pq.write_table(t, path, compression="zstd", compression_level=6, row_group_size=1_000_000)
        sizes[name] = {"rows": t.num_rows, "bytes": os.path.getsize(path)}
    return sizes


def parse_file(path: str, outdir: str, source: dict | None = None) -> dict:
    """Parse one local in-network file into `outdir`. Returns the meta written to meta.json."""
    t0 = time.time()
    fp = FileParser()
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - 8))
        tail = f.read(8)
    with open_json_stream(path) as s1:
        fp.pass_header_and_refs(s1)
    t1 = time.time()
    os.makedirs(outdir, exist_ok=True)
    fw = FactWriter(os.path.join(outdir, "rate_fact.parquet"))
    fp.fact_sink = fw
    with open_json_stream(path) as s2:
        fp.pass_items(s2)
    fw(fp.fact_buf)
    fp.fact_buf = []
    t2 = time.time()
    sizes = _write_tables(fp, outdir)
    sizes["rate_fact"] = fw.close()
    meta = {
        "source": source or {}, "local_bytes": size,
        "tail_crc32": f"0x{int.from_bytes(tail[:4], 'little'):08x}" if len(tail) == 8 else None,
        "tail_isize": int.from_bytes(tail[4:], "little") if len(tail) == 8 else None,
        "header": {k: v for k, v in fp.header.items() if k != "_keys"}, "top_level_keys": fp.header.get("_keys", []),
        "extra_top_level": fp.extra_top, "layout": sorted(fp.layout), "counts": dict(fp.counts),
        "flags": dict(sorted(fp.flags.items())), "tables": sizes,
        "seconds": {"refs_pass": round(t1 - t0, 1), "items_pass": round(t2 - t1, 1),
                    "write": round(time.time() - t2, 1)},
        "parser": "ticdata.parse v0",
    }
    with open(os.path.join(outdir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2, default=str)
    return meta
