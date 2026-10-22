// RateCommons stable front door: forwards every request to the app's current tunnel address.
// The address is read from signed notes on an ntfy.sh topic (see space/tunnel.py).
import crypto from "node:crypto";

const TOPIC = process.env.RC_ANNOUNCE_TOPIC;
const KEY = process.env.RC_ANNOUNCE_KEY;
let cache = { url: null, at: 0 };

async function target(force) {
  if (!force && cache.url && Date.now() - cache.at < 60_000) return cache.url;
  const r = await fetch(`https://ntfy.sh/${TOPIC}/json?poll=1&since=12h`, { cache: "no-store" });
  const lines = (await r.text()).trim().split("\n").filter(Boolean).reverse();
  for (const line of lines) {
    let msg;
    try { msg = JSON.parse(line).message || ""; } catch { continue; }
    const [url, ts, sig] = msg.split("|");
    if (!/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(url || "")) continue;
    const want = crypto.createHmac("sha256", KEY).update(`${url}|${ts}`).digest("hex");
    if (sig && sig.length === want.length && crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(want))) {
      cache = { url, at: Date.now() };
      return url;
    }
  }
  return null;
}

const OFFLINE = `<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>RateCommons</title><body style="font:16px system-ui;max-width:560px;margin:15vh auto;padding:0 16px">
<h2>RateCommons is offline right now</h2><p>The computer that hosts the data is asleep or off.
It comes back on its own when that computer is back online; try again in a few minutes.</p></body>`;

async function handler(request) {
  const u = new URL(request.url);
  const path = u.searchParams.get("__p") || "/";
  u.searchParams.delete("__p");
  const qs = u.searchParams.toString();
  for (let attempt = 0; attempt < 2; attempt++) {
    const t = await target(attempt > 0);
    if (!t) break;
    const headers = new Headers(request.headers);
    // Drop proxy headers: the app must see its own tunnel address as its root, so the MCP server's internal
    // calls to the app go straight to the tunnel instead of back through this gateway.
    for (const h of [...headers.keys()]) if (h.startsWith("x-forwarded") || h.startsWith("x-vercel") || h.startsWith("x-real")) headers.delete(h);
    for (const h of ["host", "connection", "content-length", "forwarded"]) headers.delete(h);
    const init = { method: request.method, headers, redirect: "manual" };
    if (!["GET", "HEAD"].includes(request.method)) { init.body = await request.arrayBuffer(); }
    try {
      const resp = await fetch(`${t}${path.startsWith("/") ? path : "/" + path}${qs ? "?" + qs : ""}`, init);
      if (resp.status === 530 || resp.status === 502) { cache = { url: null, at: 0 }; continue; }  // stale tunnel
      const out = new Headers(resp.headers);
      out.delete("content-encoding"); out.delete("content-length"); out.delete("transfer-encoding");
      const loc = out.get("location");
      if (loc && loc.startsWith(t)) out.set("location", loc.replace(t, `https://${u.host}`));
      return new Response(resp.body, { status: resp.status, headers: out });
    } catch (e) {
      cache = { url: null, at: 0 };
    }
  }
  const wantsHtml = (request.headers.get("accept") || "").includes("text/html");
  return wantsHtml ? new Response(OFFLINE, { status: 503, headers: { "content-type": "text/html; charset=utf-8" } })
                   : Response.json({ ok: false, error: "RateCommons host is offline; try again in a few minutes" }, { status: 503 });
}

export const GET = handler, POST = handler, PUT = handler, PATCH = handler, DELETE = handler, OPTIONS = handler, HEAD = handler;
