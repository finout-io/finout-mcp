import { useState, useCallback, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getAccounts } from '../api/accounts'
import type { Account } from '../types'

export interface SessionState {
  isReady: boolean
  isInitializing: boolean
  isEmbedded: boolean
  selectedAccount: Account | null
  accounts: Account[]
  error: string | null
  selectAccount: (accountId: string) => void
}

function getUrlParam(name: string): string | null {
  return new URLSearchParams(window.location.search).get(name)
}

export function useSession(): SessionState {
  const queryClient = useQueryClient()
  const isEmbedded = getUrlParam('embedded') === '1'

  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(() => {
    const urlAccountId = getUrlParam('accountId')
    if (urlAccountId) return urlAccountId
    if (isEmbedded) return null
    return localStorage.getItem('billy_last_account')
  })

  const { data: accountsData } = useQuery({
    queryKey: ['accounts'],
    queryFn: getAccounts,
    staleTime: 3 * 60 * 60 * 1000, // 3 hours
  })
  const accounts: Account[] = accountsData?.accounts ?? []
  const serverCurrentId = accountsData?.currentAccountId ?? null

  const effectiveAccountId = accounts.find((a) => a.accountId === selectedAccountId)?.accountId ??
    (
      isEmbedded
        ? null
        : accounts.find((a) => a.accountId === serverCurrentId)?.accountId ??
          accounts[0]?.accountId ??
          null
    )
  const selectedAccount = accounts.find((a) => a.accountId === effectiveAccountId) ?? null

  const selectAccount = useCallback(
    (accountId: string, skipStorage = false) => {
      setSelectedAccountId(accountId)
      if (!skipStorage) {
        localStorage.setItem('billy_last_account', accountId)
      }
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
    [queryClient],
  )

  // postMessage integration for embedded mode
  useEffect(() => {
    if (!isEmbedded) return

    // Signal readiness to parent
    window.parent.postMessage({ type: 'BILLY_READY' }, '*')

    const handler = (event: MessageEvent) => {
      if (event.source !== window.parent) return
      if (event.data?.type === 'FOBO_ACCOUNT_CHANGED' && typeof event.data.accountId === 'string') {
        selectAccount(event.data.accountId as string, true)
      }
    }

    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  // selectAccount is stable (useCallback with [queryClient]), safe to include
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEmbedded])

  return {
    isReady: selectedAccount !== null,
    isInitializing: false,
    isEmbedded,
    selectedAccount,
    accounts,
    error: null,
    selectAccount: (accountId: string) => selectAccount(accountId, isEmbedded),
  }
}
