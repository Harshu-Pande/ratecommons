"""HTTP primitives that never trust a status line.

Measured on the October 2026 postings (design doc, "Downloading reliably" tab):
UHC's CDN answers ~85% of first byte-range requests with `200` and the whole
15 GB file. Everything here therefore insists on `206` plus a matching
`Content-Range`, and closes the connection without reading a body otherwise.
"""
from __future__ import annotations

import io
import random
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

USER_AGENT = (
    "ticdata/0.1 (public-good price transparency crawler; "
    "+https://github.com/Harshu-Pande/ratecommons)"
)
_CR = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")


class RangeRefused(Exception):
    """The server would not give us the bytes we asked for."""


class ObjectChanged(Exception):
    """The remote file was replaced while we were reading it."""


class Gone(Exception):
    """403/404/410: the link expired or the file is gone; re-resolve from the index."""


def new_session(pool: int = 16) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    adapter = requests.adapters.HTTPAdapter(pool_connections=pool, pool_maxsize=pool)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


@dataclass
class Stats:
    requests: int = 0
    range_ignored: int = 0  # server answered 200 to a range request
    retries: int = 0
    bytes: int = 0
    errors: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "requests": self.requests,
            "range_ignored": self.range_ignored,
            "retries": self.retries,
            "bytes": self.bytes,
            "errors": self.errors[-5:],
        }


@dataclass
class Remote:
    url: str  # final URL after redirects
    size: int
    etag: str | None
    last_modified: str | None
    accept_ranges: str | None


def resolve(url: str, s: requests.Session | None = None, timeout: float = 30) -> Remote:
    """Follow redirects by hand, then learn size and identity from HEAD.

    UHC's download URLs answer 302 to a SAS URL on mrfstorage.uhc.com.
    """
    s = s or new_session()
    cur = url
    for _ in range(6):
        r = s.head(cur, allow_redirects=False, timeout=timeout)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            cur = requests.compat.urljoin(cur, r.headers["Location"])
            continue
        if r.status_code == 405:  # HEAD not allowed: learn size from a 1-byte range
            return _resolve_by_range(cur, s, timeout)
        if r.status_code in (403, 404, 410):
            raise Gone(f"{r.status_code} for {cur[:120]}")
        r.raise_for_status()
        size = int(r.headers.get("Content-Length", "-1"))
        if size < 0:
            return _resolve_by_range(cur, s, timeout)
        return Remote(cur, size, r.headers.get("ETag"), r.headers.get("Last-Modified"),
                      r.headers.get("Accept-Ranges"))
    raise RangeRefused(f"too many redirects for {url[:120]}")


def _resolve_by_range(url: str, s: requests.Session, timeout: float) -> Remote:
    r = s.get(url, headers={"Range": "bytes=0-0"}, stream=True, timeout=timeout)
    try:
        m = _CR.match(r.headers.get("Content-Range", ""))
        if r.status_code != 206 or not m or m.group(3) == "*":
            raise RangeRefused(f"cannot learn size of {url[:120]} (status {r.status_code})")
        return Remote(url, int(m.group(3)), r.headers.get("ETag"), r.headers.get("Last-Modified"),
                      r.headers.get("Accept-Ranges"))
    finally:
        r.close()


