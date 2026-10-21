//! Byte-level splitter: cuts the top-level `provider_references` and `in_network` arrays into
//! one record per element without parsing, and reports top-level scalar values (the header).
use std::io::Read;

pub enum Event<'a> {
    /// A top-level key began (in document order).
    Key(&'a [u8]),
    /// A top-level key with a scalar value: (key, raw JSON text of the value).
    Scalar(&'a [u8], &'a [u8]),
    /// One element of a top-level array: (array key, raw JSON text of the element).
    Record(&'a [u8], &'a [u8]),
}

#[derive(Default)]
struct State {
    depth: u32,
    in_str: bool,
    str_start: usize,
    last_str: Vec<u8>,
    key: Vec<u8>,
    val_start: Option<usize>, // start of a depth-1 value (scalar candidate)
    elem_start: Option<usize>,
    array_key: Option<Vec<u8>>,
}

const C_QUOTE: u8 = 1;
const C_OPEN: u8 = 2;
const C_CLOSE: u8 = 3;
const C_COLON: u8 = 4;
const C_COMMA: u8 = 5;

fn classes() -> [u8; 256] {
    let mut c = [0u8; 256];
    c[b'"' as usize] = C_QUOTE;
    c[b'{' as usize] = C_OPEN;
    c[b'[' as usize] = C_OPEN;
    c[b'}' as usize] = C_CLOSE;
    c[b']' as usize] = C_CLOSE;
    c[b':' as usize] = C_COLON;
    c[b',' as usize] = C_COMMA;
    c
}

/// Read the whole stream, calling `on` for every event. Returns total bytes read.
pub fn split<R: Read>(mut src: R, mut on: impl FnMut(Event)) -> std::io::Result<u64> {
    let class = classes();
    let mut buf: Vec<u8> = Vec::with_capacity(64 << 20);
    let mut chunk = vec![0u8; 16 << 20];
    let mut st = State::default();
    let mut total = 0u64;
    let mut pending_skip = 0usize;
    loop {
        let n0 = src.read(&mut chunk)?;
        if n0 == 0 {
            break;
        }
        total += n0 as u64;
        let mut i = buf.len() + pending_skip;
        buf.extend_from_slice(&chunk[..n0]);
        let n = buf.len();
        while i < n {
            if st.in_str {
                match memchr::memchr2(b'"', b'\\', &buf[i..n]) {
                    None => i = n,
                    Some(k) => {
                        let j = i + k;
                        if buf[j] == b'\\' {
                            i = j + 2;
                        } else {
                            st.in_str = false;
                            if st.depth == 1 {
                                st.last_str = buf[st.str_start..j].to_vec();
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
                C_QUOTE => {
                    st.in_str = true;
                    st.str_start = i + 1;
                }
                C_OPEN => {
                    st.depth += 1;
                    if st.depth == 2 {
                        st.val_start = None; // not a scalar
                        if c == b'[' {
                            st.array_key = Some(st.key.clone());
                        }
                    } else if st.depth == 3 && st.array_key.is_some() {
                        st.elem_start = Some(i);
                    }
                }
                C_CLOSE => {
                    if st.depth == 3 {
                        if let (Some(s0), Some(k)) = (st.elem_start.take(), st.array_key.as_ref()) {
                            on(Event::Record(k, &buf[s0..=i]));
                        }
                    } else if st.depth == 1 {
                        if let Some(v0) = st.val_start.take() {
                            on(Event::Scalar(&st.key, trim(&buf[v0..i])));
                        }
                    }
                    if st.depth == 2 && c == b']' {
                        st.array_key = None;
                    }
                    st.depth = st.depth.saturating_sub(1);
                }
                C_COLON => {
                    if st.depth == 1 {
                        st.key = std::mem::take(&mut st.last_str);
                        on(Event::Key(&st.key));
                        st.val_start = Some(i + 1);
                    }
                }
                _ => {
                    if st.depth == 1 {
                        if let Some(v0) = st.val_start.take() {
                            on(Event::Scalar(&st.key, trim(&buf[v0..i])));
                        }
                    }
                }
            }
            i += 1;
        }
        pending_skip = i - n;
        // keep the unfinished element, an unfinished depth-1 string, or an unfinished scalar
        let mut keep = st.elem_start.unwrap_or(n);
        if st.in_str && st.depth == 1 {
            keep = keep.min(st.str_start.saturating_sub(1));
        }
        if let Some(v0) = st.val_start {
            keep = keep.min(v0);
        }
        if keep > 0 {
            buf.drain(..keep);
            if let Some(s0) = st.elem_start.as_mut() {
                *s0 -= keep;
            }
            if st.in_str && st.depth == 1 {
                st.str_start -= keep;
            }
            if let Some(v0) = st.val_start.as_mut() {
                *v0 -= keep;
            }
        }
    }
    Ok(total)
}

fn trim(b: &[u8]) -> &[u8] {
    let s = b.iter().position(|c| !c.is_ascii_whitespace()).unwrap_or(b.len());
    let e = b.iter().rposition(|c| !c.is_ascii_whitespace()).map(|x| x + 1).unwrap_or(s);
    &b[s..e]
}
