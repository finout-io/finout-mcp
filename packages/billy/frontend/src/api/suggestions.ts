import { apiFetch } from './client'

interface SuggestedQueriesResponse {
  queries: string[]
}

export async function getSuggestedQueries(accountId: string): Promise<string[]> {
  const data = await apiFetch<SuggestedQueriesResponse>(
    `/api/suggested-queries?account_id=${encodeURIComponent(accountId)}`,
  )
  return data.queries
}