def fetch_range(url: str, start: int, end: int, s: requests.Session | None = None, *,
                total: int | None = None, tries: int = 6, timeout=(10, 60),
                stats: Stats | None = None) -> bytes:
    """Return exactly bytes [start, end] (inclusive) or raise.

    A `200` answer is never read: the connection is closed at once, so a
    misbehaving CDN cannot make us pull a 15 GB body. If `total` is given, a
    `206` whose Content-Range reports a different total size means the object
    was replaced, and we stop.

    No `If-Range`: Aetna's BunnyCDN and its Google Cloud origin report different
    ETags for the same object, and an `If-Range` the origin does not recognise
    turns every range request into a full-file `200` (seen October 21, 2026).
    """
    s = s or new_session()
    stats = stats or Stats()
    want = end - start + 1
    last_err = "no attempt"
    for attempt in range(tries):
        if attempt:
            stats.retries += 1
            time.sleep(min(30.0, 0.5 * 2 ** attempt) * (0.5 + random.random()))
        headers = {"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
        stats.requests += 1
        try:
            r = s.get(url, headers=headers, stream=True, timeout=timeout)
        except requests.RequestException as e:  # network trouble: retry
            last_err = repr(e)[:200]
            continue
        try:
            if r.status_code == 206:
                m = _CR.match(r.headers.get("Content-Range", ""))
                if not m or int(m.group(1)) != start or int(m.group(2)) != end:
                    last_err = f"bad Content-Range {r.headers.get('Content-Range')!r}"
                    continue
                if total is not None and m.group(3) != "*" and int(m.group(3)) != total:
                    raise ObjectChanged(f"size {total} -> {m.group(3)}")
                data = r.raw.read(want, decode_content=False)
                if len(data) != want:
                    last_err = f"short body {len(data)}/{want}"
                    continue
                stats.bytes += want
                return data
            if r.status_code == 200:
                stats.range_ignored += 1
                last_err = "200 instead of 206"
                continue
            if r.status_code in (403, 404, 410):
                raise Gone(f"{r.status_code} for {url[:120]}")
            if r.status_code == 416:
                raise RangeRefused(f"416 for bytes={start}-{end}")
            last_err = f"status {r.status_code}"
        except requests.RequestException as e:
            last_err = repr(e)[:200]
        finally:
            r.close()
    stats.errors.append(last_err)
    raise RangeRefused(f"bytes={start}-{end} of {url[:100]}: {last_err}")


class HttpFile(io.RawIOBase):
    """A seekable, read-only file over HTTP ranges that survives dropped connections.

    Reads are served from fixed-size windows. A dropped connection costs one
    window, retried on its own; whatever sits on top (zlib, rapidgzip, a JSON
    splitter) only ever sees a slower read. Sequential reads trigger prefetch
    of the next windows in parallel.
    """

    def __init__(self, url: str, *, window: int = 16 << 20, prefetch: int = 4,
                 cache_windows: int = 12, session: requests.Session | None = None,
                 remote: Remote | None = None):
        super().__init__()
        self._s = session or new_session(pool=prefetch + 4)
        self.remote = remote or resolve(url, self._s)
        self.size = self.remote.size
        self.window = window
        self.prefetch = prefetch
        self.cache_windows = max(cache_windows, prefetch + 2)
        self.stats = Stats()
        self._pos = 0
        self._lock = threading.RLock()
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self._inflight: dict[int, Future] = {}
        self._pool = ThreadPoolExecutor(max_workers=max(1, prefetch))
        self._last_idx = -1

    # io.RawIOBase interface -------------------------------------------------
    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        with self._lock:
            if whence == io.SEEK_SET:
                self._pos = offset
            elif whence == io.SEEK_CUR:
                self._pos += offset
            elif whence == io.SEEK_END:
                self._pos = self.size + offset
            self._pos = max(0, self._pos)
            return self._pos

    def readinto(self, b) -> int:
        with self._lock:
            pos = self._pos
        if pos >= self.size:
            return 0
        n = min(len(b), self.size - pos)
        out = memoryview(b)
        done = 0
        while done < n:
            idx = (pos + done) // self.window
            win = self._get(idx)
            off = (pos + done) - idx * self.window
            take = min(n - done, len(win) - off)
            out[done:done + take] = win[off:off + take]
            done += take
        with self._lock:
            self._pos = pos + done
        return done

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        super().close()

    # internals ----------------------------------------------------------------
    def _fetch(self, idx: int) -> bytes:
        start = idx * self.window
        end = min(self.size, start + self.window) - 1
        return fetch_range(self.remote.url, start, end, self._s, total=self.size,
                           stats=self.stats)

    def _get(self, idx: int) -> bytes:
        with self._lock:
            if idx in self._cache:
                self._cache.move_to_end(idx)
                data = self._cache[idx]
                fut = None
            else:
                fut = self._inflight.get(idx)
                if fut is None:
                    fut = self._pool.submit(self._fetch, idx)
                    self._inflight[idx] = fut
                data = None
            sequential = idx == self._last_idx + 1 or idx == self._last_idx
            self._last_idx = idx
            if sequential:
                last = (self.size - 1) // self.window
                for j in range(idx + 1, min(last, idx + self.prefetch) + 1):
                    if j not in self._cache and j not in self._inflight:
                        self._inflight[j] = self._pool.submit(self._fetch, j)
        if data is not None:
            return data
        data = fut.result()
        with self._lock:
            self._inflight.pop(idx, None)
            self._cache[idx] = data
            while len(self._cache) > self.cache_windows:
                self._cache.popitem(last=False)
        return data


def tail_fingerprint(url: str, size: int, s: requests.Session | None = None,
                     stats: Stats | None = None) -> tuple[int, int]:
    """CRC32 and length (mod 2**32) of the file's last gzip member: its last 8 bytes."""
    tail = fetch_range(url, size - 8, size - 1, s, total=size, stats=stats)
    return int.from_bytes(tail[:4], "little"), int.from_bytes(tail[4:], "little")
