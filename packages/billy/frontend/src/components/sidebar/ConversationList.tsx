import { useState } from 'react'
import {
  Box,
  Loader,
  NavLink,
  Stack,
  Text,
  TextInput,
} from '@mantine/core'
import { useConversations } from '../../hooks/useConversations'
import type { ConversationSummary } from '../../types'

interface Props {
  accountId: string | null
  activeId?: string
  onSelect: (conversation: ConversationSummary) => void
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days}d ago`
  return date.toLocaleDateString()
}

export function ConversationList({ accountId, activeId, onSelect }: Props) {
  const [search, setSearch] = useState('')
  const { conversations, isLoading } = useConversations(accountId, search || undefined)

  return (
    <Stack gap="xs" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <TextInput
        placeholder="Search conversations…"
        size="xs"
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        radius="md"
      />

      <Box style={{ flex: 1, overflowY: 'auto' }}>
        {isLoading ? (
          <Loader size="xs" color="finoutTeal" mt="sm" />
        ) : conversations.length === 0 ? (
          <Text size="xs" c="dimmed" ta="center" mt="md">
            {search ? 'No results' : 'No saved conversations'}
          </Text>
        ) : (
          conversations.map((c) => (
            <NavLink
              key={c.id}
              label={c.name}
              description={formatDate(c.updated_at)}
              active={c.id === activeId}
              onClick={() => onSelect(c)}
              style={{ borderRadius: 6 }}
            />
          ))
        )}
      </Box>
    </Stack>
  )
}
