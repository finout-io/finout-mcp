import { useState, useCallback } from 'react'
import { notifications } from '@mantine/notifications'
import { sendMessage } from '../api/chat'
import type { Message, ModelId } from '../types'

export interface ChatState {
  messages: Message[]
  isSending: boolean
  sendMessage: (content: string, model: ModelId) => Promise<void>
  clearMessages: () => void
  setMessages: (messages: Message[]) => void
}

export function useChat(): ChatState {
  const [messages, setMessages] = useState<Message[]>([])
  const [isSending, setIsSending] = useState(false)

  const send = useCallback(
    async (content: string, model: ModelId) => {
      if (isSending) return

      const userMessage: Message = { role: 'user', content }
      const nextMessages = [...messages, userMessage]
      setMessages(nextMessages)
      setIsSending(true)

      const wallStart = Date.now()

      try {
        const response = await sendMessage({
          message: content,
          conversation_history: messages,
          model,
        })

        const wallTime = (Date.now() - wallStart) / 1000

        const assistantMessage: Message = {
          role: 'assistant',
          content: response.response,
          tool_calls: response.tool_calls,
          usage: response.usage,
          model: response.usage.model,
          tool_time: response.tool_time,
          total_time: wallTime,
        }

        setMessages([...nextMessages, assistantMessage])
      } catch (err) {
        setMessages(messages)
        notifications.show({
          title: 'Failed to send message',
          message: err instanceof Error ? err.message : 'Unknown error',
          color: 'red',
        })
      } finally {
        setIsSending(false)
      }
    },
    [messages, isSending],
  )

  const clearMessages = useCallback(() => setMessages([]), [])

  return {
    messages,
    isSending,
    sendMessage: send,
    clearMessages,
    setMessages,
  }
}
