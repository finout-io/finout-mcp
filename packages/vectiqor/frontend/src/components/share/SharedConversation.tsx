import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Box,
  Center,
  Loader,
  Stack,
  Text,
  Title,
} from '@mantine/core'
import { getSharedConversation } from '../../api/conversations'
import { ChatMessage } from '../chat/ChatMessage'

export function SharedConversation() {
  const { token } = useParams<{ token: string }>()

  const { data: conversation, isLoading, error } = useQuery({
    queryKey: ['shared', token],
    queryFn: () => getSharedConversation(token!),
    enabled: Boolean(token),
    staleTime: Infinity,
  })

  if (isLoading) {
    return (
      <Center h="100vh">
        <Loader color="finoutTeal" />
      </Center>
    )
  }

  if (error || !conversation) {
    return (
      <Center h="100vh">
        <Stack align="center" gap="xs">
          <Title order={3}>Conversation not found</Title>
          <Text c="dimmed" size="sm">
            This link may have expired or the conversation was deleted.
          </Text>
        </Stack>
      </Center>
    )
  }

  return (
    <Box style={{ maxWidth: 800, margin: '0 auto', padding: '32px 16px' }}>
      <Stack gap="lg">
        <Stack gap={4}>
          <Title order={2}>{conversation.name}</Title>
          <Text size="sm" c="dimmed">
            {conversation.account_id} · {conversation.model} ·{' '}
            {new Date(conversation.created_at).toLocaleDateString()}
          </Text>
        </Stack>

        <Stack gap={0}>
          {conversation.messages.map((msg, idx) => (
            <ChatMessage key={idx} message={msg} />
          ))}
        </Stack>
      </Stack>
    </Box>
  )
}
