import { apiFetch } from './client'
import type { ChatResponse, Message } from '../types'

export interface SendMessageParams {
  message: string
  conversation_history: Message[]
  model: string
  account_id?: string
}

export interface ChatStatusEvent {
  phase?: string
  message: string
  tool_name?: string
}

interface StreamCallbacks {
  onStatus?: (status: ChatStatusEvent) => void
  onToken?: (text: string) => void
  onFinal: (response: ChatResponse) => void
}

const rawRequestTimeoutMs = Number(import.meta.env.VITE_CHAT_REQUEST_TIMEOUT_MS ?? '560000')
const CHAT_REQUEST_TIMEOUT_MS = Number.isFinite(rawRequestTimeoutMs) ? rawRequestTimeoutMs : 560000

function startAbortTimer(controller: AbortController): number | undefined {
  if (CHAT_REQUEST_TIMEOUT_MS <= 0) {
    return undefined
  }
  return window.setTimeout(() => controller.abort(), CHAT_REQUEST_TIMEOUT_MS)
}

export async function sendMessage(params: SendMessageParams): Promise<ChatResponse> {
  const controller = new AbortController()
  const timeout = startAbortTimer(controller)

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
      throw new Error('Request timed out. Please retry or narrow the query.')
    }
    throw err
  } finally {
    if (timeout !== undefined) window.clearTimeout(timeout)
  }
}

export async function sendMessageStream(
  params: SendMessageParams,
  callbacks: StreamCallbacks,
): Promise<void> {
  const controller = new AbortController()
  const timeout = startAbortTimer(controller)

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
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

    if (!response.ok) {
      let detail = `HTTP ${response.status}`
      try {
        const body = await response.json()
        detail = body.detail ?? body.message ?? detail
      } catch {
        // Ignore parse failures.
      }
      throw new Error(detail)
    }

    if (!response.body) {
      throw new Error('Streaming response body is missing')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let gotFinal = false
    const processBlock = (block: string) => {
      if (!block.trim() || block.startsWith(':')) return

      let eventName = 'message'
      const dataLines: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart())
        }
      }
      if (dataLines.length === 0) return

      let payload: unknown = null
      try {
        payload = JSON.parse(dataLines.join('\n'))
      } catch {
        return
      }

      if (eventName === 'status') {
        callbacks.onStatus?.(payload as ChatStatusEvent)
      } else if (eventName === 'token') {
        const tokenPayload = payload as { text?: string }
        if (tokenPayload.text) callbacks.onToken?.(tokenPayload.text)
      } else if (eventName === 'final') {
        callbacks.onFinal(payload as ChatResponse)
        gotFinal = true
      } else if (eventName === 'error') {
        const err = payload as { detail?: string }
        throw new Error(err.detail || 'Streaming request failed')
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      // Normalize all SSE newline variants so boundary parsing is stable.
      buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
      if (done && buffer.trim().length > 0 && !buffer.endsWith('\n\n')) {
        // Flush a trailing partial event block on EOF.
        buffer += '\n\n'
      }

      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
        processBlock(block)
      }

      if (done) break
    }

    if (!gotFinal) {
      throw new Error('Stream ended before a final response was received')
    }
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      throw new Error('Request timed out. Please retry or narrow the query.')
    }
    throw err
  } finally {
    if (timeout !== undefined) window.clearTimeout(timeout)
  }
}
