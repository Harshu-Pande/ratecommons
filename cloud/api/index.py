"""RateCommons cloud API: JSON tools (/api/tool/<name>), MCP over streamable HTTP (/mcp), and the web UI (/)."""
from __future__ import annotations

import asyncio
import inspect
import json
import threading
from collections import OrderedDict
import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402

import _rc as E  # noqa: E402
from _tooldocs import DOCS  # noqa: E402

TOOLS = {f.__name__: f for f in (E.provider_rates, E.rank_providers, E.lookup_rates, E.market_distribution, E.compare_providers,
                                  E.benchmark_provider, E.network_breadth, E.provider_networks, E.find_plans,
                                  E.list_products, E.search_providers, E.code_info, E.medicare_rate, E.data_status, E.run_sql)}
INT_ARGS = {"limit", "min_codes", "max_rows"}

app = FastAPI(title="RateCommons")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _schema(name: str) -> dict:
    fn = TOOLS[name]
    doc = DOCS.get(name, "")
    args, cur = {}, None
    for line in (doc.split("Args:", 1)[1] if "Args:" in doc else "").splitlines():
        m = re.match(r"^\s{2,6}(\w+): (.*)", line)
        if m and m.group(1) in inspect.signature(fn).parameters:
            cur = m.group(1)
            args[cur] = m.group(2).strip()
        elif cur and line.strip() and not line.strip().startswith("Returns"):
            args[cur] += " " + line.strip()
        elif line.strip().startswith("Returns"):
            cur = None
    props, req = {}, []
    for k, v in inspect.signature(fn).parameters.items():
        props[k] = {"type": "integer" if k in INT_ARGS else "string", "description": args.get(k, "")}
        if v.default is inspect._empty:
            req.append(k)
        else:
            props[k]["default"] = v.default
    return {"name": name, "description": doc.split("Args:")[0].strip(),
            "inputSchema": {"type": "object", "properties": props, "required": req}}


def _call(name: str, args: dict):
    fn = TOOLS[name]
    sig = inspect.signature(fn)
    kw = {k: (int(v) if k in INT_ARGS and v not in (None, "") else v) for k, v in (args or {}).items() if k in sig.parameters}
    res = fn(**kw)
    notes = E.coverage_notes(kw) if name not in ("data_status", "medicare_rate", "code_info") else []
    if notes:  # common-services packs: never let a missing code read as "no published rate"
        if isinstance(res, list):
            res = {"rows": res, "notes": notes}
        elif isinstance(res, dict):
            res = {**res, "notes": list(res.get("notes") or []) + notes}
    return res


# Identical questions are answered from memory: the data only changes when a pack is rebuilt (the server restarts
# then). AI assistants and the website often repeat a call (retries, re-renders, two tools needing the same rows).
_RCACHE: "OrderedDict[str, tuple[float, object]]" = OrderedDict()
_RCACHE_N = int(os.environ.get("RC_RESULT_CACHE", "512"))
_RCACHE_TTL = float(os.environ.get("RC_RESULT_TTL", "21600"))
_rlock = threading.Lock()
# Queries run in worker threads, at most RC_CONCURRENCY at a time; the rest wait their turn instead of all slowing
# down together (a 2-vCPU server serves 3 at once better than 10).
_SLOTS = threading.BoundedSemaphore(int(os.environ.get("RC_CONCURRENCY", "3")))


def _cached_call(name: str, args: dict):
    key = name + json.dumps(args or {}, sort_keys=True, default=str)
    now = time.time()
    with _rlock:
        hit = _RCACHE.get(key)
        if hit and now - hit[0] < _RCACHE_TTL:
            _RCACHE.move_to_end(key)
            return hit[1]
    with _SLOTS:
        res = _json(_call(name, args))
    if len(json.dumps(res, default=str)) < 4_000_000:
        with _rlock:
            _RCACHE[key] = (now, res)
            while len(_RCACHE) > _RCACHE_N:
                _RCACHE.popitem(last=False)
    return res


