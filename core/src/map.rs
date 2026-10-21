//! Map one in-network file to the same tables as parse.py: provider_group, provider_set,
//! provider_reference, price_term, price_list, code, rate_fact/part-XX, meta.json.
//!
//! Threads: one inflates, the main thread splits records and handles provider_references,
//! N workers parse in_network records, one writes Parquet. Workers cache by the raw text of
//! repeated JSON (a provider_references list, a negotiated_prices list, a single price) so
//! identical text is normalized and hashed once per worker.
use crossbeam_channel::{bounded, Receiver, Sender};
use serde_json::value::RawValue;
// Keys are mostly hashes already; Fx avoids SipHash's cost on every lookup.
use rustc_hash::{FxHashMap as HashMap, FxHashSet as HashSet};
use std::io::Read;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::Instant;

use crate::model::*;
use crate::split::{split, Event};
use crate::writer::*;

const HEADER_KEYS: [&str; 11] = [
    "reporting_entity_name", "reporting_entity_type", "plan_name", "plan_id_type", "plan_id",
    "plan_market_type", "issuer_name", "plan_sponsor_name", "plan_spsonser_name", "last_updated_on", "version",
];
const PRICE_KEYS: [&str; 8] = [
    "negotiated_rate", "negotiated_type", "setting", "service_code", "billing_code_modifier",
    "additional_information", "billing_class", "expiration_date",
];
const CACHE_CAP: usize = 2_000_000;

pub struct Seen {
    pub shards: Vec<Mutex<HashSet<u128>>>,
    cap: usize,
}
impl Seen {
    pub fn new(cap: usize) -> Seen {
        Seen { shards: (0..64).map(|_| Mutex::new(HashSet::default())).collect(), cap: cap / 64 }
    }
    pub fn contains(&self, id: &Id) -> bool {
        self.shards[(id[0] & 63) as usize].lock().unwrap().contains(&u128::from_be_bytes(*id))
    }
    /// true when `id` was not seen before (the caller then emits its row)
    pub fn insert(&self, id: &Id) -> bool {
        let mut s = self.shards[(id[0] & 63) as usize].lock().unwrap();
        if s.len() >= self.cap {
            s.clear();
        }
        s.insert(u128::from_be_bytes(*id))
    }
}

/// What a fully parsed in_network record produced, for skipping byte-identical records later in
/// the shard. Only records that raised no flag are kept, so a skip loses nothing but work.
#[derive(Clone, Copy)]
pub struct RecInfo {
    pub block_id: Id,
    pub code_id: Id,
    pub part: i32,
    pub n_pairs: i32,
    pub n_rates: u32,
    pub layout: u8, // 1 = provider_references, 2 = inline_provider_groups
}
const REC_BYTES: usize = 16 + 16 + 16 + 4 + 4 + 4 + 1;

pub struct RecordCache {
    shards: Vec<Mutex<HashMap<u128, RecInfo>>>,
    cap: usize,
}
impl RecordCache {
    fn new(cap: usize) -> RecordCache {
        RecordCache { shards: (0..64).map(|_| Mutex::new(HashMap::default())).collect(), cap: cap / 64 }
    }
    fn get(&self, k: u128) -> Option<RecInfo> {
        self.shards[(k & 63) as usize].lock().unwrap().get(&k).copied()
    }
    fn put(&self, k: u128, v: RecInfo) {
        let mut s = self.shards[(k & 63) as usize].lock().unwrap();
        if s.len() < self.cap {
            s.insert(k, v);
        }
    }
    fn load(&self, path: &str) -> u64 {
        let b = std::fs::read(path).unwrap_or_default();
        let mut n = 0;
        for c in b.chunks_exact(REC_BYTES) {
            let k = u128::from_be_bytes(c[0..16].try_into().unwrap());
            self.put(k, RecInfo {
                block_id: c[16..32].try_into().unwrap(), code_id: c[32..48].try_into().unwrap(),
                part: i32::from_le_bytes(c[48..52].try_into().unwrap()),
                n_pairs: i32::from_le_bytes(c[52..56].try_into().unwrap()),
                n_rates: u32::from_le_bytes(c[56..60].try_into().unwrap()), layout: c[60],
            });
            n += 1;
        }
        n
    }
    fn save(&self, path: &str) -> u64 {
        let mut out = Vec::new();
        let mut n = 0;
        for sh in &self.shards {
            for (k, v) in sh.lock().unwrap().iter() {
                out.extend_from_slice(&k.to_be_bytes());
                out.extend_from_slice(&v.block_id);
                out.extend_from_slice(&v.code_id);
                out.extend_from_slice(&v.part.to_le_bytes());
                out.extend_from_slice(&v.n_pairs.to_le_bytes());
                out.extend_from_slice(&v.n_rates.to_le_bytes());
                out.push(v.layout);
                n += 1;
            }
        }
        std::fs::write(path, out).expect("write record cache");
        n
    }
}

struct PgTable {
    rows: Vec<PgRow>,
    index: HashMap<Id, usize>,
}

pub struct Shared {
    pg: Mutex<PgTable>,
    blocks: Seen,
    pt_seen: Seen,
    pl_seen: Seen,
    ps_seen: Seen,
    pli_seen: Seen,
    code_seen: Seen,
}

enum Msg {
    Fb(Vec<FbRow>),
    Pt(Vec<PtRow>),
    Pl(Vec<(Id, Vec<Id>)>),
    Ps(Vec<(Id, Vec<Id>)>),
    Pli(Vec<(Id, Vec<Id>)>),
    Code(Vec<CodeRow>),
    Fact(Vec<FactRow>),
}

fn truthy(r: Option<&RawValue>) -> bool {
    match r {
        None => false,
        Some(r) => {
            let t = r.get();
            match t.as_bytes().first() {
                Some(b'[') => arr(Some(r)).map(|a| !a.0.is_empty()).unwrap_or(false),
                Some(b'{') => obj(r).map(|o| !o.0.is_empty()).unwrap_or(false),
                Some(b'"') => t.len() > 2,
                Some(b'n') | Some(b'f') => false,
                Some(b't') => true,
                _ => to_e4(t).map(|(v, _)| v != 0).unwrap_or(true),
            }
        }
    }
}

