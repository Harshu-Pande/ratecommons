//! Normalization and content hashing: a line-for-line port of `src/ticdata/parse.py`, so that
//! Python and Rust workers compute the same IDs for the same content. Any change here must be
//! mirrored there (and the cross-check test in tests/test_core_parity.py must pass).
use serde::de::{Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::value::RawValue;
use std::borrow::Cow;
use std::collections::BTreeMap;
use std::fmt;

pub const SEP: u8 = 0x1f;
pub const LSEP: u8 = 0x1e;
pub const PLACEHOLDER_E4: i64 = 100;
pub type Id = [u8; 16];

// ------------------------------------------------------------------ hashing

pub fn xxh128(data: &[u8]) -> Id {
    xxhash_rust::xxh3::xxh3_128(data).to_be_bytes()
}

/// Canonical encoding of `h(*parts)` in parse.py: fields joined by 0x1f; None is "\0";
/// lists are sorted as strings and joined by 0x1e; bytes are lowercase hex.
#[derive(Default)]
pub struct Canon {
    buf: Vec<u8>,
    first: bool,
}

impl Canon {
    pub fn new(tag: &str) -> Self {
        let mut c = Canon { buf: Vec::with_capacity(128), first: true };
        c.s(tag);
        c
    }
    fn sep(&mut self) {
        if !self.first {
            self.buf.push(SEP);
        }
        self.first = false;
    }
    pub fn s(&mut self, v: &str) -> &mut Self {
        self.sep();
        self.buf.extend_from_slice(v.as_bytes());
        self
    }
    pub fn opt(&mut self, v: Option<&str>) -> &mut Self {
        match v {
            Some(x) => self.s(x),
            None => {
                self.sep();
                self.buf.push(0);
                self
            }
        }
    }
    pub fn opt_i64(&mut self, v: Option<i64>) -> &mut Self {
        match v {
            Some(x) => self.s(&x.to_string()),
            None => self.opt(None),
        }
    }
    /// A list field: sorted as strings, joined by 0x1e.
    pub fn list(&mut self, items: &[String]) -> &mut Self {
        self.sep();
        let mut v: Vec<&String> = items.iter().collect();
        v.sort();
        for (i, x) in v.iter().enumerate() {
            if i > 0 {
                self.buf.push(LSEP);
            }
            self.buf.extend_from_slice(x.as_bytes());
        }
        self
    }
    pub fn digest(&self) -> Id {
        xxh128(&self.buf)
    }
}

/// `xxh3_128(tag + b"".join(sorted(set(ids))))`, as `h_ids` / `pack` in parse.py.
pub fn h_ids(tag: &[u8], ids: &mut Vec<Id>) -> Id {
    ids.sort_unstable();
    ids.dedup();
    let mut b = Vec::with_capacity(tag.len() + 16 * ids.len());
    b.extend_from_slice(tag);
    for i in ids.iter() {
        b.extend_from_slice(i);
    }
    xxh128(&b)
}

pub fn fact_id(cid: &Id, sid: &Id, lid: &Id) -> Id {
    let mut b = [0u8; 4 + 48];
    b[..4].copy_from_slice(b"fact");
    b[4..20].copy_from_slice(cid);
    b[20..36].copy_from_slice(sid);
    b[36..52].copy_from_slice(lid);
    xxh128(&b)
}

pub const FACT_PARTS: u64 = 16;

pub fn fact_part(ctype: Option<&str>, code: Option<&str>) -> usize {
    let mut b = Vec::with_capacity(32);
    b.extend_from_slice(ctype.unwrap_or("").as_bytes());
    b.push(SEP);
    b.extend_from_slice(code.unwrap_or("").as_bytes());
    (xxhash_rust::xxh3::xxh3_64(&b) % FACT_PARTS) as usize
}

// ------------------------------------------------------------------ raw JSON objects

/// A JSON object kept as (key, raw value) pairs in document order; values are not parsed.
pub struct RawObject<'a>(pub Vec<(Cow<'a, str>, &'a RawValue)>);

impl<'a> RawObject<'a> {
    pub fn get(&self, k: &str) -> Option<&'a RawValue> {
        self.0.iter().find(|(kk, _)| kk == k).map(|(_, v)| *v)
    }
    pub fn has(&self, k: &str) -> bool {
        self.0.iter().any(|(kk, _)| kk == k)
    }
}

