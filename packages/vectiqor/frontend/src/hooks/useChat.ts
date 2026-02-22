import { useState, useCallback } from 'react'
import { notifications } from '@mantine/notifications'
import { sendMessageStream, fetchToolOutputs } from '../api/chat'
import type { ChatResponse, Message, ModelId } from '../types'

export interface ChatState {
  messages: Message[]
  isSending: boolean
  statusMessage: string | null
  streamingText: string
  sendMessage: (content: string, model: ModelId) => Promise<void>
  clearMessages: () => void
  setMessages: (messages: Message[]) => void
}

export function useChat(accountId: string | null): ChatState {
  const [messages, setMessages] = useState<Message[]>([])
  const [isSending, setIsSending] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [streamingText, setStreamingText] = useState('')

  const send = useCallback(
    async (content: string, model: ModelId) => {
      if (isSending) return

      const userMessage: Message = { role: 'user', content }
      const nextMessages = [...messages, userMessage]
      setMessages(nextMessages)
      setIsSending(true)
      setStatusMessage('Thinking...')
      setStreamingText('')

      const wallStart = Date.now()
      let streamedText = ''
      let captured: { response: ChatResponse; wallTime: number; streamedText: string } | null = null

      try {
        await sendMessageStream(
          {
          message: content,
          conversation_history: messages,
          model,
          account_id: accountId ?? undefined,
          },
          {
            onStatus: (status) => {
              if (!status?.message) return
              setStatusMessage(status.message)
            },
            onToken: (text) => {
              streamedText += text.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
              setStreamingText(streamedText)
            },
            // Don't update state here — just capture so we can fetch outputs
            // before the single setMessages call below.
            onFinal: (response) => {
              captured = { response, wallTime: (Date.now() - wallStart) / 1000, streamedText }
            },
          },
        )

        // TypeScript CFA doesn't track mutations through callbacks; cast explicitly.
        // sendMessageStream guarantees onFinal is called before resolving (throws otherwise).
        const cap = captured as { response: ChatResponse; wallTime: number; streamedText: string } | null
        if (cap) {
          const { response, wallTime } = cap
          const finalContent = (response.response || cap.streamedText)
            .replace(/\r\n/g, '\n')
            .replace(/\r/g, '\n')
          let thinkingTrace = ''
          const trimmedFinal = finalContent.trim()
          if (trimmedFinal) {
            const idx = cap.streamedText.lastIndexOf(trimmedFinal)
            if (idx > 0) {
              thinkingTrace = cap.streamedText.slice(0, idx).trim()
            }
          } else {
            thinkingTrace = cap.streamedText.trim()
          }

          // Fetch full tool outputs before committing to state so that auto-save
          // always receives complete data (avoids a double-setMessages race with isSaving).
          let toolCalls = response.tool_calls
          if (response.request_id && response.tool_calls.length > 0) {
            try {
              toolCalls = await fetchToolOutputs(response.request_id)
            } catch {
              // Non-critical: charts won't show but text response is intact
            }
          }

          const assistantMessage: Message = {
            role: 'assistant',
            content: finalContent,
            thinking_trace: thinkingTrace || undefined,
            tool_calls: toolCalls,
            usage: response.usage,
            model: response.usage.model,
            tool_time: response.tool_time,
            total_time: wallTime,
          }
          // Single setMessages call — React 18 batches this with setIsSending(false)
          // from finally, so auto-save fires exactly once with full tool outputs.
          setStatusMessage(null)
          setStreamingText('')
          setMessages([...nextMessages, assistantMessage])
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error'
        setStatusMessage(null)
        setStreamingText('')
        const assistantError: Message = {
          role: 'assistant',
          content: `I couldn't complete that request. ${errorMessage}`,
        }
        setMessages([...nextMessages, assistantError])
        notifications.show({
          title: 'Failed to send message',
          message: errorMessage,
          color: 'red',
        })
      } finally {
        setStatusMessage(null)
        setStreamingText('')
        setIsSending(false)
      }
    },
    [messages, isSending, accountId],
  )

  const clearMessages = useCallback(() => {
    setMessages([])
    setStatusMessage(null)
    setStreamingText('')
  }, [])

  return {
    messages,
    isSending,
    statusMessage,
    streamingText,
    sendMessage: send,
    clearMessages,
    setMessages,
  }
}