/// provider group -> pg_id (shared table; names accumulate on duplicates)
fn provider_group(sh: &Shared, g: &RawValue, f: &mut Flags, counts: &mut HashMap<&'static str, u64>) -> Option<Id> {
    let o = match obj(g) {
        Some(o) => o,
        None => {
            f.add("provider_group_not_object");
            return None;
        }
    };
    let tin = norm_tin(o.get("tin"), f);
    let (npis, tin_wide) = norm_npis(o.get("npi"), f);
    let npi_s: Vec<String> = npis.iter().map(|n| n.to_string()).collect();
    let pid = Canon::new("pg").opt(tin.ttype.as_deref()).opt(tin.value.as_deref()).list(&npi_s)
        .s(if tin_wide { "1" } else { "0" }).digest();
    *counts.entry("provider_groups_seen").or_insert(0) += 1;
    let mut t = sh.pg.lock().unwrap();
    match t.index.get(&pid) {
        Some(&i) => {
            f.add("provider_group_duplicate");
            if let Some(n) = tin.business_name.filter(|n| !n.is_empty()) {
                if !t.rows[i].business_names.contains(&n) {
                    t.rows[i].business_names.push(n);
                }
            }
        }
        None => {
            let i = t.rows.len();
            t.index.insert(pid, i);
            t.rows.push(PgRow {
                pg_id: pid, tin_type: tin.ttype, tin_value: tin.value, tin_raw: tin.raw, npis, tin_wide,
                business_names: tin.business_name.filter(|n| !n.is_empty()).into_iter().collect(),
            });
        }
    }
    Some(pid)
}

/// The price's terms other than the amount, and its amount, each hashed; same encoding as parse.py.
fn amounts_key(o: &RawObject) -> (u64, u64) {
    let mut key: Vec<u8> = Vec::with_capacity(96);
    for k in ["negotiated_type", "billing_class", "setting"] {
        key.extend_from_slice(o.get(k).map(|r| r.get()).unwrap_or("null").as_bytes());
        key.push(SEP);
    }
    for (k, pad) in [("service_code", true), ("billing_code_modifier", false)] {
        match o.get(k) {
            Some(r) if r.get().starts_with('[') => {
                let mut v: Vec<String> = arr(Some(r)).unwrap().0.iter()
                    .map(|x| {
                        let s = raw_str(Some(x)).map(|s| s.trim().to_string()).unwrap_or("None".into());
                        if pad && s.chars().count() < 2 { format!("{:0>2}", s) } else { s }
                    })
                    .collect();
                v.sort();
                key.extend_from_slice(v.join("\u{1e}").as_bytes());
            }
            Some(r) if r.get() != "null" => {
                key.extend_from_slice(b"S:");
                key.extend_from_slice(r.get().as_bytes());
            }
            _ => {}
        }
        key.push(SEP);
    }
    let amt = raw_str(o.get("negotiated_rate")).map(|s| s.into_owned()).unwrap_or("None".into());
    (xxhash_rust::xxh3::xxh3_64(&key), xxhash_rust::xxh3::xxh3_64(amt.as_bytes()))
}

#[derive(Clone)]
struct Outs {
    fact: Sender<Msg>,
    pt: Sender<Msg>,
    other: Sender<Msg>,
}

struct Worker<'s> {
    sh: &'s Shared,
    rc: Option<&'s RecordCache>,
    refs: &'s HashMap<Option<String>, (Id, Vec<Id>)>,
    out: Outs,
    flags: Flags,
    counts: HashMap<&'static str, u64>,
    layout: HashSet<&'static str>,
    c_refs: HashMap<Id, Id>,
    c_prices: HashMap<Id, Id>,
    c_price: HashMap<Id, (Id, u64, u64)>,
    pt: Vec<PtRow>,
    pl: Vec<(Id, Vec<Id>)>,
    ps: Vec<(Id, Vec<Id>)>,
    codes: Vec<CodeRow>,
    facts: Vec<FactRow>,
    fb: Vec<FbRow>,
    pli: Vec<(Id, Vec<Id>)>,
    pl_ids: usize,
    ps_ids: usize,
    pli_ids: usize,
}

impl<'s> Worker<'s> {
    fn flush(&mut self, force: bool) {
        if force || self.pt.len() >= 50_000 { let v = std::mem::take(&mut self.pt); if !v.is_empty() { self.out.pt.send(Msg::Pt(v)).unwrap(); } }
        // list tables flush by size too: one Aetna provider set can name thousands of groups
        if force || self.pl.len() >= 50_000 || self.pl_ids >= 2_000_000 { self.pl_ids = 0; let v = std::mem::take(&mut self.pl); if !v.is_empty() { self.out.other.send(Msg::Pl(v)).unwrap(); } }
        if force || self.pli.len() >= 20_000 || self.pli_ids >= 2_000_000 { self.pli_ids = 0; let v = std::mem::take(&mut self.pli); if !v.is_empty() { self.out.other.send(Msg::Pli(v)).unwrap(); } }
        if force || self.ps.len() >= 20_000 || self.ps_ids >= 2_000_000 { self.ps_ids = 0; let v = std::mem::take(&mut self.ps); if !v.is_empty() { self.out.other.send(Msg::Ps(v)).unwrap(); } }
        if force || self.codes.len() >= 50_000 { let v = std::mem::take(&mut self.codes); if !v.is_empty() { self.out.other.send(Msg::Code(v)).unwrap(); } }
        if force || self.fb.len() >= 50_000 { let v = std::mem::take(&mut self.fb); if !v.is_empty() { self.out.other.send(Msg::Fb(v)).unwrap(); } }
        if force || self.facts.len() >= 200_000 { let v = std::mem::take(&mut self.facts); if !v.is_empty() { self.out.fact.send(Msg::Fact(v)).unwrap(); } }
    }

