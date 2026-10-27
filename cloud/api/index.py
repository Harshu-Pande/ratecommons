"""RateCommons cloud API: JSON tools (/api/tool/<name>), MCP over streamable HTTP (/mcp), and the web UI (/)."""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response  # noqa: E402

import _rc as E  # noqa: E402
from _tooldocs import DOCS  # noqa: E402

TOOLS = {f.__name__: f for f in (E.provider_rates, E.lookup_rates, E.market_distribution, E.compare_providers,
                                  E.benchmark_provider, E.network_breadth, E.provider_networks, E.find_plans,
                                  E.list_products, E.search_providers, E.code_info, E.medicare_rate, E.data_status)}
INT_ARGS = {"limit"}

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
    return fn(**kw)


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
        res = _call(name, body)
        out = {"ok": True, "rows": _json(res)} if isinstance(res, list) else {"ok": True, **_json(res)}
        out["seconds"] = round(time.time() - t, 2)
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "seconds": round(time.time() - t, 2)})


# ---------------------------------------------------------------- MCP (streamable HTTP, stateless, JSON responses)

SERVER = {"name": "RateCommons", "version": "2.0"}


def _rpc(msg: dict):
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
            res = _json(_call(name, p.get("arguments") or {}))
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
        out = [r for r in (_rpc(m) for m in body) if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    r = _rpc(body)
    return JSONResponse(r) if r is not None else Response(status_code=202)


@app.get("/mcp")
@app.get("/mcp/")
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})


@app.get("/api/health")
def health():
    return {"ok": True, "data": E.BASE}


@app.get("/", response_class=HTMLResponse)
def index():
    from _ui import HTML

    return HTML
