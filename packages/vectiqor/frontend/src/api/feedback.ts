import { apiFetch } from './client'
import type { FeedbackStats } from '../types'

export interface FeedbackItem {
  id: string
  account_id: string
  rating: number
  query_type?: string
  tools_used?: string[]
  friction_points?: string[]
  suggestion?: string
  created_at: string
}

export async function listFeedback(
  accountId?: string,
  limit?: number,
): Promise<FeedbackItem[]> {
  const params = new URLSearchParams()
  if (accountId) params.set('account_id', accountId)
  if (limit) params.set('limit', String(limit))
  const qs = params.toString()
  const data = await apiFetch<{ feedback: FeedbackItem[] }>(
    `/api/feedback/list${qs ? `?${qs}` : ''}`,
  )
  return data.feedback
}

export function getFeedbackStats(accountId?: string): Promise<FeedbackStats> {
  const params = new URLSearchParams()
  if (accountId) params.set('account_id', accountId)
  const qs = params.toString()
  return apiFetch<FeedbackStats>(`/api/feedback/stats${qs ? `?${qs}` : ''}`)
}
