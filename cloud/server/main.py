"""Persistent-server entry for RateCommons (same API code as the Vercel function in cloud/api).

Routes are identical to ratecommons.org's: /api/tool/<name>, /api/tools, /api/status, /api/health, /mcp (and the old
/gradio_api/mcp/). Tuning comes from environment variables (see Dockerfile): a big disk cache, memory for one-pass
queries, and a cap on how many questions run at once.

When RC_SITE_DIR holds the built website (carecompass/dist), this server also serves the whole site: the pages, the
patient tool's price files under /data/shop/* (streamed from the Hugging Face bucket and cached on disk, so a visitor's
browser only ever talks to our own host), and the same security headers as carecompass/vercel.json. That lets
ratecommons.org point straight here if Vercel is unavailable.
"""
import os
import re
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))

import httpx  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402

from index import app  # noqa: E402

SITE = os.environ.get("RC_SITE_DIR", "/app/site")
SHOP = os.environ.get("RC_SHOP_URL", "https://huggingface.co/buckets/ratecommons/work/resolve/shop/v1").rstrip("/")
SHOP_CACHE = os.path.join(os.environ.get("RC_CACHE", "/tmp/rc-cache"), "_shop")
SAFE = re.compile(r"^(?:[a-z0-9_-]+/)*[a-zA-Z0-9_.-]+\.json$")
CSP = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; img-src 'self' data: blob: "
       "https://server.arcgisonline.com; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")
SEC = {"Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
       "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), interest-cohort=(), browsing-topics=()",
       "Strict-Transport-Security": "max-age=63072000; includeSubDomains"}
_http = httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, connect=15.0),
                     headers={"User-Agent": "ratecommons-site"})
_shop_lock = threading.Lock()


def _shop_file(p: str) -> str | None:
    dest = os.path.join(SHOP_CACHE, p)
    if os.path.exists(dest):
        return dest
    r = _http.get(f"{SHOP}/{p}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = f"{dest}.{threading.get_ident()}.part"
    with open(tmp, "wb") as f:
        f.write(r.content)
    os.replace(tmp, dest)
    return dest


if os.path.isdir(SITE):
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/"]  # "/" is the website here

    @app.get("/data/shop/{p:path}")
    async def shop(p: str):
        if not SAFE.match(p) or ".." in p:
            return Response("Not found", 404)
        try:
            f = await run_in_threadpool(_shop_file, p)
        except Exception:
            return Response("Upstream unavailable", 502, headers={"Cache-Control": "no-store"})
        if not f:
            return Response("null", 404, media_type="application/json", headers={"Cache-Control": "public, max-age=3600"})
        return FileResponse(f, media_type="application/json; charset=utf-8",
                            headers={"Cache-Control": "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800", **SEC})

    @app.get("/{path:path}")
    async def site(path: str, request: Request):
        full = os.path.realpath(os.path.join(SITE, path))
        if path and full.startswith(os.path.realpath(SITE) + os.sep) and os.path.isfile(full):
            cc = ("public, max-age=31536000, immutable" if path.startswith("assets/") else
                  "public, max-age=2592000" if path.startswith("ocr/") else "public, max-age=300")
            return FileResponse(full, headers={"Cache-Control": cc, **SEC})
        if path.startswith(("api/", "assets/", "ocr/")):
            return JSONResponse({"error": "not found"}, 404)
        return FileResponse(os.path.join(SITE, "index.html"), headers={"Cache-Control": "no-cache", **SEC})
