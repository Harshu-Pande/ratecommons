"""Vercel entry: loads the app code from github.com/Harshu-Pande/ratecommons cloud/api at a pinned commit (RC_CODE_REF)."""
import importlib.util
import json
import os
import sys

import httpx

REF = os.environ.get("RC_CODE_REF", "main")
D = f"/tmp/rc-code/{REF}"
if not os.path.exists(f"{D}/.ok"):
    os.makedirs(D, exist_ok=True)
    for f in ("index.py", "_rc.py", "_tooldocs.py", "_ui.py"):
        r = httpx.get(f"https://raw.githubusercontent.com/Harshu-Pande/ratecommons/{REF}/cloud/api/{f}", timeout=30)
        r.raise_for_status()
        open(f"{D}/{f}", "wb").write(r.content)
    open(f"{D}/.ok", "w").write("ok")
sys.path.insert(0, D)
spec = importlib.util.spec_from_file_location("rc_app", f"{D}/index.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
_inner = mod.app


async def app(scope, receive, send):
    if scope["type"] == "http":
        path = scope.get("path", "")
        if path == "/__debug":
            body = json.dumps({"path": path, "root_path": scope.get("root_path"), "raw": str(scope.get("raw_path")), "ref": REF}).encode()
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        for pre in ("/api/index.py", "/api/index"):
            if path.startswith(pre):
                scope = dict(scope, path=path[len(pre):] or "/")
                break
    await _inner(scope, receive, send)
