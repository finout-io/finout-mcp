import { useState, useCallback } from 'react'

const STORAGE_KEY = 'billy_user'

export interface UserInfo {
  name: string
  email: string
}

export interface UserState {
  user: UserInfo | null
  setUser: (name: string, email: string) => void
  clearUser: () => void
}

function loadUser(): UserInfo | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed?.name && parsed?.email) return parsed as UserInfo
    return null
  } catch {
    return null
  }
}

export function useUser(): UserState {
  const [user, setUserState] = useState<UserInfo | null>(loadUser)

  const setUser = useCallback((name: string, email: string) => {
    const info: UserInfo = { name, email }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(info))
    setUserState(info)
  }, [])

  const clearUser = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    setUserState(null)
  }, [])

  return { user, setUser, clearUser }
}