    /// (pt_id, hash of the terms other than the amount, hash of the amount): the two hashes feed
    /// the "several amounts under identical terms" flag without parsing the price again.
    fn price_term(&mut self, praw: &RawValue) -> (Id, u64, u64) {
        let key = xxh128(praw.get().as_bytes());
        if let Some(v) = self.c_price.get(&key) {
            return *v;
        }
        *self.counts.entry("pt_cache_miss").or_insert(0) += 1;
        let p = obj(praw).expect("price is an object");
        let (terms_h, amt_h) = amounts_key(&p);
        let f = &mut self.flags;
        let rate = p.get("negotiated_rate");
        let rate_s = raw_str(rate).map(|s| s.into_owned());
        let e4 = match &rate_s {
            None => {
                f.add("rate_missing");
                None
            }
            Some(t) => match to_e4(t) {
                None => {
                    f.add("rate_unparseable");
                    None
                }
                Some((v, inexact)) => {
                    if inexact {
                        f.add("rate_sub_e4_precision");
                    }
                    Some(v)
                }
            },
        };
        let ntype = raw_str(p.get("negotiated_type")).map(|s| s.into_owned());
        let setting = raw_str(p.get("setting")).map(|s| s.into_owned());
        if setting.is_none() {
            f.add("setting_missing");
        }
        let pos = norm_pos(p.get("service_code"), f);
        let mods = norm_mods(p.get("billing_code_modifier"));
        let info = raw_str(p.get("additional_information")).map(|s| s.into_owned());
        let bclass = raw_str(p.get("billing_class")).map(|s| s.into_owned());
        let exp = raw_str(p.get("expiration_date")).map(|s| s.into_owned());
        let pid = Canon::new("pt").opt(ntype.as_deref()).opt_i64(e4).opt(bclass.as_deref()).opt(setting.as_deref())
            .list(&pos).list(&mods).opt(exp.as_deref()).opt(info.as_deref()).digest();
        if self.sh.pt_seen.insert(&pid) {
            let mut rf = Vec::new();
            if let Some(v) = e4 {
                if v <= PLACEHOLDER_E4 && ntype.as_deref().unwrap_or("").to_lowercase() != "percentage" {
                    rf.push("placeholder_amount".to_string());
                    f.add("placeholder_amount");
                }
                if v <= 0 {
                    rf.push("non_positive_rate".to_string());
                }
            }
            let extra_keys: Vec<&(std::borrow::Cow<str>, &RawValue)> =
                p.0.iter().filter(|(k, _)| !PRICE_KEYS.contains(&k.as_ref())).collect();
            let extra = if extra_keys.is_empty() {
                None
            } else {
                let mut m = serde_json::Map::new();
                for (k, v) in extra_keys {
                    m.insert(k.to_string(), serde_json::from_str(v.get()).unwrap_or(serde_json::Value::Null));
                }
                Some(py_dumps(&serde_json::Value::Object(m), false))
            };
            let sc_raw = p.get("service_code").filter(|r| r.get() != "null")
                .map(|r| py_dumps(&serde_json::from_str(r.get()).unwrap_or(serde_json::Value::Null), false));
            let rc = rc_ranges(info.as_deref());
            self.pt.push(PtRow {
                pt_id: pid, negotiated_type: ntype, rate_e4: e4, rate_raw: rate_s, billing_class: bclass, setting,
                service_code: pos, service_code_raw: sc_raw, billing_code_modifier: mods, expiration_date: exp,
                additional_information: info, applies_to_revenue_codes: rc, extra, flags: rf,
            });
        }
        if self.c_price.len() >= CACHE_CAP {
            self.c_price.clear();
        }
        self.c_price.insert(key, (pid, terms_h, amt_h));
        (pid, terms_h, amt_h)
    }

    fn price_list(&mut self, prices: Option<&RawValue>) -> Id {
        let key = xxh128(prices.map(|p| p.get()).unwrap_or("null").as_bytes());
        if let Some(id) = self.c_prices.get(&key) {
            return *id;
        }
        let items: Vec<&RawValue> = arr(prices).map(|a| a.0).unwrap_or_default()
            .into_iter().filter(|p| p.get().starts_with('{')).collect();
        *self.counts.entry("pl_cache_miss").or_insert(0) += 1;
        let tpt = Instant::now();
        let terms: Vec<(Id, u64, u64)> = items.iter().map(|p| self.price_term(p)).collect();
        *self.counts.entry("t_price_term_us").or_insert(0) += tpt.elapsed().as_micros() as u64;
        let mut ids: Vec<Id> = terms.iter().map(|t| t.0).collect();
        let lid = h_ids(b"pl", &mut ids);
        if self.sh.pl_seen.insert(&lid) {
            // several amounts under otherwise identical terms: kept as a set, flagged
            if terms.len() >= 2 {
                let mut amounts: HashMap<u64, u64> = HashMap::with_capacity_and_hasher(terms.len(), Default::default());
                let mut multi = false;
                for &(_, k, a) in &terms {
                    match amounts.insert(k, a) {
                        Some(prev) if prev != a => {
                            multi = true;
                            break;
                        }
                        _ => {}
                    }
                }
                if multi {
                    self.flags.add("price_list_multiple_amounts");
                }
            }
            self.pl_ids += ids.len();
            self.pl.push((lid, ids));
        }
        if self.c_prices.len() >= CACHE_CAP {
            self.c_prices.clear();
        }
        self.c_prices.insert(key, lid);
        lid
    }

