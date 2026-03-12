import { apiFetch } from './client'
import type { Account } from '../types'

interface AccountRaw {
  accountId?: string
  account_id?: string
  id?: string
  _id?: string
  name?: string
  email?: string
}

interface AccountsResponse {
  accounts: AccountRaw[]
  current_account_id: string | null
  cached: boolean
}

function normalizeAccount(raw: AccountRaw): Account | null {
  const accountId = raw.accountId ?? raw.account_id ?? raw.id ?? raw._id ?? ''
  const name = raw.name ?? raw.email ?? accountId
  if (!accountId) return null
  return { accountId, name }
}

export async function getAccounts(): Promise<{ accounts: Account[]; currentAccountId: string | null }> {
  const data = await apiFetch<AccountsResponse>('/api/accounts')
  return {
    accounts: data.accounts.map(normalizeAccount).filter((account): account is Account => account !== null),
    currentAccountId: data.current_account_id,
  }
}
