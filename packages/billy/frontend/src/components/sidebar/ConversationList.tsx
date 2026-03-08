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
        styles={{
          input: {
            backgroundColor: 'rgba(255,255,255,0.08)',
            border: '1px solid rgba(255,255,255,0.15)',
            color: '#ffffff',
            '&::placeholder': { color: 'rgba(255,255,255,0.4)' },
          },
        }}
      />

      <Box style={{ flex: 1, overflowY: 'auto' }}>
        {isLoading ? (
          <Loader size="xs" color="finoutBlue" mt="sm" />
        ) : conversations.length === 0 ? (
          <Text size="xs" ta="center" mt="md" style={{ color: 'rgba(255,255,255,0.4)' }}>
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
              styles={{
                root: {
                  color: 'rgba(255,255,255,0.8)',
                  '&:hover': { backgroundColor: 'rgba(255,255,255,0.05)' },
                  '&[dataActive]': { backgroundColor: 'rgba(255,255,255,0.1)' },
                },
                label: { color: 'rgba(255,255,255,0.85)' },
                description: { color: 'rgba(255,255,255,0.4)' },
              }}
            />
          ))
        )}
      </Box>
    </Stack>
  )
}
