"""A broken single GET resumes from the bytes on disk (identity._fetch)."""
import http.server
import threading

from ticdata.identity import _fetch
from ticdata.net import new_session

DATA = bytes(range(256)) * 120_000  # ~30 MB: more than one 8 MB read chunk, below the ranged-download size


class Flaky(http.server.BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def do_HEAD(self):
        self.send_response(405)
        self.end_headers()

    def do_GET(self):
        rng = self.headers.get("Range")
        Flaky.calls.append(rng)
        if rng:
            a, _, b = rng.split("=")[1].partition("-")
            start, end = int(a), int(b) if b else len(DATA) - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(DATA)}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self.wfile.write(DATA[start:end + 1])
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(DATA)))
        self.end_headers()
        self.wfile.write(DATA[: len(DATA) // 3])  # then drop the connection
        self.wfile.flush()
        self.connection.shutdown(2)


def test_broken_download_resumes(tmp_path):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Flaky)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        res = _fetch(f"http://127.0.0.1:{srv.server_address[1]}/f.json.gz", str(tmp_path / "f"), new_session())
    finally:
        srv.shutdown()
    assert (tmp_path / "f").read_bytes() == DATA
    assert res["resumes"] == 1 and Flaky.calls[-1].startswith("bytes=") and Flaky.calls[-1] != "bytes=0-0"