    /// A provider set's ID is its flattened, sorted group list (the design's identity); it is
    /// stored as the provider lists (one per reference, or one inline list) it was built from,
    /// because Aetna sets name thousands of groups and the same lists recur across sets.
    fn resolve_set(&mut self, nr: &RawObject) -> Id {
        let mut packed: Vec<&(Id, Vec<Id>)> = Vec::new();
        let refs_v = nr.get("provider_references");
        if let Some(a) = arr(refs_v) {
            for rid in a.0 {
                let k = raw_str(Some(rid)).map(|s| s.into_owned());
                match self.refs.get(&k) {
                    Some(v) => packed.push(v),
                    None => self.flags.add("provider_reference_unresolved"),
                }
            }
        }
        let mut inline: Vec<Option<Id>> = Vec::new();
        if truthy(nr.get("provider_groups")) {
            self.layout.insert("inline_provider_groups");
            for g in arr(nr.get("provider_groups")).map(|a| a.0).unwrap_or_default() {
                inline.push(provider_group(self.sh, g, &mut self.flags, &mut self.counts));
            }
        }
        if truthy(refs_v) {
            self.layout.insert("provider_references");
        }
        let mut lists: Vec<Id> = Vec::with_capacity(packed.len() + 1);
        for p in &packed {
            lists.push(p.0);
            if self.sh.pli_seen.insert(&p.0) {
                self.pli_ids += p.1.len();
                self.pli.push((p.0, p.1.clone()));
            }
        }
        let inline_ids: Vec<Id> = inline.iter().flatten().copied().collect();
        if !inline.is_empty() {
            let mut v = inline_ids.clone();
            let lid = h_ids(b"pli", &mut v);
            lists.push(lid);
            if self.sh.pli_seen.insert(&lid) {
                self.pli_ids += v.len();
                self.pli.push((lid, v));
            }
        }
        let mut ids: Vec<Id> = if packed.len() == 1 && inline.is_empty() {
            packed[0].1.clone()
        } else {
            let mut v: Vec<Id> = packed.iter().flat_map(|p| p.1.iter().copied()).collect();
            v.extend(inline_ids);
            v
        };
        let sid = h_ids(b"ps", &mut ids);
        if self.sh.ps_seen.insert(&sid) {
            lists.sort_unstable();
            lists.dedup();
            self.ps_ids += lists.len();
            self.ps.push((sid, lists));
        }
        sid
    }

    fn item(&mut self, key: u128, rec: &[u8]) {
        let flags_before = self.flags.1;
        let text = std::str::from_utf8(rec).expect("record is UTF-8");
        let it: RawObject = obj(raw(text)).expect("in_network item is a JSON object");
        let f = &mut self.flags;
        let ctype = raw_str(it.get("billing_code_type")).map(|s| s.into_owned());
        let code_raw = raw_str(it.get("billing_code")).map(|s| s.into_owned());
        let code = norm_billing_code(ctype.as_deref(), it.get("billing_code"), f);
        let ctype_a: Option<Arc<str>> = ctype.as_deref().map(Arc::from);
        let code_a: Option<Arc<str>> = code.as_deref().map(Arc::from);
        let bundle = {
            let mut m = serde_json::Map::new();
            for k in ["bundled_codes", "covered_services"] {
                if let Some(v) = it.get(k) {
                    m.insert(k.to_string(), serde_json::from_str(v.get()).unwrap_or(serde_json::Value::Null));
                }
            }
            if m.is_empty() { None } else { Some(py_dumps(&serde_json::Value::Object(m), true)) }
        };
        let s = |k: &str| raw_str(it.get(k)).map(|s| s.into_owned());
        let (arr_, ver, name, desc, sev) = (s("negotiation_arrangement"), s("billing_code_type_version"), s("name"),
                                            s("description"), s("severity_of_illness"));
        let cid = Canon::new("code").opt(arr_.as_deref()).opt(ctype.as_deref()).opt(ver.as_deref())
            .opt(code.as_deref()).opt(name.as_deref()).opt(desc.as_deref()).opt(sev.as_deref())
            .opt(bundle.as_deref()).digest();
        if self.sh.code_seen.insert(&cid) {
            self.codes.push(CodeRow {
                code_id: cid, negotiation_arrangement: arr_, billing_code_type: ctype.clone(),
                billing_code_type_version: ver, billing_code: code.clone(), billing_code_raw: code_raw, name,
                description: desc, severity_of_illness: sev, bundle,
            });
        }
        *self.counts.entry("in_network_items").or_insert(0) += 1;
        let mut pairs: Vec<[u8; 32]> = Vec::new();
        let mut layout_bits = 0u8;
        let mut n_rates = 0u32;
        for nr in arr(it.get("negotiated_rates")).map(|a| a.0).unwrap_or_default() {
            let o = match obj(nr) {
                Some(o) => o,
                None => {
                    self.flags.add("negotiated_rate_not_object");
                    continue;
                }
            };
            let refs_v = o.get("provider_references");
            let tps = Instant::now();
            let sid = if truthy(refs_v) && !truthy(o.get("provider_groups")) {
                self.layout.insert("provider_references");
                let key = xxh128(refs_v.unwrap().get().as_bytes());
                match self.c_refs.get(&key) {
                    Some(s) => *s,
                    None => {
                        let s = self.resolve_set(&o);
                        if self.c_refs.len() >= CACHE_CAP {
                            self.c_refs.clear();
                        }
                        self.c_refs.insert(key, s);
                        s
                    }
                }
            } else {
                self.resolve_set(&o)
            };
            *self.counts.entry("t_provider_set_us").or_insert(0) += tps.elapsed().as_micros() as u64;
            let tpl = Instant::now();
            let lid = self.price_list(o.get("negotiated_prices"));
            *self.counts.entry("t_price_list_us").or_insert(0) += tpl.elapsed().as_micros() as u64;
            *self.counts.entry("negotiated_rates").or_insert(0) += 1;
            n_rates += 1;
            if truthy(o.get("provider_references")) {
                layout_bits |= 1;
            }
            if truthy(o.get("provider_groups")) {
                layout_bits |= 2;
            }
            let mut pr = [0u8; 32];
            pr[..16].copy_from_slice(&sid);
            pr[16..].copy_from_slice(&lid);
            pairs.push(pr);
        }
        pairs.sort_unstable();
        pairs.dedup();
        let mut bb = Vec::with_capacity(3 + 16 + 32 * pairs.len());
        bb.extend_from_slice(b"blk");
        bb.extend_from_slice(&cid);
        for pr in &pairs {
            bb.extend_from_slice(pr);
        }
        let bid = xxh128(&bb);
        let part = fact_part(ctype.as_deref(), code.as_deref()) as i32;
        self.fb.push(FbRow { block_id: bid, code_id: cid, part, n_rates: pairs.len() as i32 });
        if let Some(rc) = self.rc {
            if self.flags.1 == flags_before {
                rc.put(key, RecInfo { block_id: bid, code_id: cid, part, n_pairs: pairs.len() as i32, n_rates,
                                      layout: layout_bits });
            }
        }
        if !self.sh.blocks.insert(&bid) {
            *self.counts.entry("blocks_repeated").or_insert(0) += 1;
        } else {
            *self.counts.entry("blocks_new").or_insert(0) += 1;
            for pr in &pairs {
                let mut sid = [0u8; 16];
                let mut lid = [0u8; 16];
                sid.copy_from_slice(&pr[..16]);
                lid.copy_from_slice(&pr[16..]);
                self.facts.push(FactRow { fact_id: fact_id(&cid, &sid, &lid), code_id: cid, ps_id: sid, pl_id: lid,
                                          block_id: bid, billing_code_type: ctype_a.clone(), billing_code: code_a.clone() });
            }
        }
        self.flush(false);
    }
}

