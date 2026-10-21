"""The range reader must survive a CDN that answers ranges with whole files
(UHC, October 2026) and connections that die mid-body."""
import gzip
import http.server
import os
import threading

import pytest

from ticdata.net import HttpFile, RangeRefused, fetch_range, tail_fingerprint

DATA = gzip.compress(os.urandom(1 << 20) + b"x" * (3 << 20))


class Handler(http.server.BaseHTTPRequestHandler):
    seen: dict = {}
    mode = "flaky"

    def log_message(self, *a):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(DATA)))
        self.send_header("ETag", '"v1"')
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        rng = self.headers.get("Range")
        n = Handler.seen.get(rng, 0)
        Handler.seen[rng] = n + 1
        if Handler.mode == "never" or (rng and n == 0 and Handler.mode == "flaky"):
            # first request for each range: whole file with 200, like UHC's CDN
            self.send_response(200)
            self.send_header("Content-Length", str(len(DATA)))
            self.send_header("ETag", '"v1"')
            self.end_headers()
            try:
                self.wfile.write(DATA)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        a, b = rng.split("=")[1].split("-")
        a, b = int(a), int(b)
        body = DATA[a:b + 1]
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {a}-{b}/{len(DATA)}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", '"v1"')
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def server():
    Handler.seen = {}
    Handler.mode = "flaky"
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/file.gz"
    srv.shutdown()


def test_fetch_range_rejects_200_then_succeeds(server):
    got = fetch_range(server, 100, 199)
    assert got == DATA[100:200]


def test_fetch_range_gives_up_when_server_never_honors_ranges(server):
    Handler.mode = "never"
    with pytest.raises(RangeRefused):
        fetch_range(server, 0, 9, tries=2)


def test_tail_fingerprint_matches_gzip_trailer(server):
    crc, isize = tail_fingerprint(server, len(DATA))
    assert crc == int.from_bytes(DATA[-8:-4], "little")
    assert isize == (4 << 20) % (1 << 32)


def test_httpfile_streams_whole_file_through_gzip(server):
    f = HttpFile(server, window=256 << 10, prefetch=3)
    with gzip.open(f) as g:
        out = g.read()
    assert out[-10:] == b"x" * 10 and len(out) == 4 << 20
    assert f.stats.range_ignored >= 1  # the flaky first answers were seen and refused


def test_httpfile_random_access(server):
    f = HttpFile(server, window=64 << 10, prefetch=2)
    f.seek(len(DATA) - 100)
    assert f.read(100) == DATA[-100:]
    f.seek(12345)
    assert f.read(10) == DATA[12345:12355]
