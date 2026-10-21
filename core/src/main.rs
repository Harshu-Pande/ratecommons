//! ticcore: streaming record splitter for Transparency in Coverage files (experiment E7).
//!
//! `ticcore scan <file> [threads]` decompresses a gzip (any number of members) or plain JSON
//! file on one thread, cuts the top-level `provider_references` and `in_network` arrays into
//! records at the byte level (no full parse), and hands each record to worker threads that
//! parse it with serde_json and hash it. Prints JSON timings so we can see whether parsing
//! keeps up with decompression.
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

mod map;
mod model;
mod split;
mod writer;

use crossbeam_channel::bounded;
use std::fs::File;
use std::io::{BufReader, Read};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

#[derive(Default)]
struct Splitter {
    depth: u32,
    in_str: bool,

    str_start: usize,
    last_str: Vec<u8>,
    key: Vec<u8>,
    elem_start: Option<usize>,
    array_key: Option<Vec<u8>>,
}

enum Rec {
    Item(Vec<u8>, bool), // (bytes, is_in_network)
}

fn open(path: &str) -> Box<dyn Read + Send> {
    let mut f = File::open(path).expect("open");
    let mut magic = [0u8; 2];
    f.read_exact(&mut magic).expect("read magic");
    let f = File::open(path).expect("reopen");
    let r = BufReader::with_capacity(1 << 22, f);
    if magic == [0x1f, 0x8b] {
        Box::new(flate2::read::MultiGzDecoder::new(r))
    } else {
        Box::new(r)
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() >= 4 && args[1] == "map" {
        let threads: usize = args.get(4).and_then(|s| s.parse().ok()).unwrap_or_else(|| {
            std::thread::available_parallelism().map(|n| n.get().saturating_sub(1).max(1)).unwrap_or(2)
        });
        let source: serde_json::Value = args.get(5).filter(|s| !s.starts_with("--")).and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or(serde_json::json!({}));
        let seen = args.iter().position(|a| a == "--seen-blocks").and_then(|i| args.get(i + 1)).cloned();
        let rcache = args.iter().position(|a| a == "--record-cache").and_then(|i| args.get(i + 1)).cloned();
        let meta = map::map_file(&args[2], &args[3], threads, source, seen.as_deref(), rcache.as_deref());
        println!("{}", serde_json::to_string(&meta).unwrap());
        return;
    }
    if args.len() >= 3 && args[1] == "inflate" {
        let t0 = Instant::now();
        let mut src = open(&args[2]);
        let mut chunk = vec![0u8; 16 << 20];
        let mut total = 0u64;
        loop {
            let n = src.read(&mut chunk).expect("read");
            if n == 0 { break; }
            total += n as u64;
        }
        let dt = t0.elapsed().as_secs_f64();
        println!("{{\"json_bytes\":{},\"seconds\":{:.1},\"json_gb_per_s\":{:.3}}}", total, dt, total as f64 / dt / 1e9);
        return;
    }
    if args.len() < 3 || args[1] != "scan" {
        eprintln!("usage: ticcore scan <file> [threads] [mode: split|parse]");
        std::process::exit(2);
    }
    let path = args[2].clone();
    let threads: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(3);
    let parse = args.get(4).map(|s| s != "split").unwrap_or(true);

    let (tx, rx) = bounded::<Rec>(64);
    let parsed_bytes = Arc::new(AtomicU64::new(0));
    let rates = Arc::new(AtomicU64::new(0));
    let mut workers = Vec::new();
    for _ in 0..threads {
        let rx = rx.clone();
        let pb = parsed_bytes.clone();
        let rt = rates.clone();
        workers.push(std::thread::spawn(move || {
            let mut acc: u64 = 0;
            for Rec::Item(bytes, inn) in rx {
                acc ^= xxhash_rust::xxh3::xxh3_64(&bytes);
                if parse {
                    let v: serde_json::Value = serde_json::from_slice(&bytes).expect("record is valid JSON");
                    if inn {
                        if let Some(a) = v.get("negotiated_rates").and_then(|x| x.as_array()) {
                            rt.fetch_add(a.len() as u64, Ordering::Relaxed);
                        }
                    }
                }
                pb.fetch_add(bytes.len() as u64, Ordering::Relaxed);
            }
            acc
        }));
    }

    let t0 = Instant::now();
    // decompression on its own thread, so splitting overlaps it
    let (ctx, crx) = bounded::<Vec<u8>>(4);
    let inflater = std::thread::spawn(move || {
        let mut src = open(&path);
        loop {
            let mut chunk = vec![0u8; 16 << 20];
            let mut filled = 0;
            while filled < chunk.len() {
                let n = src.read(&mut chunk[filled..]).expect("read");
                if n == 0 { break; }
                filled += n;
            }
            if filled == 0 { break; }
            chunk.truncate(filled);
            if ctx.send(chunk).is_err() { break; }
        }
    });
    // byte classes outside strings: 1 = quote, 2 = open, 3 = close, 4 = colon
    let mut class = [0u8; 256];
    class[b'"' as usize] = 1;
    class[b'{' as usize] = 2;
    class[b'[' as usize] = 2;
    class[b'}' as usize] = 3;
    class[b']' as usize] = 3;
    class[b':' as usize] = 4;
    let mut buf: Vec<u8> = Vec::with_capacity(64 << 20);
    let mut sp = Splitter::default();
    let (mut total, mut refs, mut items, mut max_rec) = (0u64, 0u64, 0u64, 0usize);
    let mut header_keys: Vec<String> = Vec::new();
    let mut pending_skip = 0usize; // an escaped byte that falls at the start of the next chunk
    for chunk in crx {
        total += chunk.len() as u64;
        let mut i = buf.len() + pending_skip;
        buf.extend_from_slice(&chunk);
        let n = buf.len();
        while i < n {
            if sp.in_str {
                // jump to the next quote or backslash
                match memchr::memchr2(b'"', b'\\', &buf[i..n]) {
                    None => { i = n; }
                    Some(k) => {
                        let j = i + k;
                        if buf[j] == b'\\' {
                            i = j + 2; // skip the escaped byte (may run past n: handled below)
                        } else {
                            sp.in_str = false;
                            if sp.depth == 1 {
                                sp.last_str = buf[sp.str_start..j].to_vec();
                            }
                            i = j + 1;
                        }
                    }
                }
                continue;
            }
            let c = buf[i];
            match class[c as usize] {
                0 => {}
                1 => { sp.in_str = true; sp.str_start = i + 1; }
                2 => {
                    sp.depth += 1;
                    if sp.depth == 2 && c == b'[' {
                        sp.array_key = Some(sp.key.clone());
                    } else if sp.depth == 3 && sp.array_key.is_some() {
                        sp.elem_start = Some(i);
                    }
                }
                3 => {
                    if sp.depth == 3 {
                        if let (Some(s0), Some(k)) = (sp.elem_start.take(), sp.array_key.as_ref()) {
                            let inn = k.as_slice() == b"in_network";
                            if inn || k.as_slice() == b"provider_references" {
                                let rec = buf[s0..=i].to_vec();
                                max_rec = max_rec.max(rec.len());
                                if inn { items += 1 } else { refs += 1 }
                                tx.send(Rec::Item(rec, inn)).expect("send");
                            }
                        }
                    }
                    if sp.depth == 2 && c == b']' {
                        sp.array_key = None;
                    }
                    sp.depth -= 1;
                }
                _ => {
                    if sp.depth == 1 {
                        sp.key = std::mem::take(&mut sp.last_str);
                        header_keys.push(String::from_utf8_lossy(&sp.key).into_owned());
                    }
                }
            }
            i += 1;
        }
        pending_skip = i - n; // 1 when a backslash was the last byte of the buffer
        // keep only the unfinished element, or an unfinished top-level string
        let mut keep = sp.elem_start.unwrap_or(n);
        if sp.in_str && sp.depth == 1 {
            keep = keep.min(sp.str_start.saturating_sub(1));
        }
        if keep > 0 {
            buf.drain(..keep);
            if let Some(s0) = sp.elem_start.as_mut() { *s0 -= keep; }
            if sp.in_str && sp.depth == 1 { sp.str_start -= keep; }
        }
    }
    inflater.join().unwrap();
    let t_split = t0.elapsed().as_secs_f64();
    drop(tx);
    let mut acc = 0u64;
    for w in workers {
        acc ^= w.join().unwrap();
    }
    let t_all = t0.elapsed().as_secs_f64();
    println!(
        "{{\"json_bytes\":{},\"provider_references\":{},\"in_network\":{},\"negotiated_rates\":{},\"max_record_bytes\":{},\"split_seconds\":{:.1},\"total_seconds\":{:.1},\"json_gb_per_s\":{:.3},\"threads\":{},\"parse\":{},\"top_level_keys\":{:?},\"xor_hash\":\"{:016x}\"}}",
        total, refs, items, rates.load(Ordering::Relaxed), max_rec, t_split, t_all,
        total as f64 / t_all / 1e9, threads, parse, header_keys, acc
    );
}
