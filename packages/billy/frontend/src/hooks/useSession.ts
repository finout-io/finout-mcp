import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getAccounts } from '../api/accounts'
import type { Account } from '../types'

export interface SessionState {
  isReady: boolean
  isInitializing: boolean
  selectedAccount: Account | null
  accounts: Account[]
  error: string | null
  selectAccount: (accountId: string) => void
}

export function useSession(): SessionState {
  const queryClient = useQueryClient()
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(
    () => localStorage.getItem('billy_last_account'),
  )

  const { data: accountsData } = useQuery({
    queryKey: ['accounts'],
    queryFn: getAccounts,
    staleTime: 3 * 60 * 60 * 1000, // 3 hours
  })
  const accounts: Account[] = accountsData?.accounts ?? []
  const serverCurrentId = accountsData?.currentAccountId ?? null

  // Resolve the effective account: prefer localStorage, then server hint, then first account
  const effectiveAccountId =
    accounts.find((a) => a.accountId === selectedAccountId)?.accountId ??
    accounts.find((a) => a.accountId === serverCurrentId)?.accountId ??
    accounts[0]?.accountId ??
    null
  const selectedAccount = accounts.find((a) => a.accountId === effectiveAccountId) ?? null

  const selectAccount = useCallback(
    (accountId: string) => {
      setSelectedAccountId(accountId)
      localStorage.setItem('billy_last_account', accountId)
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
    [queryClient],
  )

  return {
    isReady: selectedAccount !== null,
    isInitializing: false,
    selectedAccount,
    accounts,
    error: null,
    selectAccount,
  }
}
