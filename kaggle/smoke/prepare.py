"""Write kernel-metadata.json and script.py for the Kaggle smoke kernel.

Usage: python kaggle/smoke/prepare.py <kaggle_username> <pip spec>
  pip spec: "owner/repo" (installs from GitHub main) or any pip-installable URL,
  e.g. a wheel published to the ops dataset on Hugging Face.
Kaggle only uploads the code file, so the script installs the package itself.
"""
import json
import sys
from pathlib import Path

user, spec = sys.argv[1], sys.argv[2]
if "://" not in spec and spec.count("/") == 1:
    spec = f"git+https://github.com/{spec}@main"
here = Path(__file__).parent

(here / "kernel-metadata.json").write_text(json.dumps({
    "id": f"{user}/ratecommons-smoke",
    "title": "ratecommons-smoke",
    "code_file": "script.py",
    "language": "python",
    "kernel_type": "script",
    "is_private": True,
    "enable_gpu": False,
    "enable_tpu": False,
    "enable_internet": True,
    "dataset_sources": [],
    "competition_sources": [],
    "kernel_sources": [],
    "model_sources": [],
}, indent=2))

(here / "script.py").write_text(f'''\
import json, subprocess, sys, traceback
out = "/kaggle/working"
log = open(out + "/kaggle-smoke.log", "w")
def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    log.write(" ".join(cmd) + "\\n" + p.stdout[-5000:] + p.stderr[-5000:] + "\\n"); log.flush()
    return p.returncode
run([sys.executable, "-m", "pip", "install", "-q", "{spec}"])
try:
    from ticdata import smoke
    json.dump(smoke.net(512), open(out + "/kaggle-net.json", "w"), indent=2, default=str)
    json.dump(smoke.bench(20, ("uhc",)), open(out + "/kaggle-bench.json", "w"), indent=2, default=str)
except Exception:
    log.write(traceback.format_exc())
log.close()
''')
print("prepared", user, spec)
