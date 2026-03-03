import { useState, useCallback, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
import { getAccounts, switchAccount } from '../api/accounts'
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
    () => localStorage.getItem('vectiqor_last_account'),
  )
  const [isReady, setIsReady] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: accountsData } = useQuery({
    queryKey: ['accounts'],
    queryFn: getAccounts,
    staleTime: 3 * 60 * 60 * 1000, // 3 hours
  })
  const accounts: Account[] = accountsData?.accounts ?? []
  // Prefer localStorage, then server's current_account_id, then first account
  const serverCurrentId = accountsData?.currentAccountId ?? null

  const initMutation = useMutation({
    mutationFn: (accountId: string) => switchAccount(accountId),
    onSuccess: (_data, accountId) => {
      localStorage.setItem('vectiqor_last_account', accountId)
      setIsReady(true)
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
    onError: (err: Error) => {
      setError(err.message)
      setIsReady(false)
      notifications.show({
        title: 'Failed to initialize session',
        message: err.message,
        color: 'red',
      })
    },
  })

  // Auto-init when accounts load
  useEffect(() => {
    if (accounts.length === 0 || isReady || initMutation.isPending) return
    const inList = (id: string | null) => id != null && accounts.some((a) => a.accountId === id)
    // Priority: localStorage → server's current_account_id → first account
    const accountId = inList(selectedAccountId)
      ? selectedAccountId!
      : inList(serverCurrentId)
        ? serverCurrentId!
        : accounts[0]!.accountId
    setSelectedAccountId(accountId)
    initMutation.mutate(accountId)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accounts.length])

  const selectAccount = useCallback(
    (accountId: string) => {
      setSelectedAccountId(accountId)
      setIsReady(false)
      initMutation.mutate(accountId)
    },
    [initMutation],
  )

  // Resolve the effective account: selectedAccountId may lag one render behind the
  // auto-init effect, so also check the server's current_account_id and first account
  // to avoid a "No account selected" flash while state propagates.
  const effectiveAccountId =
    accounts.find((a) => a.accountId === selectedAccountId)?.accountId ??
    accounts.find((a) => a.accountId === serverCurrentId)?.accountId ??
    accounts[0]?.accountId ??
    null
  const selectedAccount = accounts.find((a) => a.accountId === effectiveAccountId) ?? null

  return {
    isReady,
    isInitializing: initMutation.isPending,
    selectedAccount,
    accounts,
    error,
    selectAccount,
  }
}