fn writer_thread(rx: Receiver<Msg>, outdir: String) -> serde_json::Map<String, serde_json::Value> {
    let fact_dir = format!("{outdir}/rate_fact");
    let mut w: HashMap<&'static str, Pq> = HashMap::default();
    let mut parts: Vec<Option<Pq>> = (0..FACT_PARTS).map(|_| None).collect();
    let mut busy = std::collections::BTreeMap::<&str, f64>::new();
    fn wr<'a>(w: &'a mut HashMap<&'static str, Pq>, outdir: &str, name: &'static str) -> &'a mut Pq {
        w.entry(name).or_insert_with(|| Pq::create(&format!("{outdir}/{name}.parquet"), name))
    }
    for m in rx {
        let t = Instant::now();
        let kind = match m {
            Msg::Pt(v) => { wr(&mut w, &outdir, "price_term").write(pt_cols(&v), "price_term"); "price_term" }
            Msg::Pl(v) => { wr(&mut w, &outdir, "price_list").write(pl_cols(&v), "price_list"); "price_list" }
            Msg::Ps(v) => { wr(&mut w, &outdir, "provider_set").write(ps_cols(&v), "provider_set"); "provider_set" }
            Msg::Pli(v) => { wr(&mut w, &outdir, "provider_list").write(ps_cols(&v), "provider_list"); "provider_list" }
            Msg::Code(v) => { wr(&mut w, &outdir, "code").write(code_cols(&v), "code"); "code" }
            Msg::Fb(v) => { wr(&mut w, &outdir, "file_block").write(fb_cols(&v), "file_block"); "file_block" }
            Msg::Fact(v) => {
                std::fs::create_dir_all(&fact_dir).unwrap();
                let mut by: Vec<Vec<FactRow>> = (0..FACT_PARTS).map(|_| Vec::new()).collect();
                for r in v {
                    let k = fact_part(r.billing_code_type.as_deref(), r.billing_code.as_deref());
                    by[k].push(r);
                }
                for (k, rows) in by.into_iter().enumerate() {
                    if rows.is_empty() {
                        continue;
                    }
                    let pw = parts[k].get_or_insert_with(|| Pq::create(&format!("{fact_dir}/part-{k:02}.parquet"), "rate_fact"));
                    pw.write(fact_cols(&rows), "rate_fact");
                }
                "rate_fact"
            }
        };
        *busy.entry(kind).or_insert(0.0) += t.elapsed().as_secs_f64();
    }
    let mut out = serde_json::Map::new();
    for (name, pw) in w {
        let (rows, bytes) = pw.close();
        out.insert(name.into(), serde_json::json!({"rows": rows, "bytes": bytes}));
    }
    let (mut frows, mut fbytes, mut nparts) = (0u64, 0u64, 0u64);
    for pw in parts.into_iter().flatten() {
        let (r, b) = pw.close();
        frows += r;
        fbytes += b;
        nparts += 1;
    }
    if nparts > 0 {
        out.insert("rate_fact".into(), serde_json::json!({"rows": frows, "bytes": fbytes, "parts": nparts}));
    }
    out.insert("_writer_busy_seconds".into(), serde_json::json!(busy));
    out
}

fn open(path: &str) -> Box<dyn Read + Send> {
    let mut f = std::fs::File::open(path).expect("open");
    let mut magic = [0u8; 2];
    let _ = f.read(&mut magic);
    let r = std::io::BufReader::with_capacity(1 << 22, std::fs::File::open(path).expect("reopen"));
    if magic == [0x1f, 0x8b] {
        Box::new(flate2::read::MultiGzDecoder::new(r))
    } else if magic == *b"PK" {
        eprintln!("zip files are handled by the Python parser");
        std::process::exit(3);
    } else {
        Box::new(r)
    }
}

/// Inflate on a separate thread and hand back a reader over the decompressed chunks.
struct ChanReader {
    rx: Receiver<Vec<u8>>,
    cur: Vec<u8>,
    pos: usize,
}
impl Read for ChanReader {
    fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
        while self.pos >= self.cur.len() {
            match self.rx.recv() {
                Ok(v) => {
                    self.cur = v;
                    self.pos = 0;
                }
                Err(_) => return Ok(0),
            }
        }
        let n = out.len().min(self.cur.len() - self.pos);
        out[..n].copy_from_slice(&self.cur[self.pos..self.pos + n]);
        self.pos += n;
        Ok(n)
    }
}

fn threaded_reader(path: String, read: Arc<AtomicU64>) -> (ChanReader, std::thread::JoinHandle<()>) {
    let (tx, rx) = bounded::<Vec<u8>>(4);
    let h = std::thread::spawn(move || {
        let mut src = open(&path);
        loop {
            let mut chunk = vec![0u8; 16 << 20];
            let mut filled = 0;
            while filled < chunk.len() {
                let n = src.read(&mut chunk[filled..]).expect("inflate");
                if n == 0 {
                    break;
                }
                filled += n;
            }
            if filled == 0 {
                break;
            }
            chunk.truncate(filled);
            read.fetch_add(filled as u64, Ordering::Relaxed);
            if tx.send(chunk).is_err() {
                break;
            }
        }
    });
    (ChanReader { rx, cur: Vec::new(), pos: 0 }, h)
}

