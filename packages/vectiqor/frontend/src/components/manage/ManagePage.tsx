import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Accordion,
  Badge,
  Box,
  Card,
  Center,
  Group,
  Loader,
  Popover,
  Rating,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { listConversations, getConversation } from '../../api/conversations'
import { listFeedback, getFeedbackStats } from '../../api/feedback'
import { ChatMessage } from '../chat/ChatMessage'
import type { Conversation, ConversationSummary } from '../../types'

function formatDate(value: unknown): string {
  if (!value) return '—'
  const str = String(value)
  // asyncpg returns naive datetime strings without timezone — append Z to treat as UTC
  const iso = str.includes('+') || str.endsWith('Z') ? str : str + 'Z'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? str : d.toLocaleDateString()
}

// ─── Conversations tab ────────────────────────────────────────────────────────

function ConversationRow({ summary }: { summary: ConversationSummary }) {
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
              {summary.account_id}
            </Text>
          </Box>
          <Badge size="sm" variant="light" color="teal" style={{ flexShrink: 0 }}>
            {summary.model.includes('haiku') ? 'Haiku' : summary.model.includes('opus') ? 'Opus' : 'Sonnet'}
          </Badge>
          <Text size="xs" c="dimmed" style={{ flexShrink: 0, width: 80, textAlign: 'right' }}>
            {formatDate(summary.created_at)}
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

function ConversationsTab() {
  const [search, setSearch] = useState('')
  const [accountFilter, setAccountFilter] = useState<string | null>(null)

  const { data: all = [], isLoading } = useQuery({
    queryKey: ['manage-conversations'],
    queryFn: () => listConversations(),
    staleTime: 30 * 1000,
  })

  const accounts = [...new Set(all.map((c) => c.account_id))].sort()

  const filtered = all.filter((c) => {
    const matchSearch = !search || c.name.toLowerCase().includes(search.toLowerCase())
    const matchAccount = !accountFilter || c.account_id === accountFilter
    return matchSearch && matchAccount
  })

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
          data={accounts.map((a) => ({ value: a, label: a }))}
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
            <ConversationRow key={c.id} summary={c} />
          ))}
        </Accordion>
      )}
    </Stack>
  )
}

// ─── Feedback tab ─────────────────────────────────────────────────────────────

function FeedbackTab() {
  const [accountFilter, setAccountFilter] = useState<string | null>(null)

  const { data: feedback = [], isLoading } = useQuery({
    queryKey: ['manage-feedback'],
    queryFn: () => listFeedback(),
    staleTime: 30 * 1000,
  })

  const { data: stats } = useQuery({
    queryKey: ['manage-feedback-stats', accountFilter],
    queryFn: () => getFeedbackStats(accountFilter ?? undefined),
    staleTime: 30 * 1000,
  })

  const accounts = [...new Set(feedback.map((f) => f.account_id))].sort()

  const filtered = accountFilter
    ? feedback.filter((f) => f.account_id === accountFilter)
    : feedback

  return (
    <Stack gap="md">
      {/* Stats */}
      {stats && (
        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <Card withBorder>
            <Text size="xs" c="dimmed">Total feedback</Text>
            <Text size="xl" fw={700}>{stats.total_count ?? 0}</Text>
          </Card>
          <Card withBorder>
            <Text size="xs" c="dimmed">Avg rating</Text>
            <Text size="xl" fw={700}>{stats.avg_rating != null ? Number(stats.avg_rating).toFixed(1) : '—'} / 5</Text>
          </Card>
          <Card withBorder>
            <Text size="xs" c="dimmed">👍 Positive (4-5★)</Text>
            <Text size="xl" fw={700}>{stats.positive_count ?? 0}</Text>
          </Card>
          <Card withBorder>
            <Text size="xs" c="dimmed">👎 Negative (1-2★)</Text>
            <Text size="xl" fw={700}>{stats.negative_count ?? 0}</Text>
          </Card>
        </SimpleGrid>
      )}

      {/* Filter */}
      <Select
        placeholder="All accounts"
        data={accounts.map((a) => ({ value: a, label: a }))}
        value={accountFilter}
        onChange={setAccountFilter}
        clearable
        size="sm"
        style={{ width: 240 }}
      />

      {/* Table */}
      {isLoading ? (
        <Center py="xl"><Loader color="teal" /></Center>
      ) : (
        <Table striped highlightOnHover withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={170}>Rating</Table.Th>
              <Table.Th>Account</Table.Th>
              <Table.Th>Query type</Table.Th>
              <Table.Th>Tools used</Table.Th>
              <Table.Th>Friction</Table.Th>
              <Table.Th>Suggestion</Table.Th>
              <Table.Th>Date</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {filtered.map((f) => (
              <Table.Tr key={f.id}>
                <Table.Td>
                  <Group gap={8} wrap="nowrap">
                    <Rating value={Math.max(0, Math.min(5, f.rating))} readOnly count={5} />
                    <Text size="xs" c="dimmed">{f.rating}/5</Text>
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Text size="xs">{f.account_id}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs">{f.query_type ?? '—'}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs">{f.tools_used?.join(', ') ?? '—'}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs">{f.friction_points?.join(', ') ?? '—'}</Text>
                </Table.Td>
                <Table.Td style={{ maxWidth: 200 }}>
                  {f.suggestion ? (
                    <Popover width={320} position="left" withArrow shadow="md">
                      <Popover.Target>
                        <Text size="xs" truncate style={{ cursor: 'pointer', textDecoration: 'underline dotted' }}>
                          {f.suggestion}
                        </Text>
                      </Popover.Target>
                      <Popover.Dropdown>
                        <ScrollArea mah={200}>
                          <Text size="sm">{f.suggestion}</Text>
                        </ScrollArea>
                      </Popover.Dropdown>
                    </Popover>
                  ) : (
                    <Text size="xs" c="dimmed">—</Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="xs">{formatDate(f.created_at)}</Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function ManagePage() {
  return (
    <Box p="xl" style={{ maxWidth: 1200, margin: '0 auto' }}>
      <Stack gap="lg">
        <Group gap="sm" align="baseline">
          <Text style={{ fontSize: 28 }}>🤖</Text>
          <Title order={2}>VECTIQOR — Conversation Manager</Title>
        </Group>

        <Tabs defaultValue="conversations" keepMounted={false}>
          <Tabs.List>
            <Tabs.Tab value="conversations">💬 Conversations</Tabs.Tab>
            <Tabs.Tab value="feedback">⭐ Feedback</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="conversations" pt="md">
            <ConversationsTab />
          </Tabs.Panel>

          <Tabs.Panel value="feedback" pt="md">
            <FeedbackTab />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </Box>
  )
}
