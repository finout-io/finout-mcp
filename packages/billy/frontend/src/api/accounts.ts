import { apiFetch } from './client'
import type { Account } from '../types'

interface AccountsResponse {
  accounts: Account[]
  current_account_id: string | null
  cached: boolean
}

export async function getAccounts(): Promise<{ accounts: Account[]; currentAccountId: string | null }> {
  const data = await apiFetch<AccountsResponse>('/api/accounts')
  return { accounts: data.accounts, currentAccountId: data.current_account_id }
}

export function switchAccount(accountId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>('/api/switch-account', {
    method: 'POST',
    body: JSON.stringify({ account_id: accountId }),
  })
}