async def _acall(name: str, args: dict):
    return await run_in_threadpool(_cached_call, name, args)


def _json(o):
    return json.loads(json.dumps(o, default=lambda x: x.hex() if isinstance(x, (bytes, bytearray)) else str(x)))


@app.get("/api/tools")
def api_tools():
    return [_schema(n) for n in TOOLS]


@app.post("/api/tool/{name}")
async def api_tool(name: str, request: Request):
    if name not in TOOLS:
        return JSONResponse({"ok": False, "error": f"unknown tool {name}"}, 404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    t = time.time()
    try:
        res = await _acall(name, body)
        out = {"ok": True, "rows": res} if isinstance(res, list) else {"ok": True, **res}
        out["seconds"] = round(time.time() - t, 2)
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "seconds": round(time.time() - t, 2)})


# ---------------------------------------------------------------- MCP (streamable HTTP, stateless, JSON responses)

SERVER = {"name": "RateCommons", "version": "2.0"}


async def _arpc(msg: dict):
    """tools/call runs in a worker thread (cached, limited); everything else is instant."""
    if msg.get("method") == "tools/call" and msg.get("id") is not None:
        p = msg.get("params") or {}
        if p.get("name") in TOOLS:
            try:
                res = await _acall(p.get("name"), p.get("arguments") or {})
                return _rpc(msg, res)
            except Exception as e:
                return {"jsonrpc": "2.0", "id": msg.get("id"),
                        "result": {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}}
    return _rpc(msg)


def _rpc(msg: dict, done=None):
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:  # notification
        return None
    if method == "initialize":
        ver = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": ver, "serverInfo": SERVER,
                                                         "capabilities": {"tools": {"listChanged": False}}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [_schema(n) for n in TOOLS]}}
    if method == "tools/call":
        p = msg.get("params") or {}
        name = p.get("name")
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        try:
            res = done if done is not None else _json(_call(name, p.get("arguments") or {}))
            text = json.dumps(res, separators=(",", ":"))
            if len(text) > 120_000:
                text = text[:120_000] + " ...(truncated; narrow the query)"
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


@app.post("/mcp")
@app.post("/mcp/")
@app.post("/gradio_api/mcp/")  # the old Mac app's MCP address keeps working
async def mcp(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}, 400)
    if isinstance(body, list):
        out = [r for r in await asyncio.gather(*(_arpc(m) for m in body)) if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    r = await _arpc(body)
    return JSONResponse(r) if r is not None else Response(status_code=202)


@app.get("/mcp")
@app.get("/mcp/")
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})


@app.get("/api/health")
def health():
    return {"ok": True, "data": E.BASE, "warm": sorted(E._meta), "cached_answers": len(_RCACHE)}


@app.get("/api/status")
async def status():
    """data_status for the website, cacheable by any CDN (it only changes when a pack is rebuilt)."""
    res = await _acall("data_status", {})
    return JSONResponse({"ok": True, **res}, headers={"Cache-Control": "public, max-age=300, s-maxage=3600, "
                                                                     "stale-while-revalidate=86400"})


def _keep_fresh():
    """Persistent server: load every payer's metadata at start, then check every RC_REFRESH_SECONDS whether the
    pipeline published new packs; if so drop the stale files and remembered answers and load the new metadata."""
    E.payers_loaded()
    E.refresh_if_changed()  # records the shared files' identity
    while True:
        time.sleep(float(os.environ.get("RC_REFRESH_SECONDS", "900")))
        try:
            if E.refresh_if_changed():
                with _rlock:
                    _RCACHE.clear()
                E.payers_loaded()
        except Exception:
            traceback.print_exc()


if os.environ.get("RC_WARM") == "1":
    threading.Thread(target=_keep_fresh, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def index():
    from _ui import HTML

    return HTML
