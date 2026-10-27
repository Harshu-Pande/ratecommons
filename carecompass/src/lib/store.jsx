import { createContext, useContext, useEffect, useState } from 'react'

export const EMPTY_PROFILE = {
  personalized: false, deductible: '', deductibleMet: '', coinsurance: '', copay: '', copayMode: 'none',
  oopMax: '', oopSpent: '',
}
const KEY = 'carecompass.profile.v1'
const Ctx = createContext(null)

function load() {
  try {
    const s = sessionStorage.getItem(KEY)
    return s ? { ...EMPTY_PROFILE, ...JSON.parse(s) } : EMPTY_PROFILE
  } catch {
    return EMPTY_PROFILE
  }
}

export function ProfileProvider({ children }) {
  const [profile, setProfile] = useState(load)
  useEffect(() => {
    try { sessionStorage.setItem(KEY, JSON.stringify(profile)) } catch { /* private mode */ }
  }, [profile])
  return (
    <Ctx.Provider value={{
      profile, setProfile, update: (p) => setProfile((x) => ({ ...x, ...p })), reset: () => setProfile(EMPTY_PROFILE),
    }}>
      {children}
    </Ctx.Provider>
  )
}
export const useProfile = () => useContext(Ctx)
