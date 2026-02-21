import { apiFetch } from './client'
import type { FeedbackStats } from '../types'

interface FeedbackItemRaw {
  id: string
  account_id?: string
  accountId?: string
  rating: number
  query_type?: string
  queryType?: string
  tools_used?: string[]
  toolsUsed?: string[]
  friction_points?: string[]
  frictionPoints?: string[]
  suggestion?: string
  created_at?: string
  createdAt?: string
  created?: string
  date?: string
}

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

function normalizeFeedbackItem(raw: FeedbackItemRaw): FeedbackItem {
  return {
    id: raw.id,
    account_id: raw.account_id ?? raw.accountId ?? '',
    rating: Number(raw.rating),
    query_type: raw.query_type ?? raw.queryType,
    tools_used: raw.tools_used ?? raw.toolsUsed ?? [],
    friction_points: raw.friction_points ?? raw.frictionPoints ?? [],
    suggestion: raw.suggestion,
    created_at: raw.created_at ?? raw.createdAt ?? raw.created ?? raw.date ?? '',
  }
}

export async function listFeedback(
  accountId?: string,
  limit?: number,
): Promise<FeedbackItem[]> {
  const params = new URLSearchParams()
  if (accountId) params.set('account_id', accountId)
  if (limit) params.set('limit', String(limit))
  const qs = params.toString()
  const data = await apiFetch<{ feedback: FeedbackItemRaw[] }>(
    `/api/feedback/list${qs ? `?${qs}` : ''}`,
  )
  return data.feedback.map(normalizeFeedbackItem)
}

export function getFeedbackStats(accountId?: string): Promise<FeedbackStats> {
  const params = new URLSearchParams()
  if (accountId) params.set('account_id', accountId)
  const qs = params.toString()
  return apiFetch<FeedbackStats>(`/api/feedback/stats${qs ? `?${qs}` : ''}`)
}
