import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Accordion,
  Badge,
  Box,
  Center,
  Group,
  Loader,
  Select,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { listConversations, getConversation } from '../../api/conversations'
import { getAccounts } from '../../api/accounts'
import { ChatMessage } from '../chat/ChatMessage'
import type { Conversation, ConversationSummary } from '../../types'

function parseTimestamp(value: unknown): Date | null {
  if (!value) return null

  if (value instanceof Date) {
    return isNaN(value.getTime()) ? null : value
  }
  if (typeof value === 'number') {
    const d = new Date(value)
    return isNaN(d.getTime()) ? null : d
  }
  if (typeof value === 'object') {
    const obj = value as { $date?: unknown; created_at?: unknown; createdAt?: unknown }
    const nested = obj.$date ?? obj.created_at ?? obj.createdAt
    if (nested !== undefined) return parseTimestamp(nested)
  }

  const raw = String(value).trim()
  if (!raw) return null

  const normalizedBase = raw.includes('T') ? raw : raw.replace(' ', 'T')
  // JS Date parsing is inconsistent with >3 fractional second digits (microseconds).
  const normalized = normalizedBase.replace(/(\.\d{3})\d+/, '$1')
  const withTimezone = /([zZ]|[+-]\d{2}:\d{2})$/.test(normalized)
    ? normalized
    : `${normalized}Z`

  const parsed = new Date(withTimezone)
  if (!isNaN(parsed.getTime())) return parsed

  const fallback = new Date(raw)
  return isNaN(fallback.getTime()) ? null : fallback
}

function formatDateTime(value: unknown): string {
  const date = parseTimestamp(value)
  if (date) return date.toLocaleString()
  if (!value) return '—'
  return String(value)
}

function accountLabel(accountId: string, accountNameById: Map<string, string>): string {
  return accountNameById.get(accountId) ?? `Unknown (${accountId.slice(0, 8)}…)`
}

function sortByCreatedAtDesc<T extends { created_at: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const aParsed = parseTimestamp(a.created_at)
    const bParsed = parseTimestamp(b.created_at)
    const aTime = aParsed?.getTime() ?? Number.NEGATIVE_INFINITY
    const bTime = bParsed?.getTime() ?? Number.NEGATIVE_INFINITY
    if (aTime !== bTime) return bTime - aTime
    // Fallback for non-parseable values: compare raw strings descending.
    return String(b.created_at ?? '').localeCompare(String(a.created_at ?? ''))
  })
}

// ─── Conversations tab ────────────────────────────────────────────────────────

function ConversationRow({
  summary,
  accountNameById,
}: {
  summary: ConversationSummary
  accountNameById: Map<string, string>
}) {
  const [open, setOpen] = useState(false)
  const { data: full, isFetching } = useQuery<Conversation>({
    queryKey: ['conversation', summary.id],
    queryFn: () => getConversation(summary.id),
    enabled: open,
    staleTime: Infinity,
  })

  const msgCount = full?.messages.length ?? '—'
  const toolCount = full?.tool_calls?.length ?? '—'

  return (
    <Accordion.Item value={summary.id}>
      <Accordion.Control onClick={() => setOpen(true)}>
        <Group gap="md" wrap="nowrap">
          <Box style={{ flex: 1, minWidth: 0 }}>
            <Text size="sm" fw={500} truncate>
              {summary.name}
            </Text>
            <Text size="xs" c="dimmed">
              {accountLabel(summary.account_id, accountNameById)}
              {summary.user_email && ` · ${summary.user_email}`}
            </Text>
          </Box>
          <Badge size="sm" variant="light" color="teal" style={{ flexShrink: 0 }}>
            {summary.model.includes('haiku') ? 'Haiku' : summary.model.includes('opus') ? 'Opus' : 'Sonnet'}
          </Badge>
          <Text size="xs" c="dimmed" style={{ flexShrink: 0, width: 170, textAlign: 'right' }}>
            {formatDateTime(summary.created_at)}
          </Text>
        </Group>
      </Accordion.Control>
      <Accordion.Panel>
        {isFetching && <Center py="md"><Loader size="sm" color="teal" /></Center>}
        {full && (
          <Stack gap="xs">
            <Group gap="xl">
              <Text size="xs" c="dimmed">{msgCount} messages · {toolCount} tool calls</Text>
              {full.user_note && (
                <Text size="xs" c="yellow.4">📝 {full.user_note}</Text>
              )}
              {full.share_token && (
                <Text
                  size="xs"
                  c="teal"
                  style={{ cursor: 'pointer', textDecoration: 'underline' }}
                  onClick={() => window.open(`/share/${full.share_token}`, '_blank')}
                >
                  🔗 Share link
                </Text>
              )}
            </Group>
            <Box
              style={(theme) => ({
                background: theme.colors.dark[8],
                borderRadius: theme.radius.md,
                padding: theme.spacing.md,
                maxHeight: 500,
                overflowY: 'auto',
              })}
            >
              {full.messages.map((msg, i) => (
                <ChatMessage key={i} message={msg} />
              ))}
            </Box>
          </Stack>
        )}
      </Accordion.Panel>
    </Accordion.Item>
  )
}

