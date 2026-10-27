const Callout = ({ x, y, n }) => (
  <g>
    <circle cx={x} cy={y} r="13" fill="#f59e0b" stroke="#fff" strokeWidth="3" />
    <text x={x} y={y + 4.5} textAnchor="middle" fontSize="13" fontWeight="800" fill="#fff" fontFamily="Inter, sans-serif">{n}</text>
  </g>
)

export const CARD_STEPS = [
  { n: 1, title: 'Plan type & network', text: 'PPO, HMO, EPO, HDHP… PPO plans cover some out-of-network care; HMO/EPO usually do not.' },
  { n: 2, title: 'Deductible', text: 'Often shown as “In-Ntwk Ded”. The first number is for you (individual); the second is for the whole family.' },
  { n: 3, title: 'Coinsurance', text: 'May appear as “Coins 20%” or “Plan pays 80%” — which means YOU pay 20%.' },
  { n: 4, title: 'Copays', text: 'Flat fees for common visits (PCP, specialist, urgent care, ER). Imaging copays are less often printed — check your benefits summary.' },
  { n: 5, title: 'Out-of-pocket maximum', text: 'The most you’ll pay this year for in-network care. Sometimes labeled “OOP Max”.' },
  { n: 6, title: 'Member services phone', text: 'Usually on the back. Call to ask what you have met so far and whether a place is in-network.' },
]

export default function CardIllustration({ className = '' }) {
  return (
    <svg viewBox="0 0 660 420" className={className} role="img" aria-label="Illustration of a sample health insurance card with numbered callouts">
      <defs>
        <linearGradient id="cardg" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#1c56b0" /><stop offset="1" stopColor="#143a73" />
        </linearGradient>
        <filter id="sh" x="-10%" y="-10%" width="120%" height="130%">
          <feDropShadow dx="0" dy="8" stdDeviation="10" floodColor="#0f1f33" floodOpacity=".18" />
        </filter>
      </defs>
      <g filter="url(#sh)">
        <rect x="20" y="20" width="620" height="380" rx="26" fill="#fff" />
        <path d="M20 46a26 26 0 0 1 26-26h568a26 26 0 0 1 26 26v62H20z" fill="url(#cardg)" />
      </g>
      <g fontFamily="Inter, sans-serif">
        <text x="50" y="62" fontSize="22" fontWeight="800" fill="#fff">Sample Health Plan</text>
        <text x="50" y="88" fontSize="13" fill="#d9eaff">Illustration only · not a real insurer</text>
        <rect x="486" y="44" width="124" height="40" rx="10" fill="#10b981" />
        <text x="548" y="70" fontSize="17" fontWeight="800" fill="#fff" textAnchor="middle">PPO · Choice</text>
        <text x="50" y="140" fontSize="11" fill="#6b7c93" fontWeight="600" letterSpacing="1">MEMBER</text>
        <text x="50" y="160" fontSize="16" fill="#0f1f33" fontWeight="700">JANE Q SAMPLE</text>
        <text x="50" y="188" fontSize="11" fill="#6b7c93" fontWeight="600" letterSpacing="1">MEMBER ID</text>
        <text x="50" y="206" fontSize="15" fill="#0f1f33">XYZ 000000000</text>
        <text x="220" y="188" fontSize="11" fill="#6b7c93" fontWeight="600" letterSpacing="1">GROUP #</text>
        <text x="220" y="206" fontSize="15" fill="#0f1f33">0000000</text>
        <rect x="46" y="228" width="276" height="148" rx="14" fill="#f6f8fb" />
        <text x="62" y="252" fontSize="11" fill="#6b7c93" fontWeight="700" letterSpacing="1">COPAYS</text>
        {[['PCP', '$30'], ['Specialist', '$60'], ['Urgent Care', '$75'], ['ER', '$350']].map(([k, v], i) => (
          <g key={k}>
            <text x="62" y={280 + i * 25} fontSize="15" fill="#3d4f66">{k}</text>
            <text x="300" y={280 + i * 25} fontSize="15" fill="#0f1f33" fontWeight="700" textAnchor="end">{v}</text>
          </g>
        ))}
        <rect x="340" y="128" width="274" height="248" rx="14" fill="#eef6ff" />
        <text x="356" y="152" fontSize="11" fill="#6b7c93" fontWeight="700" letterSpacing="1">IN-NETWORK</text>
        <text x="356" y="182" fontSize="14" fill="#3d4f66">Deductible (Ind / Fam)</text>
        <text x="356" y="204" fontSize="18" fill="#0f1f33" fontWeight="800">$1,500 / $3,000</text>
        <text x="356" y="240" fontSize="14" fill="#3d4f66">Coinsurance</text>
        <text x="356" y="262" fontSize="18" fill="#0f1f33" fontWeight="800">20% after ded.</text>
        <text x="356" y="298" fontSize="14" fill="#3d4f66">Out-of-Pocket Max (Ind / Fam)</text>
        <text x="356" y="320" fontSize="18" fill="#0f1f33" fontWeight="800">$6,000 / $12,000</text>
        <text x="356" y="356" fontSize="12" fill="#6b7c93">Member Services: 1-800-000-0000</text>
      </g>
      <Callout x={476} y={48} n={1} /><Callout x={604} y={186} n={2} /><Callout x={604} y={246} n={3} />
      <Callout x={330} y={250} n={4} /><Callout x={604} y={304} n={5} /><Callout x={604} y={350} n={6} />
    </svg>
  )
}
