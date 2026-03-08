import { Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Accordion,
  Badge,
  Box,
  Card,
  Center,
  Group,
  Loader,
  Rating,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Tooltip,
  Title,
} from '@mantine/core'
import { listConversations, getConversation } from '../../api/conversations'
import { listFeedback, getFeedbackStats } from '../../api/feedback'
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

function renderCollapsedCell(text: string | undefined, lines: number = 2) {
  if (!text) return <Text size="xs" c="dimmed">—</Text>
  return (
    <Tooltip label={text} multiline w={460} withArrow openDelay={250}>
      <Text size="xs" lineClamp={lines} style={{ cursor: 'help' }}>
        {text}
      </Text>
    </Tooltip>
  )
}

function sortFeedbackByCreatedAtDesc<T extends { created_at: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const aParsed = parseTimestamp(a.created_at)
    const bParsed = parseTimestamp(b.created_at)
    const aTime = aParsed?.getTime() ?? Number.NEGATIVE_INFINITY
    const bTime = bParsed?.getTime() ?? Number.NEGATIVE_INFINITY
    return bTime - aTime
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

// ─── Feedback tab ─────────────────────────────────────────────────────────────

function FeedbackTab({ accountNameById }: { accountNameById: Map<string, string> }) {
  const [accountFilter, setAccountFilter] = useState<string | null>(null)
  const [expandedFeedbackId, setExpandedFeedbackId] = useState<string | null>(null)

  const { data: feedback = [], isLoading } = useQuery({
    queryKey: ['manage-feedback'],
    queryFn: () => listFeedback(),
    staleTime: 0,
  })

  const { data: stats } = useQuery({
    queryKey: ['manage-feedback-stats', accountFilter],
    queryFn: () => getFeedbackStats(accountFilter ?? undefined),
    staleTime: 0,
  })

  const accounts = [...new Set(feedback.map((f) => f.account_id))]
    .sort((a, b) => accountLabel(a, accountNameById).localeCompare(accountLabel(b, accountNameById)))

  const filtered = sortFeedbackByCreatedAtDesc(accountFilter
    ? feedback.filter((f) => f.account_id === accountFilter)
    : feedback)

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
        data={accounts.map((a) => ({ value: a, label: accountLabel(a, accountNameById) }))}
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
        <ScrollArea>
          <Table striped highlightOnHover withTableBorder miw={1100}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={170}>Rating</Table.Th>
                <Table.Th w={240}>Account</Table.Th>
                <Table.Th w={120}>Query type</Table.Th>
                <Table.Th w={240}>Tools used</Table.Th>
                <Table.Th w={260}>Friction</Table.Th>
                <Table.Th w={320}>Suggestion</Table.Th>
                <Table.Th w={190}>Date</Table.Th>
                <Table.Th w={120}>Details</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {filtered.map((f) => {
                const isExpanded = expandedFeedbackId === f.id
                const toolsText = f.tools_used?.join(', ') ?? ''
                const frictionText = f.friction_points?.join(', ') ?? ''
                const suggestionText = f.suggestion ?? ''
                return (
                  <Fragment key={f.id}>
                    <Table.Tr
                      onClick={() => setExpandedFeedbackId(isExpanded ? null : f.id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <Table.Td>
                        <Group gap={8} wrap="nowrap">
                          <Rating value={Math.max(0, Math.min(5, f.rating))} readOnly count={5} />
                          <Text size="xs" c="dimmed">{f.rating}/5</Text>
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs">{accountLabel(f.account_id, accountNameById)}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs">{f.query_type ?? '—'}</Text>
                      </Table.Td>
                      <Table.Td>
                        {isExpanded ? (
                          <Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>
                            {toolsText || '—'}
                          </Text>
                        ) : (
                          renderCollapsedCell(toolsText, 1)
                        )}
                      </Table.Td>
                      <Table.Td>
                        {isExpanded ? (
                          <Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>
                            {frictionText || '—'}
                          </Text>
                        ) : (
                          renderCollapsedCell(frictionText, 2)
                        )}
                      </Table.Td>
                      <Table.Td>
                        {isExpanded ? (
                          <Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>
                            {suggestionText || '—'}
                          </Text>
                        ) : (
                          renderCollapsedCell(suggestionText, 2)
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs">{formatDateTime(f.created_at)}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {isExpanded ? 'Collapse' : 'Expand'}
                        </Text>
                      </Table.Td>
                    </Table.Tr>

                    {isExpanded && (
                      <Table.Tr>
                        <Table.Td colSpan={8}>
                          <Stack gap="sm">
                            <Group justify="space-between">
                              <Text size="sm" fw={600}>Feedback details</Text>
                              <Text size="xs" c="dimmed">{formatDateTime(f.created_at)}</Text>
                            </Group>
                            <Text size="xs">
                              <Text span fw={600}>Account: </Text>
                              {accountLabel(f.account_id, accountNameById)}
                            </Text>
                            <Text size="xs">
                              <Text span fw={600}>Query type: </Text>
                              {f.query_type ?? '—'}
                            </Text>
                            <Box>
                              <Text size="xs" fw={600} mb={4}>Tools used</Text>
                              <Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>
                                {toolsText || '—'}
                              </Text>
                            </Box>
                            <Box>
                              <Text size="xs" fw={600} mb={4}>Friction points</Text>
                              <Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>
                                {frictionText || '—'}
                              </Text>
                            </Box>
                            <Box>
                              <Text size="xs" fw={600} mb={4}>Suggestion</Text>
                              <Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>
                                {suggestionText || '—'}
                              </Text>
                            </Box>
                          </Stack>
                        </Table.Td>
                      </Table.Tr>
                    )}
                  </Fragment>
                )
              })}
            </Table.Tbody>
          </Table>
        </ScrollArea>
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
            <Tabs.Tab value="feedback">⭐ Feedback</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="conversations" pt="md">
            <ConversationsTab accountNameById={accountNameById} />
          </Tabs.Panel>

          <Tabs.Panel value="feedback" pt="md">
            <FeedbackTab accountNameById={accountNameById} />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </Box>
  )
}