fn decode_scalar(raw: &[u8]) -> Option<String> {
    let t = std::str::from_utf8(raw).ok()?;
    let r: Box<RawValue> = serde_json::from_str(t).ok()?;
    raw_str(Some(&r)).map(|s| s.into_owned())
}

/// Load a seen-blocks file (concatenated 16-byte IDs) into the shared set.
fn load_blocks(path: &str, s: &Seen) -> u64 {
    let b = std::fs::read(path).unwrap_or_default();
    let mut n = 0;
    for c in b.chunks_exact(16) {
        let mut id = [0u8; 16];
        id.copy_from_slice(c);
        s.insert(&id);
        n += 1;
    }
    n
}

fn save_blocks(path: &str, s: &Seen) -> u64 {
    let mut out = Vec::new();
    let mut n = 0;
    for sh in &s.shards {
        for v in sh.lock().unwrap().iter() {
            out.extend_from_slice(&v.to_be_bytes());
            n += 1;
        }
    }
    std::fs::write(path, out).expect("write seen blocks");
    n
}

pub fn map_file(path: &str, outdir: &str, threads: usize, source: serde_json::Value,
                seen_blocks: Option<&str>, record_cache: Option<&str>) -> serde_json::Value {
    let t0 = Instant::now();
    std::fs::create_dir_all(outdir).unwrap();
    let size = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
    let tail = {
        let mut f = std::fs::File::open(path).unwrap();
        use std::io::{Seek, SeekFrom};
        let mut b = [0u8; 8];
        if size >= 8 {
            f.seek(SeekFrom::Start(size - 8)).unwrap();
            f.read_exact(&mut b).unwrap();
        }
        b
    };

    let sh = Arc::new(Shared {
        pg: Mutex::new(PgTable { rows: Vec::new(), index: HashMap::default() }),
        blocks: Seen::new(usize::MAX / 2),
        pt_seen: Seen::new(60_000_000),
        pl_seen: Seen::new(60_000_000),
        ps_seen: Seen::new(50_000_000),
        pli_seen: Seen::new(50_000_000),
        code_seen: Seen::new(50_000_000),
    });
    let blocks_loaded = seen_blocks.map(|p| load_blocks(p, &sh.blocks)).unwrap_or(0);
    let rcache: Option<Arc<RecordCache>> = record_cache.map(|_| Arc::new(RecordCache::new(10_000_000)));
    let recs_loaded = match (&rcache, record_cache) {
        (Some(c), Some(p)) => c.load(p),
        _ => 0,
    };
    let mut refs_digest: u128 = 0;
    let mut skip_fb: Vec<FbRow> = Vec::new();
    let mut skipped: u64 = 0;
    let mut skipped_rates: u64 = 0;
    let mut skip_layout = 0u8;
    // three writer threads: rate facts, price terms, everything else
    let mut whs = Vec::new();
    let mut senders = Vec::new();
    for _ in 0..3 {
        let (tx, rx) = bounded::<Msg>(8);
        let od = outdir.to_string();
        whs.push(std::thread::spawn(move || writer_thread(rx, od)));
        senders.push(tx);
    }
    let wtx = Outs { fact: senders[0].clone(), pt: senders[1].clone(), other: senders[2].clone() };
    drop(senders);

    let mut main_flags = Flags::default();
    let mut main_counts: HashMap<&'static str, u64> = HashMap::default();
    let mut refs: HashMap<Option<String>, (Id, Vec<Id>)> = HashMap::default();
    let mut ref_rows: Vec<RefRow> = Vec::new();
    let mut ref_index: HashMap<Option<String>, usize> = HashMap::default();
    let mut header = serde_json::Map::new();
    let mut extra_top = serde_json::Map::new();
    let mut keys: Vec<String> = Vec::new();
    let mut refs_key_seen = false;
    let mut refs_after_items = false;
    // hash of the raw provider_references records in order: two files with the same value resolve
    // every reference identically (the basis for skipping byte-identical records across files)
    let mut refs_hasher = xxhash_rust::xxh3::Xxh3::new();

    // workers start lazily, when the first in_network record arrives (references are complete then)
    let mut item_tx: Option<Sender<(u128, Vec<u8>)>> = None;
    let mut handles: Vec<std::thread::JoinHandle<(Flags, HashMap<&'static str, u64>, HashSet<&'static str>)>> = Vec::new();
    let mut refs_arc: Option<Arc<HashMap<Option<String>, (Id, Vec<Id>)>>> = None;

    // records waiting for or inside workers are bounded by bytes, not only by count: one in_network
    // record can be hundreds of MB, and 256 of those would exhaust a 16 GB runner
    let inflight: Arc<(Mutex<usize>, Condvar)> = Arc::new((Mutex::new(0), Condvar::new()));
    let inflight_max: usize = std::env::var("TIC_INFLIGHT_MB").ok().and_then(|v| v.parse().ok()).unwrap_or(768) << 20;
    let read_bytes = Arc::new(AtomicU64::new(0));
    let sent = Arc::new(AtomicU64::new(0));
    let biggest = Arc::new(AtomicU64::new(0));
    // profiling aid: parse only the first N in_network records (the rest is still read, not parsed)
    let max_records: u64 = std::env::var("TIC_MAX_RECORDS").ok().and_then(|v| v.parse().ok()).unwrap_or(u64::MAX);
    let stop = Arc::new(AtomicBool::new(false));
    // progress on stderr every 15 s, so a killed run still shows how far it got and how big it grew
    let progress = {
        let (read_bytes, sent, biggest, stop, inflight, sh) =
            (read_bytes.clone(), sent.clone(), biggest.clone(), stop.clone(), inflight.clone(), sh.clone());
        std::thread::spawn(move || {
            let t = Instant::now();
            let mut last = 0u64;
            while !stop.load(Ordering::Relaxed) {
                std::thread::sleep(std::time::Duration::from_millis(250));
                let el = t.elapsed().as_secs();
                if el < last + 15 {
                    continue;
                }
                last = el;
                let rss_mb = std::fs::read_to_string("/proc/self/statm").ok()
                    .and_then(|s| s.split_whitespace().nth(1).and_then(|x| x.parse::<u64>().ok()))
                    .map(|p| p * 4096 >> 20).unwrap_or(0);
                let pg = sh.pg.lock().map(|t| t.rows.len()).unwrap_or(0);
                let inf = *inflight.0.lock().unwrap() >> 20;
                eprintln!("[ticcore {el}s] json {:.2} GB, records {}, biggest record {} MB, in flight {} MB, \
                           provider groups {}, rss {} MB",
                          read_bytes.load(Ordering::Relaxed) as f64 / 1e9, sent.load(Ordering::Relaxed),
                          biggest.load(Ordering::Relaxed) >> 20, inf, pg, rss_mb);
            }
        })
    };
    let (reader, inflater) = threaded_reader(path.to_string(), read_bytes.clone());
    let t_refs = std::cell::Cell::new(0.0f64);
    let total = split(reader, |ev| match ev {
        Event::Key(k) => {
            let k = String::from_utf8_lossy(k).into_owned();
            if k == "provider_references" {
                refs_key_seen = true;
            }
            if k == "in_network" && !refs_key_seen {
                main_flags.add("in_network_before_provider_references_or_absent");
            }
            keys.push(k);
        }
        Event::Scalar(k, v) => {
            let k = String::from_utf8_lossy(k).into_owned();
            let val = decode_scalar(v).map(serde_json::Value::String).unwrap_or(serde_json::Value::Null);
            if HEADER_KEYS.contains(&k.as_str()) { header.insert(k, val); } else { extra_top.insert(k, val); }
        }
        Event::Record(k, rec) => {
            if k == b"provider_references" {
                if item_tx.is_some() {
                    refs_after_items = true;
                    return;
                }
                refs_hasher.update(rec);
                refs_hasher.update(b"\x1e");
                let text = std::str::from_utf8(rec).expect("UTF-8");
                let r: RawObject = obj(raw(text)).expect("provider reference object");
                let rid = raw_str(r.get("provider_group_id")).map(|s| s.into_owned());
                let mut ids: Vec<Id> = Vec::new();
                for g in arr(r.get("provider_groups")).map(|a| a.0).unwrap_or_default() {
                    if let Some(id) = provider_group(&sh, g, &mut main_flags, &mut main_counts) {
                        ids.push(id);
                    }
                }
                ids.sort_unstable();
                ids.dedup();
                if r.has("location") {
                    main_flags.add("remote_provider_reference");
                }
                let row = RefRow {
                    provider_group_id: rid.clone(), pg_ids: ids.clone(),
                    network_name: arr(r.get("network_name")).map(|a| a.0).unwrap_or_default().iter()
                        .map(|n| raw_str(Some(n)).map(|s| s.into_owned()).unwrap_or("None".into())).collect(),
                    location: raw_str(r.get("location")).map(|s| s.into_owned()),
                };
                match ref_index.get(&rid) {
                    Some(&i) => {
                        main_flags.add("provider_reference_id_repeated");
                        ref_rows[i] = row;
                    }
                    None => {
                        ref_index.insert(rid.clone(), ref_rows.len());
                        ref_rows.push(row);
                    }
                }
                let mut lid_src = ids.clone();
                let lid = h_ids(b"pli", &mut lid_src);
                refs.insert(rid, (lid, ids));
                *main_counts.entry("provider_references").or_insert(0) += 1;
            } else if k == b"in_network" {
                if sent.load(Ordering::Relaxed) >= max_records {
                    return;
                }
                if item_tx.is_none() {
                    t_refs.set(t0.elapsed().as_secs_f64());
                    let arc = Arc::new(std::mem::take(&mut refs));
                    refs_arc = Some(arc.clone());
                    refs_digest = refs_hasher.digest128();
                    let (tx, rx) = bounded::<(u128, Vec<u8>)>(256);
                    for _ in 0..threads.max(1) {
                        let rx = rx.clone();
                        let sh = sh.clone();
                        let refs = arc.clone();
                        let out = wtx.clone();
                        let rc = rcache.clone();
                        let inflight = inflight.clone();
                        handles.push(std::thread::spawn(move || {
                            let mut w = Worker {
                                sh: &sh, rc: rc.as_deref(), refs: &refs, out, flags: Flags::default(),
                                counts: HashMap::default(),
                                layout: HashSet::default(), c_refs: HashMap::default(), c_prices: HashMap::default(),
                                c_price: HashMap::default(), pt: vec![], pl: vec![], ps: vec![], codes: vec![], facts: vec![],
                                fb: vec![], pli: vec![], pl_ids: 0, ps_ids: 0, pli_ids: 0,
                            };
                            let mut busy = 0.0f64;
                            for (key, rec) in rx {
                                let t = Instant::now();
                                w.item(key, &rec);
                                {
                                    let (m, cv) = &*inflight;
                                    *m.lock().unwrap() -= rec.len();
                                    cv.notify_all();
                                }
                                busy += t.elapsed().as_secs_f64();
                            }
                            *w.counts.entry("worker_busy_ms").or_insert(0) += (busy * 1000.0) as u64;
                            w.flush(true);
                            (w.flags, w.counts, w.layout)
                        }));
                    }
                    item_tx = Some(tx);
                }
                let key = if rcache.is_some() {
                    let mut h = xxhash_rust::xxh3::Xxh3::new();
                    h.update(&refs_digest.to_be_bytes());
                    h.update(rec);
                    h.digest128()
                } else {
                    0
                };
                if let Some(info) = rcache.as_ref().and_then(|c| c.get(key)) {
                    // byte-identical record under identical references, already parsed in this shard:
                    // only its membership row is new, unless its facts were never written here
                    if sh.blocks.contains(&info.block_id) {
                        skipped += 1;
                        skipped_rates += info.n_rates as u64;
                        skip_layout |= info.layout;
                        skip_fb.push(FbRow { block_id: info.block_id, code_id: info.code_id, part: info.part,
                                             n_rates: info.n_pairs });
                        if skip_fb.len() >= 50_000 {
                            wtx.other.send(Msg::Fb(std::mem::take(&mut skip_fb))).unwrap();
                        }
                        return;
                    }
                }
                {
                    let (m, cv) = &*inflight;
                    let mut g = m.lock().unwrap();
                    while *g > 0 && *g + rec.len() > inflight_max {
                        g = cv.wait(g).unwrap();
                    }
                    *g += rec.len();
                }
                sent.fetch_add(1, Ordering::Relaxed);
                biggest.fetch_max(rec.len() as u64, Ordering::Relaxed);
                item_tx.as_ref().unwrap().send((key, rec.to_vec())).unwrap();
            }
        }
    })
    .expect("read input");
    inflater.join().unwrap();
    drop(item_tx);
    let mut flags = main_flags;
    let mut counts = main_counts;
    let mut layout: HashSet<&'static str> = HashSet::default();
    for h in handles {
        let (f, c, l) = h.join().unwrap();
        flags.merge(&f);
        for (k, v) in c {
            *counts.entry(k).or_insert(0) += v;
        }
        layout.extend(l);
    }
    if !skip_fb.is_empty() {
        wtx.other.send(Msg::Fb(std::mem::take(&mut skip_fb))).unwrap();
    }
    if rcache.is_some() {
        *counts.entry("records_skipped").or_insert(0) += skipped;
        *counts.entry("in_network_items").or_insert(0) += skipped;
        *counts.entry("negotiated_rates").or_insert(0) += skipped_rates;
        *counts.entry("blocks_repeated").or_insert(0) += skipped;
        if skip_layout & 1 != 0 {
            layout.insert("provider_references");
        }
        if skip_layout & 2 != 0 {
            layout.insert("inline_provider_groups");
        }
    }
    let t_items = t0.elapsed().as_secs_f64();
    stop.store(true, Ordering::Relaxed);
    let _ = progress.join();
    counts.insert("biggest_record_bytes", biggest.load(Ordering::Relaxed));
    drop(wtx);
    let mut tables = serde_json::Map::new();
    let mut wbusy = serde_json::Map::new();
    for h in whs {
        let mut m = h.join().unwrap();
        if let Some(serde_json::Value::Object(b)) = m.remove("_writer_busy_seconds") {
            wbusy.extend(b);
        }
        tables.extend(m);
    }
    for name in ["price_term", "price_list", "provider_set", "provider_list", "code", "file_block"] {
        if !tables.contains_key(name) {
            let pw = Pq::create(&format!("{outdir}/{name}.parquet"), name);
            let (r, b) = pw.close();
            tables.insert(name.into(), serde_json::json!({"rows": r, "bytes": b}));
        }
    }
    tables.insert("_writer_busy_seconds".into(), serde_json::Value::Object(wbusy));
    let mut tables = serde_json::Value::Object(tables);
    let _ = refs_arc;

    // provider groups and references are written last (names accumulate until the end)
    let pg = std::mem::replace(&mut sh.pg.lock().unwrap().rows, Vec::new());
    let mut w = Pq::create(&format!("{outdir}/provider_group.parquet"), "provider_group");
    for chunk in pg.chunks(500_000) {
        w.write(pg_cols(chunk), "provider_group");
    }
    if pg.is_empty() {
        w.write(pg_cols(&[]), "provider_group");
    }
    let (r, b) = w.close();
    tables["provider_group"] = serde_json::json!({"rows": r, "bytes": b});
    let mut w = Pq::create(&format!("{outdir}/provider_reference.parquet"), "provider_reference");
    w.write(ref_cols(&ref_rows), "provider_reference");
    let (r, b) = w.close();
    tables["provider_reference"] = serde_json::json!({"rows": r, "bytes": b});
    if refs_after_items {
        flags.add("provider_references_after_in_network_unsupported_in_rust");
    }

    let blocks_saved = seen_blocks.map(|p| save_blocks(p, &sh.blocks)).unwrap_or(0);
    if let (Some(c), Some(p)) = (&rcache, record_cache) {
        counts.insert("record_cache_loaded", recs_loaded);
        counts.insert("record_cache_saved", c.save(p));
    }
    counts.insert("seen_blocks_loaded", blocks_loaded);
    counts.insert("seen_blocks_saved", blocks_saved);
    let mut lay: Vec<&str> = layout.into_iter().collect();
    lay.sort();
    let counts_v: serde_json::Map<String, serde_json::Value> =
        counts.into_iter().map(|(k, v)| (k.to_string(), serde_json::json!(v))).collect();
    let meta = serde_json::json!({
        "source": source,
        "local_bytes": size,
        "tail_crc32": format!("0x{:08x}", u32::from_le_bytes([tail[0], tail[1], tail[2], tail[3]])),
        "tail_isize": u32::from_le_bytes([tail[4], tail[5], tail[6], tail[7]]),
        "header": header,
        "top_level_keys": keys,
        "extra_top_level": extra_top,
        "layout": lay,
        "counts": counts_v,
        "flags": flags.0,
        "tables": tables,
        "json_bytes": total,
        "refs_hash": format!("{:032x}", refs_hasher.digest128()),
        "seconds": {"refs_pass": (t_refs.get() * 10.0).round() / 10.0,
                    "items_pass": ((t_items - t_refs.get()) * 10.0).round() / 10.0,
                    "write": ((t0.elapsed().as_secs_f64() - t_items) * 10.0).round() / 10.0},
        "parser": "ticcore map v0.1",
        "threads": threads,
    });
    std::fs::write(format!("{outdir}/meta.json"), serde_json::to_string_pretty(&meta).unwrap()).unwrap();
    meta
}
