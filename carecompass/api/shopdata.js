// Serves the patient tool's price files from our own domain, so a visitor's browser never contacts the
// storage host directly. Streams the file from the Hugging Face bucket (following its CDN redirect) and
// lets Vercel's CDN cache it for a day.
const ORIGIN = 'https://huggingface.co/buckets/ratecommons/work/resolve/shop/v1'
const SAFE = /^(?:[a-z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.json$/

export default {
  async fetch(request) {
    const p = new URL(request.url).searchParams.get('p') || ''
    if (!SAFE.test(p) || p.includes('..')) return new Response('Not found', { status: 404 })
    let up
    try {
      up = await fetch(`${ORIGIN}/${p}`, { redirect: 'follow', headers: { 'user-agent': 'ratecommons-site' } })
    } catch {
      return new Response('Upstream unavailable', { status: 502, headers: { 'cache-control': 'no-store' } })
    }
    if (up.status === 404) {
      return new Response('null', { status: 404, headers: { 'content-type': 'application/json', 'cache-control': 'public, s-maxage=3600' } })
    }
    if (!up.ok) return new Response('Upstream error', { status: 502, headers: { 'cache-control': 'no-store' } })
    return new Response(up.body, {
      status: 200,
      headers: {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800',
        'x-content-type-options': 'nosniff',
      },
    })
  },
}
