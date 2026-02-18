import { useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
import {
  listConversations,
  saveConversation,
  getConversation,
} from '../api/conversations'
import type { Message, ToolCall } from '../types'

export function useConversations(accountId: string | null, search?: string) {
  const queryClient = useQueryClient()

  const { data: conversations = [], isLoading } = useQuery({
    queryKey: ['conversations', accountId, search],
    queryFn: () => listConversations(accountId ?? undefined, search),
    enabled: Boolean(accountId),
    staleTime: 60 * 1000,
  })

  const saveMutation = useMutation({
    mutationFn: saveConversation,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
    onError: (err: Error) => {
      notifications.show({
        title: 'Failed to save conversation',
        message: err.message,
        color: 'red',
      })
    },
  })

  const save = useCallback(
    (params: {
      name: string
      accountId: string
      model: string
      messages: Message[]
      toolCalls: ToolCall[]
      conversationId?: string
    }) => {
      return saveMutation.mutateAsync({
        name: params.name,
        account_id: params.accountId,
        model: params.model,
        messages: params.messages,
        tool_calls: params.toolCalls,
        conversation_id: params.conversationId,
      })
    },
    [saveMutation],
  )

  const loadConversation = useCallback((id: string) => {
    return getConversation(id)
  }, [])

  return {
    conversations,
    isLoading,
    save,
    isSaving: saveMutation.isPending,
    loadConversation,
  }
}