impl<'de: 'a, 'a> Deserialize<'de> for RawObject<'a> {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V<'a>(std::marker::PhantomData<&'a ()>);
        impl<'de: 'a, 'a> Visitor<'de> for V<'a> {
            type Value = RawObject<'a>;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("a JSON object")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut m: M) -> Result<Self::Value, M::Error> {
                let mut v = Vec::with_capacity(8);
                while let Some(k) = m.next_key::<Cow<'de, str>>()? {
                    let val: &'de RawValue = m.next_value()?;
                    v.push((k, val));
                }
                Ok(RawObject(v))
            }
        }
        d.deserialize_map(V(std::marker::PhantomData))
    }
}

/// A JSON array kept as raw elements.
pub struct RawArray<'a>(pub Vec<&'a RawValue>);

impl<'de: 'a, 'a> Deserialize<'de> for RawArray<'a> {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V<'a>(std::marker::PhantomData<&'a ()>);
        impl<'de: 'a, 'a> Visitor<'de> for V<'a> {
            type Value = RawArray<'a>;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("a JSON array")
            }
            fn visit_seq<S: SeqAccess<'de>>(self, mut s: S) -> Result<Self::Value, S::Error> {
                let mut v = Vec::new();
                while let Some(x) = s.next_element::<&'de RawValue>()? {
                    v.push(x);
                }
                Ok(RawArray(v))
            }
        }
        d.deserialize_seq(V(std::marker::PhantomData))
    }
}

pub fn obj<'a>(r: &'a RawValue) -> Option<RawObject<'a>> {
    if r.get().starts_with('{') {
        serde_json::from_str(r.get()).ok()
    } else {
        None
    }
}

pub fn arr<'a>(r: Option<&'a RawValue>) -> Option<RawArray<'a>> {
    let r = r?;
    if r.get().starts_with('[') {
        serde_json::from_str(r.get()).ok()
    } else {
        None
    }
}

pub fn is_null(r: Option<&RawValue>) -> bool {
    r.map(|x| x.get() == "null").unwrap_or(true)
}

/// Python `str(value)` of what ijson returns for this JSON value; None for null or missing.
pub fn raw_str<'a>(r: Option<&'a RawValue>) -> Option<Cow<'a, str>> {
    let t = r?.get();
    match t.as_bytes().first()? {
        b'"' => {
            let inner = &t[1..t.len() - 1];
            if inner.contains('\\') {
                Some(Cow::Owned(serde_json::from_str::<String>(t).unwrap_or_default()))
            } else {
                Some(Cow::Borrowed(inner))
            }
        }
        b'n' => None,
        b't' => Some(Cow::Borrowed("True")),
        b'f' => Some(Cow::Borrowed("False")),
        _ => Some(Cow::Borrowed(t)), // numbers keep their text; objects and arrays are rare here
    }
}

pub fn is_json_string(r: &RawValue) -> bool {
    r.get().starts_with('"')
}

// ------------------------------------------------------------------ numbers

