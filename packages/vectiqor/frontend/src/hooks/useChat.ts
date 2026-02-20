import { useState, useCallback } from 'react'
import { notifications } from '@mantine/notifications'
import { sendMessageStream } from '../api/chat'
import type { Message, ModelId } from '../types'

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
            onFinal: (response) => {
              const wallTime = (Date.now() - wallStart) / 1000
              const finalContent = (response.response || streamedText)
                .replace(/\r\n/g, '\n')
                .replace(/\r/g, '\n')
              let thinkingTrace = ''
              const trimmedFinal = finalContent.trim()
              if (trimmedFinal) {
                const idx = streamedText.lastIndexOf(trimmedFinal)
                if (idx > 0) {
                  thinkingTrace = streamedText.slice(0, idx).trim()
                }
              } else {
                thinkingTrace = streamedText.trim()
              }
              const assistantMessage: Message = {
                role: 'assistant',
                content: finalContent,
                thinking_trace: thinkingTrace || undefined,
                tool_calls: response.tool_calls,
                usage: response.usage,
                model: response.usage.model,
                tool_time: response.tool_time,
                total_time: wallTime,
              }
              setStatusMessage(null)
              setStreamingText('')
              setMessages([...nextMessages, assistantMessage])
            },
          },
        )
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
