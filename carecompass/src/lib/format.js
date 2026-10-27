export function money(v, opts = {}) {
  if (v == null || !Number.isFinite(v)) return '—'
  const cents = opts.cents ?? (Math.abs(v) < 1000 && Math.round(v) !== v)
  return v.toLocaleString('en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0,
  })
}
export const moneyRound = (v) => money(v, { cents: false })
export const PAYER_NAMES = { cigna: 'Cigna', aetna: 'Aetna', uhc: 'UnitedHealthcare' }
