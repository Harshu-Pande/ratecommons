// On-device text recognition for insurance cards and bills (Tesseract.js); nothing leaves the browser.
let worker = null

async function getWorker(onProgress) {
  getWorker.onProgress = onProgress
  worker ||= (async () => {
    const { createWorker } = await import('tesseract.js')
    return createWorker('eng', 1, {
      logger: (m) => {
        if (m.status === 'recognizing text' && typeof getWorker.onProgress === 'function') getWorker.onProgress(m.progress)
      },
    })
  })()
  return worker
}

async function preprocess(file) {
  const bmp = await createImageBitmap(file)
  const scale = Math.min(2.5, Math.max(1, 2000 / Math.max(bmp.width, bmp.height)))
  const c = document.createElement('canvas')
  c.width = Math.round(bmp.width * scale)
  c.height = Math.round(bmp.height * scale)
  const ctx = c.getContext('2d')
  ctx.drawImage(bmp, 0, 0, c.width, c.height)
  const img = ctx.getImageData(0, 0, c.width, c.height)
  const d = img.data
  for (let i = 0; i < d.length; i += 4) {
    let g = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]
    g = Math.max(0, Math.min(255, (g - 128) * 1.35 + 128))
    d[i] = d[i + 1] = d[i + 2] = g
  }
  ctx.putImageData(img, 0, 0)
  return c
}

export async function readImage(file, onProgress) {
  const w = await getWorker(onProgress)
  let src = file
  try { src = await preprocess(file) } catch { /* use the original */ }
  const { data } = await w.recognize(src)
  return data.text || ''
}

const num = (s) => {
  const n = parseFloat(String(s).replace(/[,$\s]/g, ''))
  return Number.isFinite(n) ? n : null
}

function after(text, label, value, span = 90) {
  const re = new RegExp(label.source, label.flags.includes('g') ? label.flags : label.flags + 'g')
  for (const m of text.matchAll(re)) {
    const v = text.slice(m.index + m[0].length, m.index + m[0].length + span).match(value)
    if (v) return v[1]
  }
  return null
}

export function parseCard(raw) {
  const t = raw.replace(/[|]/g, ' ').replace(/[ \t]+/g, ' ')
  const out = {}
  const dollars = /\$\s?(\d{1,3}(?:,\d{3})+|\d{3,6})(?![\d,])/
  const ded = after(t, /\b(?:deductible|ded)\b/i, dollars)
  if (ded) out.deductible = num(ded)
  const oop = after(t, /(?:out[- ]of[- ]pocket|\bOOP\b|\bOOPM\b)/i, dollars)
  if (oop) out.oopMax = num(oop)
  let co = after(t, /co-?ins(?:urance)?/i, /(\d{1,3})\s?%/, 60) || after(t, /plan pays/i, /(\d{2,3})\s?%/, 30)
  if (!co) {
    const m = t.match(/(\d{1,2})\s?%\s*(?:co-?ins|coinsurance)/i)
    if (m) co = m[1]
  }
  if (co) {
    let c = parseInt(co, 10)
    if (c >= 50 && c <= 100) c = 100 - c
    if (c >= 0 && c < 100) out.coinsurance = c
  }
  const copay = (k) => {
    const m = t.match(new RegExp(`\\b(?:${k})\\b[^\\d$\\n]{0,18}\\$\\s?(\\d{1,4})`, 'i'))
    return m ? num(m[1]) : null
  }
  const copays = {
    'Primary care': copay('PCP|primary|office visit|OV'),
    Specialist: copay('spec(?:ialist)?|SPC|SPL'),
    'Urgent care': copay('urgent(?: care)?|UC'),
    'Emergency room': copay('ER|emergency|EMER'),
    'Imaging / radiology': copay('imag(?:ing)?|radiology|MRI|CT|hi-?tech|advanced'),
  }
  out.copays = Object.fromEntries(Object.entries(copays).filter(([, v]) => v != null))
  if (copays['Imaging / radiology'] != null) out.copay = copays['Imaging / radiology']
  out.found = ['deductible', 'oopMax', 'coinsurance'].filter((k) => out[k] != null).length + Object.keys(out.copays).length
  return out
}

export function parseBill(raw) {
  const t = raw.replace(/[ \t]+/g, ' ')
  const grab = (k) => {
    const re = new RegExp(`(?:${k})[^\\d$\\n]{0,30}\\$?\\s?(-?[\\d,]+\\.\\d{2})`, 'gi')
    const v = [...t.matchAll(re)].map((m) => num(m[1])).filter((x) => x != null && x >= 0)
    return v.length ? Math.max(...v) : null
  }
  return {
    owed: grab('amount you owe|you owe|you may owe|patient responsibility|your responsibility|patient balance|balance due|amount due|total due|pay this amount|what you owe'),
    toDeductible: grab('applied to (?:your )?deductible|deductible amount|deductible'),
    coinsurance: grab('coinsurance|co-insurance'),
    copay: grab('copay|co-pay'),
  }
}