/// Decimal(text) * 10000, rounded half-even, as parse.py's `to_e4`. Returns (value, inexact).
pub fn to_e4(text: &str) -> Option<(i64, bool)> {
    let t = text.trim();
    let (neg, body) = match t.as_bytes().first()? {
        b'-' => (true, &t[1..]),
        b'+' => (false, &t[1..]),
        _ => (false, t),
    };
    let (mant, exp) = match body.find(|c| c == 'e' || c == 'E') {
        Some(i) => (&body[..i], body[i + 1..].parse::<i32>().ok()?),
        None => (body, 0),
    };
    let (ip, fp) = match mant.find('.') {
        Some(i) => (&mant[..i], &mant[i + 1..]),
        None => (mant, ""),
    };
    if ip.is_empty() && fp.is_empty() {
        return None;
    }
    if !ip.bytes().all(|c| c.is_ascii_digit()) || !fp.bytes().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let digits: String = format!("{}{}", ip, fp);
    let digits = digits.trim_start_matches('0');
    let digits = if digits.is_empty() { "0" } else { digits };
    // value = digits * 10^(exp - len(fp)); e4 = digits * 10^(exp - len(fp) + 4)
    let shift = exp - fp.len() as i32 + 4;
    let mut d: i128 = 0;
    if digits.len() > 36 {
        return None;
    }
    for c in digits.bytes() {
        d = d * 10 + (c - b'0') as i128;
    }
    let (val, inexact) = if shift >= 0 {
        if shift > 30 {
            return None;
        }
        (d.checked_mul(10i128.pow(shift as u32))?, false)
    } else {
        let s = (-shift) as u32;
        if s > 36 {
            return Some((0, d != 0));
        }
        let p = 10i128.pow(s);
        let q = d / p;
        let r = d % p;
        let twice = r * 2;
        let q = if twice > p || (twice == p && q % 2 == 1) { q + 1 } else { q };
        (q, r != 0)
    };
    let val = if neg { -val } else { val };
    if val > i64::MAX as i128 || val < i64::MIN as i128 {
        return None;
    }
    Some((val as i64, inexact))
}

/// Python `int(x)` for an NPI as ijson returns it: strings strictly, numbers truncated.
pub fn py_int(r: &RawValue, flags: &mut Flags) -> Option<i64> {
    let t = r.get();
    if t.starts_with('"') {
        flags.add("npi_as_string");
        let s = raw_str(Some(r)).unwrap_or_default();
        let s = s.trim();
        let (neg, b) = match s.as_bytes().first() {
            Some(b'-') => (true, &s[1..]),
            Some(b'+') => (false, &s[1..]),
            _ => (false, s),
        };
        if b.is_empty() || !b.bytes().all(|c| c.is_ascii_digit()) {
            return None;
        }
        let v: i64 = b.parse().ok()?;
        return Some(if neg { -v } else { v });
    }
    match t.as_bytes().first()? {
        b't' => Some(1),
        b'f' => Some(0),
        b'n' | b'[' | b'{' => None,
        _ => {
            if t.bytes().all(|c| c.is_ascii_digit() || c == b'-') {
                t.parse().ok()
            } else {
                to_e4(t).map(|(v, _)| v / 10000) // Decimal -> int truncates toward zero
            }
        }
    }
}

// ------------------------------------------------------------------ flags

#[derive(Default, Clone)]
pub struct Flags(pub BTreeMap<String, u64>);

impl Flags {
    pub fn add(&mut self, k: &str) {
        *self.0.entry(k.to_string()).or_insert(0) += 1;
    }
    pub fn merge(&mut self, o: &Flags) {
        for (k, v) in &o.0 {
            *self.0.entry(k.clone()).or_insert(0) += v;
        }
    }
}

// ------------------------------------------------------------------ normalizers

pub struct Tin {
    pub ttype: Option<String>,
    pub value: Option<String>,
    pub raw: Option<String>,
    pub business_name: Option<String>,
}

pub fn norm_tin(tin: Option<&RawValue>, f: &mut Flags) -> Tin {
    let o = match tin.and_then(obj) {
        Some(o) => o,
        None => {
            f.add("tin_missing");
            return Tin { ttype: None, value: None, raw: None, business_name: None };
        }
    };
    let tt = raw_str(o.get("type")).map(|s| s.trim().to_lowercase()).filter(|s| !s.is_empty());
    let raw = raw_str(o.get("value")).map(|s| s.into_owned());
    let mut v = raw.as_deref().unwrap_or("").trim().replace('-', "");
    if let Some(r) = &raw {
        if &v != r {
            f.add("tin_trimmed");
        }
    }
    let digits = |s: &str| !s.is_empty() && s.bytes().all(|c| c.is_ascii_digit());
    if tt.as_deref() == Some("ein") && digits(&v) && v.len() == 8 {
        v = format!("0{}", v);
        f.add("ein_left_padded");
    }
    if tt.as_deref() == Some("ein") && !(digits(&v) && v.len() == 9) {
        f.add("ein_malformed");
    }
    if tt.as_deref() == Some("npi") && !(digits(&v) && v.len() == 10) {
        f.add("tin_npi_malformed");
    }
    let bn = raw_str(o.get("business_name")).map(|s| s.into_owned());
    Tin { ttype: tt, value: if v.is_empty() { None } else { Some(v) }, raw, business_name: bn }
}

