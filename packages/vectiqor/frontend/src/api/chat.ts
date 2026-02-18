import { apiFetch } from './client'
import type { ChatResponse, Message } from '../types'

export interface SendMessageParams {
  message: string
  conversation_history: Message[]
  model: string
}

export function sendMessage(params: SendMessageParams): Promise<ChatResponse> {
  return apiFetch<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      message: params.message,
      conversation_history: params.conversation_history.map((m) => ({
        role: m.role,
        content: m.content,
      })),
      model: params.model,
    }),
  })
}
