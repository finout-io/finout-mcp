import { apiFetch } from './client'
import type { ChatResponse, Message } from '../types'

export interface SendMessageParams {
  message: string
  conversation_history: Message[]
  model: string
  account_id?: string
}

export async function sendMessage(params: SendMessageParams): Promise<ChatResponse> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 120_000)

  try {
    return await apiFetch<ChatResponse>('/api/chat', {
      method: 'POST',
      signal: controller.signal,
      body: JSON.stringify({
        message: params.message,
        conversation_history: params.conversation_history.map((m) => ({
          role: m.role,
          content: m.content,
        })),
        model: params.model,
        account_id: params.account_id,
      }),
    })
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      throw new Error('Request timed out. Please try again.')
    }
    throw err
  } finally {
    window.clearTimeout(timeout)
  }
}
