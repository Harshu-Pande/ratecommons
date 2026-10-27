import { money } from './format'

const num = (v) => {
  const n = parseFloat(String(v ?? '').replace(/[$,%\s]/g, ''))
  return Number.isFinite(n) && n >= 0 ? n : 0
}

export function normalizeProfile(p) {
  const deductible = num(p.deductible)
  const oopMax = num(p.oopMax)
  return {
    personalized: !!p.personalized,
    deductible,
    deductibleMet: Math.min(num(p.deductibleMet), deductible || Infinity),
    coinsurance: Math.min(num(p.coinsurance), 100) / 100,
    copay: num(p.copay),
    copayMode: p.copayMode || 'none',
    oopMax,
    oopSpent: Math.max(num(p.oopSpent), Math.min(num(p.deductibleMet), deductible || Infinity)),
  }
}

export function isPersonalized(p) {
  const n = normalizeProfile(p)
  return n.personalized && (n.deductible > 0 || n.coinsurance > 0 || n.copay > 0 || n.oopMax > 0)
}

/**
 * Patient estimate for a set of bills (e.g. facility + radiologist, or one visit bill).
 * bills: [{key, label, allowed}]; payerName for the explanation text.
 */
export function estimate(bills, profile, payerName = 'your plan') {
  const total = bills.reduce((s, b) => s + b.allowed, 0)
  if (!isPersonalized(profile)) {
    return {
      personalized: false, total, patient: total, insurer: 0,
      bills: bills.map((b) => ({ ...b, patient: b.allowed, parts: [{ kind: 'deductible', amount: b.allowed }] })),
      steps: [
        `The negotiated price for this is ${money(total)}.`,
        'We have not applied your plan details yet, so this shows the most you would pay if you have NOT met your deductible — you would owe the full negotiated price.',
        'Add your deductible, coinsurance, and what you have spent this year to see your personal estimate.',
      ],
    }
  }
  const a = normalizeProfile(profile)
  let dedLeft = Math.max(0, a.deductible - a.deductibleMet)
  const oopLeft = a.oopMax > 0 ? Math.max(0, a.oopMax - a.oopSpent) : Infinity
  let capLeft = oopLeft
  const steps = [`Negotiated price (what ${payerName} has agreed to pay in total): ${money(total)}` +
    (bills.length > 1 ? ` = ${bills.map((b) => `${money(b.allowed)} ${b.short || b.label.toLowerCase()}`).join(' + ')}.` : '.')]
  if (a.deductible > 0) steps.push(`Deductible remaining this year: ${money(a.deductible)} − ${money(a.deductibleMet)} already met = ${money(dedLeft)}.`)
  if (a.oopMax > 0) steps.push(`Out-of-pocket max remaining: ${money(a.oopMax)} − ${money(a.oopSpent)} already spent = ${money(oopLeft)}.`)
  if (a.copayMode === 'instead' && a.copay > 0) {
    let c = Math.min(a.copay, total)
    let capped = false
    if (c > capLeft) { c = capLeft; capped = true }
    steps.push(`Your plan charges a flat ${money(a.copay)} copay for this type of care instead of the deductible/coinsurance.`)
    if (capped) steps.push(`That is capped by your remaining out-of-pocket maximum: ${money(c)}.`)
    return finish(total, bills.map((b) => {
      const share = total > 0 ? (c * b.allowed) / total : 0
      return { ...b, patient: share, parts: [{ kind: 'copay', amount: share }] }
    }), steps, payerName)
  }
  let copayUsed = false
  const out = bills.map((b) => {
    const parts = []
    let pay = 0
    const d = Math.min(b.allowed, dedLeft)
    if (d > 0) { parts.push({ kind: 'deductible', amount: d }); pay += d; dedLeft -= d }
    const rest = b.allowed - d
    if (rest > 0) {
      if (a.copayMode === 'after' && a.copay > 0) {
        const c = copayUsed ? 0 : Math.min(a.copay, rest)
        if (c > 0) { parts.push({ kind: 'copay', amount: c }); pay += c; copayUsed = true }
      } else if (a.coinsurance > 0) {
        const c = rest * a.coinsurance
        parts.push({ kind: 'coinsurance', amount: c, rate: a.coinsurance, base: rest }); pay += c
      }
    }
    if (pay > capLeft) { parts.push({ kind: 'oopcap', amount: -(pay - capLeft) }); pay = capLeft }
    capLeft -= pay
    return { ...b, patient: pay, parts }
  })
  out.forEach((b) => {
    const t = b.parts.map((x) => x.kind === 'deductible' ? `${money(x.amount)} toward your deductible`
      : x.kind === 'coinsurance' ? `${Math.round(x.rate * 100)}% coinsurance on the remaining ${money(x.base)} = ${money(x.amount)}`
        : x.kind === 'copay' ? `${money(x.amount)} copay`
          : x.kind === 'oopcap' ? `minus ${money(-x.amount)} because you hit your out-of-pocket maximum` : '')
    steps.push(`${b.label}: ${money(b.allowed)} allowed → you pay ${t.length ? t.join(', ') : '$0'} = ${money(b.patient)}.`)
  })
  return finish(total, out, steps, payerName)
}

function finish(total, bills, steps, payerName) {
  const patient = bills.reduce((s, b) => s + b.patient, 0)
  steps.push(`Your estimated total: ${money(patient)}. ${payerName} pays the other ${money(total - patient)}.`)
  return { personalized: true, total, patient, insurer: total - patient, bills, steps }
}