/// Elements Python would iterate for `x or []`: list items, or the characters of a string.
fn py_iter<'a>(r: Option<&'a RawValue>) -> Vec<Cow<'a, str>> {
    let r = match r {
        Some(r) => r,
        None => return vec![],
    };
    let t = r.get();
    if t.starts_with('[') {
        arr(Some(r)).map(|a| a.0.into_iter().map(|x| raw_str(Some(x)).unwrap_or(Cow::Borrowed("None"))).collect())
            .unwrap_or_default()
    } else if t.starts_with('"') {
        raw_str(Some(r)).map(|s| s.chars().map(|c| Cow::Owned(c.to_string())).collect()).unwrap_or_default()
    } else {
        vec![]
    }
}

pub fn norm_npis(npi: Option<&RawValue>, f: &mut Flags) -> (Vec<i64>, bool) {
    let mut out: Vec<i64> = Vec::new();
    let mut tin_wide = false;
    let items = arr(npi).map(|a| a.0).unwrap_or_default();
    for x in &items {
        match py_int(x, f) {
            None => f.add("npi_unparseable"),
            Some(0) => tin_wide = true,
            Some(n) => {
                if !(1_000_000_000..=9_999_999_999).contains(&n) {
                    f.add("npi_out_of_range");
                }
                out.push(n);
            }
        }
    }
    out.sort_unstable();
    out.dedup();
    if tin_wide && !out.is_empty() {
        f.add("npi_zero_mixed_in");
    }
    if items.is_empty() {
        f.add("npi_list_empty");
    }
    (out, tin_wide)
}

pub fn norm_pos(codes: Option<&RawValue>, f: &mut Flags) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for c in py_iter(codes) {
        let mut s = c.trim().to_string();
        if s.len() == 1 && s.bytes().all(|b| b.is_ascii_digit()) {
            s = format!("0{}", s);
            f.add("pos_padded");
        }
        out.push(s);
    }
    out.sort();
    out.dedup();
    out
}

pub fn norm_mods(mods: Option<&RawValue>) -> Vec<String> {
    let mut v: Vec<String> = py_iter(mods).into_iter().map(|m| m.trim().to_string()).collect();
    v.sort();
    v.dedup();
    v
}

pub fn norm_billing_code(ctype: Option<&str>, code: Option<&RawValue>, f: &mut Flags) -> Option<String> {
    let s = raw_str(code)?;
    let mut t = s.trim().to_string();
    if t != s {
        f.add("billing_code_trimmed");
    }
    if ctype.map(|c| c.to_uppercase()) == Some("RC".into()) && !t.is_empty()
        && t.bytes().all(|c| c.is_ascii_digit()) && t.len() < 4 {
        t = format!("{:0>4}", t);
        f.add("revenue_code_padded");
    }
    if t.to_uppercase() == "CSTM" {
        t = "CSTM-00".into();
        f.add("cstm_normalized");
    }
    Some(t)
}

/// RC[a-b] ranges in additional_information, as parse.py's regex RC\[(\d{1,4})-(\d{1,4})\].
pub fn rc_ranges(info: Option<&str>) -> Vec<String> {
    let mut out = Vec::new();
    let s = match info {
        Some(s) => s.as_bytes(),
        None => return out,
    };
    let mut i = 0;
    while i + 3 <= s.len() {
        if &s[i..i + 3] == b"RC[" {
            let a0 = i + 3;
            let mut a1 = a0;
            while a1 < s.len() && s[a1].is_ascii_digit() {
                a1 += 1;
            }
            let la = a1 - a0;
            if (1..=4).contains(&la) && a1 < s.len() && s[a1] == b'-' {
                let b0 = a1 + 1;
                let mut b1 = b0;
                while b1 < s.len() && s[b1].is_ascii_digit() {
                    b1 += 1;
                }
                let lb = b1 - b0;
                if (1..=4).contains(&lb) && b1 < s.len() && s[b1] == b']' {
                    let a = std::str::from_utf8(&s[a0..a1]).unwrap();
                    let b = std::str::from_utf8(&s[b0..b1]).unwrap();
                    out.push(format!("{:0>4}-{:0>4}", a, b));
                    i = b1 + 1;
                    continue;
                }
            }
        }
        i += 1;
    }
    out
}

