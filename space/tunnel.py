"""Keep a Cloudflare quick tunnel to the app open and announce its address.

The quick tunnel's address changes whenever it restarts (reboot, sleep, network change). The stable front
door (gateway/, on Vercel) learns the current address from a signed note posted to an ntfy.sh topic:
"<url>|<unix time>|<hmac-sha256(key, url|time)>". The key is a random secret kept only on this computer
(RC_ANNOUNCE_KEY_FILE) and in the gateway's environment; the topic name is RC_ANNOUNCE_TOPIC.
Run by launchd; exits when cloudflared exits so launchd restarts both.
"""
import hashlib, hmac, os, re, subprocess, sys, time, urllib.request

HOME = os.path.expanduser("~/ratecommons-app")
key = open(os.environ.get("RC_ANNOUNCE_KEY_FILE", f"{HOME}/.announce_key")).read().strip().encode()
topic = os.environ["RC_ANNOUNCE_TOPIC"]
log = open(f"{HOME}/tunnel.log", "w")
p = subprocess.Popen([f"{HOME}/cloudflared", "tunnel", "--no-autoupdate", "--url", "http://localhost:7860"],
                     stdout=log, stderr=subprocess.STDOUT)
url = None
for _ in range(120):
    m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", open(f"{HOME}/tunnel.log").read())
    if m:
        url = m.group(0)
        break
    time.sleep(1)
if not url:
    p.kill()
    sys.exit(1)
open(f"{HOME}/public_url.txt", "w").write(url + "\n")


def announce():
    ts = str(int(time.time()))
    sig = hmac.new(key, f"{url}|{ts}".encode(), hashlib.sha256).hexdigest()
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{topic}", data=f"{url}|{ts}|{sig}".encode(),
                                                      method="POST"), timeout=30)
    except Exception as e:
        print("announce failed", e, flush=True)


while p.poll() is None:
    announce()
    for _ in range(240):  # every 4 minutes
        if p.poll() is not None:
            break
        time.sleep(1)
sys.exit(1)