function ConversationsTab({ accountNameById }: { accountNameById: Map<string, string> }) {
  const [search, setSearch] = useState('')
  const [accountFilter, setAccountFilter] = useState<string | null>(null)

  const { data: all = [], isLoading } = useQuery({
    queryKey: ['manage-conversations'],
    queryFn: () => listConversations(),
    staleTime: 30 * 1000,
  })

  const accounts = [...new Set(all.map((c) => c.account_id))]
    .sort((a, b) => accountLabel(a, accountNameById).localeCompare(accountLabel(b, accountNameById)))

  const filtered = sortByCreatedAtDesc(all.filter((c) => {
    const matchSearch = !search || c.name.toLowerCase().includes(search.toLowerCase())
    const matchAccount = !accountFilter || c.account_id === accountFilter
    return matchSearch && matchAccount
  }))

  return (
    <Stack gap="md">
      <Group gap="sm">
        <TextInput
          placeholder="Search conversations…"
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ flex: 1 }}
          size="sm"
        />
        <Select
          placeholder="All accounts"
          data={accounts.map((a) => ({ value: a, label: accountLabel(a, accountNameById) }))}
          value={accountFilter}
          onChange={setAccountFilter}
          clearable
          size="sm"
          style={{ width: 240 }}
        />
        <Text size="sm" c="dimmed" style={{ flexShrink: 0 }}>
          {filtered.length} / {all.length}
        </Text>
      </Group>

      {isLoading ? (
        <Center py="xl"><Loader color="teal" /></Center>
      ) : filtered.length === 0 ? (
        <Center py="xl"><Text c="dimmed">No conversations found</Text></Center>
      ) : (
        <Accordion variant="separated" chevronPosition="right">
          {filtered.map((c) => (
            <ConversationRow key={c.id} summary={c} accountNameById={accountNameById} />
          ))}
        </Accordion>
      )}
    </Stack>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function ManagePage() {
  const { data: accountsData } = useQuery({
    queryKey: ['accounts'],
    queryFn: getAccounts,
    staleTime: 3 * 60 * 60 * 1000,
  })
  const accountNameById = new Map((accountsData?.accounts ?? []).map((a) => [a.accountId, a.name]))

  return (
    <Box p="xl" style={{ maxWidth: 1200, margin: '0 auto' }}>
      <Stack gap="lg">
        <Group gap="sm" align="baseline">
          <Text style={{ fontSize: 28 }}>🤖</Text>
          <Title order={2}>BILLY — Conversation Manager</Title>
        </Group>

        <Tabs defaultValue="conversations" keepMounted={false}>
          <Tabs.List>
            <Tabs.Tab value="conversations">💬 Conversations</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="conversations" pt="md">
            <ConversationsTab accountNameById={accountNameById} />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </Box>
  )
}