// ------------------------------------------------------------------ Python json.dumps

/// `json.dumps(value, default=str[, sort_keys])` as Python writes it for ijson values:
/// separators ", " and ": ", ASCII-only escapes, non-integer numbers as quoted strings.
pub fn py_dumps(v: &serde_json::Value, sort_keys: bool) -> String {
    let mut out = String::new();
    dump(v, sort_keys, &mut out);
    out
}

fn dump(v: &serde_json::Value, sk: bool, o: &mut String) {
    use serde_json::Value::*;
    match v {
        Null => o.push_str("null"),
        Bool(b) => o.push_str(if *b { "true" } else { "false" }),
        Number(n) => {
            let t = n.to_string();
            if t.contains('.') || t.contains('e') || t.contains('E') {
                dump_str(&py_decimal_str(&t), o);
            } else {
                o.push_str(&t);
            }
        }
        String(s) => dump_str(s, o),
        Array(a) => {
            o.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    o.push_str(", ");
                }
                dump(x, sk, o);
            }
            o.push(']');
        }
        Object(m) => {
            o.push('{');
            let mut keys: Vec<&std::string::String> = m.keys().collect();
            if sk {
                keys.sort();
            }
            for (i, k) in keys.iter().enumerate() {
                if i > 0 {
                    o.push_str(", ");
                }
                dump_str(k, o);
                o.push_str(": ");
                dump(&m[k.as_str()], sk, o);
            }
            o.push('}');
        }
    }
}

/// str(Decimal(text)) for ordinary decimal text (no exponent) is the text itself.
fn py_decimal_str(t: &str) -> String {
    t.to_string()
}

fn dump_str(s: &str, o: &mut String) {
    o.push('"');
    for ch in s.chars() {
        match ch {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            '\r' => o.push_str("\\r"),
            '\t' => o.push_str("\\t"),
            '\u{08}' => o.push_str("\\b"),
            '\u{0c}' => o.push_str("\\f"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                let cp = c as u32;
                if cp > 0xffff {
                    let v = cp - 0x10000;
                    o.push_str(&format!("\\u{:04x}\\u{:04x}", 0xd800 + (v >> 10), 0xdc00 + (v & 0x3ff)));
                } else {
                    o.push_str(&format!("\\u{:04x}", cp));
                }
            }
            c => o.push(c),
        }
    }
    o.push('"');
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn e4_matches_decimal_half_even() {
        assert_eq!(to_e4("73.31"), Some((733100, false)));
        assert_eq!(to_e4("0.01"), Some((100, false)));
        assert_eq!(to_e4("255"), Some((2550000, false)));
        assert_eq!(to_e4("1.00005"), Some((10000, true)));
        assert_eq!(to_e4("1.00015"), Some((10002, true)));
        assert_eq!(to_e4("1.000051"), Some((10001, true)));
        assert_eq!(to_e4("2.55E2"), Some((2550000, false)));
        assert_eq!(to_e4("-3.5"), Some((-35000, false)));
        assert_eq!(to_e4("abc"), None);
    }

    #[test]
    fn rc_ranges_like_python_regex() {
        assert_eq!(rc_ranges(Some("RC[0369-0369]")), vec!["0369-0369"]);
        assert_eq!(rc_ranges(Some("x RC[36-369] RC[12345-1] RC[1-2]")), vec!["0036-0369", "0001-0002"]);
    }

    #[test]
    fn py_dumps_matches_python() {
        let v: serde_json::Value = serde_json::from_str(r#"{"b": [1, 2.50, "é"], "a": null}"#).unwrap();
        assert_eq!(py_dumps(&v, true), r#"{"a": null, "b": [1, "2.50", "é"]}"#);
        assert_eq!(py_dumps(&v, false), r#"{"b": [1, "2.50", "é"], "a": null}"#);
    }
}
