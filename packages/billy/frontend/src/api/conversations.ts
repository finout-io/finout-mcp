import { apiFetch } from './client'
import type { Conversation, ConversationSummary, Message, ToolCall } from '../types'

export interface SaveConversationParams {
  name: string
  account_id: string
  model: string
  messages: Message[]
  tool_calls: ToolCall[]
  user_note?: string
  conversation_id?: string
}

export async function saveConversation(
  params: SaveConversationParams,
): Promise<{ id: string; share_token: string }> {
  const data = await apiFetch<{ success: boolean; conversation_id: string; share_token: string }>(
    '/api/conversations/save',
    { method: 'POST', body: JSON.stringify(params) },
  )
  return { id: data.conversation_id, share_token: data.share_token }
}

export async function listConversations(
  accountId?: string,
  search?: string,
): Promise<ConversationSummary[]> {
  const params = new URLSearchParams()
  if (accountId) params.set('account_id', accountId)
  if (search) params.set('search', search)
  const qs = params.toString()
  const data = await apiFetch<{ conversations: ConversationSummary[] }>(
    `/api/conversations/list${qs ? `?${qs}` : ''}`,
  )
  return data.conversations
}

export function getConversation(id: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/api/conversations/${id}`)
}

export function getSharedConversation(token: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/api/share/${token}`)
}

export function updateNote(id: string, note: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/api/conversations/${id}/note`, {
    method: 'PUT',
    body: JSON.stringify({ note }),
  })
}
