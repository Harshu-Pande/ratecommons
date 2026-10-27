"""Vercel entry (deployed as api/index.py): loads the app code from this repo at a pinned commit (RC_CODE_REF),
so a release is a one-line environment change plus a redeploy. Source: cloud/api/ in Harshu-Pande/ratecommons."""
import importlib.util
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
app = mod.app
