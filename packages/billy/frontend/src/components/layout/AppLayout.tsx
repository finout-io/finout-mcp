import { useState, useCallback, useEffect, useRef } from 'react'
import {
  AppShell,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Code,
  Divider,
  Group,
  List,
  Modal,
  Popover,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useQuery } from '@tanstack/react-query'
import { useSession } from '../../hooks/useSession'
import { useChat } from '../../hooks/useChat'
import { useConversations } from '../../hooks/useConversations'
import { useUser } from '../../hooks/useUser'
import { getWhatsNew } from '../../api/whatsNew'
import { getTools } from '../../api/tools'
import { Sidebar } from './Sidebar'
import { ChatArea } from '../chat/ChatArea'
import { ChatInput } from '../chat/ChatInput'
import type { ConversationSummary, ModelId, ToolEntry, WhatsNewEntry } from '../../types'
import { MODEL_OPTIONS } from '../../types'
import { Link } from 'react-router-dom'

const LAST_SEEN_CHANGELOG_VERSION_KEY = 'billy_last_seen_changelog_version'

const CHANGELOG_SECTION_LABELS: Record<keyof WhatsNewEntry['sections'], string> = {
  external_mcp: 'External MCP',
  internal_mcp: 'Internal MCP',
  billy: 'Billy',
}

function createConversationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `conv-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function LoginScreen({ onLogin }: { onLogin: (name: string, email: string) => void }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [errors, setErrors] = useState<{ name?: string; email?: string }>({})

  const handleSubmit = () => {
    const newErrors: { name?: string; email?: string } = {}
    if (!name.trim()) newErrors.name = 'Name is required'
    if (!email.trim()) newErrors.email = 'Email is required'
    else if (!email.includes('@')) newErrors.email = 'Enter a valid email'
    setErrors(newErrors)
    if (Object.keys(newErrors).length === 0) {
      onLogin(name.trim(), email.trim())
    }
  }

  return (
    <Center h="100vh">
      <Card shadow="md" padding="xl" radius="md" w={380}>
        <Stack gap="md">
          <Text size="lg" fw={600} ta="center">Welcome to Billy</Text>
          <TextInput
            label="Name"
            placeholder="Your name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            error={errors.name}
          />
          <TextInput
            label="Email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
            error={errors.email}
            onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          />
          <Button fullWidth onClick={handleSubmit}>Continue</Button>
        </Stack>
      </Card>
    </Center>
  )
}


export function AppLayout() {
  const { user, setUser, clearUser } = useUser()
  const session = useSession()
  const { isEmbedded } = session
  const accountId = session.selectedAccount?.accountId ?? null
  const chat = useChat(accountId, user?.email)

  const [model, setModel] = useState<ModelId>(MODEL_OPTIONS[1]!.value)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(isEmbedded)
  const [activeConversationId, setActiveConversationId] = useState<string>(() => createConversationId())
  const [shareToken, setShareToken] = useState<string | undefined>()
  const [whatsNewOpen, setWhatsNewOpen] = useState(false)
  const [unseenEntries, setUnseenEntries] = useState<WhatsNewEntry[]>([])
  const [toolsOpen, setToolsOpen] = useState(false)
  const [toolsCategory, setToolsCategory] = useState<string>('all')
  // Ref so the auto-save effect always reads the latest ID without becoming a dep
  const activeConversationIdRef = useRef<string | undefined>(activeConversationId)
  const lastAccountIdRef = useRef<string | null>(null)
  const initializedWhatsNewRef = useRef(false)

  const { save, isSaving, loadConversation } = useConversations(accountId)
  const { data: whatsNewData } = useQuery({
    queryKey: ['whats-new'],
    queryFn: getWhatsNew,
    staleTime: 10 * 60 * 1000,
  })
  const { data: toolsData } = useQuery({
    queryKey: ['tools'],
    queryFn: getTools,
    staleTime: Infinity,
  })

  // Keep ref in sync with state
  useEffect(() => { activeConversationIdRef.current = activeConversationId }, [activeConversationId])

  // Switching accounts always starts a fresh conversation.
  useEffect(() => {
    // Ignore transient null values during refetch/state propagation.
    if (!accountId) return
    if (lastAccountIdRef.current === accountId) return
    lastAccountIdRef.current = accountId

    chat.clearMessages()
    setActiveConversationId(createConversationId())
    setShareToken(undefined)
  }, [accountId, chat])

  // Auto-save after every assistant response, updating the same conversation
  useEffect(() => {
    const hasAssistant = chat.messages.some((m) => m.role === 'assistant')
    if (!hasAssistant || !accountId || isSaving) return

    const firstUser = chat.messages.find((m) => m.role === 'user')
    const name = firstUser ? firstUser.content.slice(0, 60) : 'Conversation'
    const toolCalls = chat.messages.flatMap((m) => m.tool_calls ?? [])

    save({
      name,
      accountId,
      accountName: session.selectedAccount?.name,
      model,
      messages: chat.messages,
      toolCalls,
      conversationId: activeConversationIdRef.current, // always current, never stale
      userEmail: user?.email,
    }).then((result) => {
      setActiveConversationId(result.id)
      setShareToken(result.share_token)
    }).catch(() => { /* ignore silent auto-save failures */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.messages])

  useEffect(() => {
    if (!whatsNewData || initializedWhatsNewRef.current) return
    initializedWhatsNewRef.current = true

    const lastSeenVersion = localStorage.getItem(LAST_SEEN_CHANGELOG_VERSION_KEY)
    if (!lastSeenVersion) {
      if (whatsNewData.entries.length > 0) {
        setUnseenEntries(whatsNewData.entries)
        setWhatsNewOpen(true)
      }
      return
    }

    const lastSeenIndex = whatsNewData.entries.findIndex((e) => e.version === lastSeenVersion)
    const nextUnseen =
      lastSeenIndex === -1
        ? whatsNewData.entries
        : whatsNewData.entries.slice(0, lastSeenIndex)

    if (nextUnseen.length > 0) {
      setUnseenEntries(nextUnseen)
      setWhatsNewOpen(true)
    }
  }, [whatsNewData])

  const handleSelectConversation = useCallback(
    async (summary: ConversationSummary) => {
      try {
        const conv = await loadConversation(summary.id)
        chat.setMessages(conv.messages)
        setActiveConversationId(conv.id)
        setShareToken(conv.share_token)
        setModel(conv.model as ModelId)
      } catch {
        notifications.show({
          title: 'Failed to load conversation',
          message: 'Could not load the selected conversation',
          color: 'red',
        })
      }
    },
    [loadConversation, chat],
  )

  const handleNewConversation = useCallback(() => {
    chat.clearMessages()
    setActiveConversationId(createConversationId())
    setShareToken(undefined)
  }, [chat])

  const handleSendMessage = useCallback(
    (content: string, nextModel: ModelId) => chat.sendMessage(content, nextModel, activeConversationIdRef.current),
    [chat],
  )

  const handleCopyShareLink = useCallback(() => {
    if (!shareToken) return
    const url = `${window.location.origin}/share/${shareToken}`
    navigator.clipboard.writeText(url).then(
      () => notifications.show({ message: 'Share link copied!', color: 'teal' }),
      () => notifications.show({ message: 'Failed to copy', color: 'red' }),
    )
  }, [shareToken])

  const handleExport = useCallback(() => {
    if (chat.messages.length === 0) return
    let md = `# BILLY Conversation Export\n`
    md += `Date: ${new Date().toISOString()}\n`
    md += `Account: ${session.selectedAccount?.name ?? 'Unknown'}\n\n---\n\n`

    chat.messages.forEach((msg, i) => {
      if (msg.role === 'user') {
        md += `## User Message ${i + 1}\n${msg.content}\n\n`
      } else {
        md += `## Assistant Response ${i + 1}\n${msg.content}\n\n`
        if (msg.tool_calls && msg.tool_calls.length > 0) {
          md += `### Tool Calls (${msg.tool_calls.length})\n`
          msg.tool_calls.forEach((tc) => {
            md += `\n**Tool: ${tc.name}**\n`
            md += `Input:\n\`\`\`json\n${JSON.stringify(tc.input, null, 2)}\n\`\`\`\n`
            md += `Output:\n\`\`\`\n${typeof tc.output === 'string' ? tc.output : JSON.stringify(tc.output, null, 2)}\n\`\`\`\n`
          })
          md += `\n`
        }
      }
    })

    navigator.clipboard.writeText(md).then(
      () => notifications.show({ message: '📋 Chat copied as Markdown', color: 'teal' }),
      () => notifications.show({ message: 'Failed to copy', color: 'red' }),
    )
  }, [chat.messages, session.selectedAccount])

  const markWhatsNewSeen = useCallback(() => {
    if (!whatsNewData?.current_version) return
    localStorage.setItem(LAST_SEEN_CHANGELOG_VERSION_KEY, whatsNewData.current_version)
    setWhatsNewOpen(false)
  }, [whatsNewData])

  if (!user) {
    if (isEmbedded) {
      return (
        <Center h="100vh">
          <Text size="sm" c="dimmed">Waiting for embedded user context…</Text>
        </Center>
      )
    }
    return <LoginScreen onLogin={setUser} />
  }

  const CATEGORY_LABELS: Record<string, string> = {
    all: 'All',
    cost_query: 'Cost Queries',
    filters: 'Filters',
    waste: 'Waste & Savings',
    context: 'Context & Objects',
    visualization: 'Visualization',
    admin: 'Admin',
  }

  const toolCategories: string[] = toolsData
    ? ['all', ...Array.from(new Set(toolsData.tools.map((t: ToolEntry) => t.category)))]
    : []

  const filteredTools = toolsData
    ? toolsData.tools.filter((t) => toolsCategory === 'all' || t.category === toolsCategory)
    : []

  return (
    <>
      <Modal
        opened={toolsOpen}
        onClose={() => setToolsOpen(false)}
        title="Available Tools"
        size="xl"
        centered
      >
        <Stack gap="md">
          <Group gap="xs" wrap="wrap">
            {toolCategories.map((cat) => (
              <Button
                key={cat}
                size="xs"
                variant={toolsCategory === cat ? 'filled' : 'light'}
                color="finoutBlue"
                onClick={() => setToolsCategory(cat)}
              >
                {CATEGORY_LABELS[cat] ?? cat}
              </Button>
            ))}
          </Group>
          <ScrollArea h={480}>
            <Stack gap="md">
              {filteredTools.map((tool: ToolEntry) => (
                <Card key={tool.name} padding="sm" radius="sm" withBorder>
                  <Stack gap={6}>
                    <Group gap="xs" align="center">
                      <Code fw={700}>{tool.name}</Code>
                      <Badge
                        size="xs"
                        color={tool.availability === 'public' ? 'teal' : 'grape'}
                        variant="light"
                      >
                        {tool.availability}
                      </Badge>
                      <Badge size="xs" color="gray" variant="light">
                        {CATEGORY_LABELS[tool.category] ?? tool.category}
                      </Badge>
                    </Group>
                    <Text size="sm">{tool.description}</Text>
                    {tool.workflow && (
                      <Text size="xs" c="dimmed" ff="monospace">
                        Workflow: {tool.workflow}
                      </Text>
                    )}
                    {tool.when_to_use.length > 0 && (
                      <Stack gap={2}>
                        <Text size="xs" fw={600} c="dimmed">WHEN TO USE</Text>
                        <List size="xs" spacing={2}>
                          {tool.when_to_use.map((w) => (
                            <List.Item key={w}>{w}</List.Item>
                          ))}
                        </List>
                      </Stack>
                    )}
                    {tool.example_prompts.filter((p) => !p.startsWith('(')).length > 0 && (
                      <Stack gap={2}>
                        <Text size="xs" fw={600} c="dimmed">EXAMPLE PROMPTS</Text>
                        <List size="xs" spacing={2}>
                          {tool.example_prompts.filter((p) => !p.startsWith('(')).map((p) => (
                            <List.Item key={p}>{p}</List.Item>
                          ))}
                        </List>
                      </Stack>
                    )}
                    {tool.key_params.length > 0 && (
                      <Stack gap={2}>
                        <Text size="xs" fw={600} c="dimmed">KEY PARAMS</Text>
                        <List size="xs" spacing={2}>
                          {tool.key_params.map((p) => (
                            <List.Item key={p}>{p}</List.Item>
                          ))}
                        </List>
                      </Stack>
                    )}
                  </Stack>
                </Card>
              ))}
            </Stack>
          </ScrollArea>
          <Divider />
          <Group justify="flex-end">
            <Button onClick={() => setToolsOpen(false)}>Close</Button>
          </Group>
        </Stack>
      </Modal>
      <Modal
        opened={whatsNewOpen}
        onClose={markWhatsNewSeen}
        title={`What's New in Billy (${whatsNewData?.current_version ?? ''})`}
        size="lg"
        centered
      >
        <Stack gap="md">
          {unseenEntries.map((entry) => (
            <Stack key={entry.version} gap={6}>
              <Title order={4}>{entry.title}</Title>
              <Text size="sm" c="dimmed">
                v{entry.version} · {entry.date}
              </Text>
              {(Object.keys(CHANGELOG_SECTION_LABELS) as (keyof WhatsNewEntry['sections'])[])
                .map((sectionKey) => ({ key: sectionKey, changes: entry.sections[sectionKey] }))
                .filter(({ changes }) => changes.length > 0)
                .map(({ key, changes }) => (
                  <Stack key={key} gap={4}>
                    <Text fw={600} size="sm">{CHANGELOG_SECTION_LABELS[key]}</Text>
                    <List spacing={4} size="sm">
                      {changes.map((change) => (
                        <List.Item key={`${entry.version}-${key}-${change}`}>{change}</List.Item>
                      ))}
                    </List>
                  </Stack>
                ))}
            </Stack>
          ))}
          <Group justify="flex-end">
            <Button onClick={markWhatsNewSeen}>Got it</Button>
          </Group>
        </Stack>
      </Modal>
      <AppShell
        navbar={{ width: sidebarCollapsed ? 64 : 260, breakpoint: 'sm', collapsed: { mobile: false } }}
        padding={0}
      >
      <AppShell.Navbar p="md" style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column', backgroundColor: '#1e2433', borderRight: '1px solid #2d3748' }}>
        <Sidebar
          accounts={session.accounts}
          selectedAccountId={session.selectedAccount?.accountId ?? null}
          onSelectAccount={session.selectAccount}
          isInitializing={session.isInitializing}
          isEmbedded={isEmbedded}
          collapsed={sidebarCollapsed}
          onToggleCollapsed={() => setSidebarCollapsed((collapsed) => !collapsed)}
          model={model}
          onModelChange={setModel}
          activeConversationId={activeConversationId}
          onSelectConversation={handleSelectConversation}
          onNewConversation={handleNewConversation}
          shareToken={shareToken}
          onCopyShareLink={handleCopyShareLink}
        />
      </AppShell.Navbar>

      <AppShell.Main style={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: '#f8fafc' }}>
        {!isEmbedded && (
          <Group
            px="md"
            py="sm"
            justify="space-between"
            style={{
              borderBottom: '1px solid #e2e8f0',
              flexShrink: 0,
              backgroundColor: '#ffffff',
            }}
          >
            <Text size="sm" c="dimmed">
              {session.selectedAccount?.name ?? 'No account selected'}
              {session.isInitializing && ' · Initializing…'}
              {session.error && ` · Error: ${session.error}`}
            </Text>
            <Group gap="xs">
              {toolsData && (
                <Button
                  size="xs"
                  variant="subtle"
                  color="#1570ef"
                  onClick={() => {
                    setToolsCategory('all')
                    setToolsOpen(true)
                  }}
                >
                  Tools
                </Button>
              )}
              {whatsNewData && (
                <Button
                  size="xs"
                  variant="subtle"
                  color="#1570ef"
                  onClick={() => {
                    setUnseenEntries(whatsNewData.entries)
                    setWhatsNewOpen(true)
                  }}
                >
                  What's new
                </Button>
              )}
              {chat.messages.length > 0 && (
                <Tooltip label="Copy chat as Markdown">
                  <Button size="xs" variant="subtle" color="#1570ef" onClick={handleExport}>
                    📋 Export
                  </Button>
                </Tooltip>
              )}
              {shareToken && (
                <Tooltip label="Copy share link">
                  <Button size="xs" variant="subtle" color="#1570ef" onClick={handleCopyShareLink}>
                    🔗 Share
                  </Button>
                </Tooltip>
              )}
              <Button
                component={Link}
                to="/manage"
                size="xs"
                variant="subtle"
                color="#1570ef"
              >
                Manage
              </Button>
              <Popover position="bottom-end" shadow="md">
                <Popover.Target>
                  <Button size="xs" variant="subtle">{user.name}</Button>
                </Popover.Target>
                <Popover.Dropdown>
                  <Stack gap="xs">
                    <Text size="sm" fw={500}>{user.name}</Text>
                    <Text size="xs" c="dimmed">{user.email}</Text>
                    <Button size="xs" variant="light" color="red" onClick={clearUser}>
                      Sign out
                    </Button>
                  </Stack>
                </Popover.Dropdown>
              </Popover>
            </Group>
          </Group>
        )}

        {/* Chat area */}
        <Box style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <ChatArea
            messages={chat.messages}
            isSending={chat.isSending}
            statusMessage={chat.statusMessage}
            streamingText={chat.streamingText}
            onSuggestedQuestion={handleSendMessage}
            model={model}
            sessionReady={session.isReady}
            accountId={accountId}
            userName={user?.name}
          />

          <Stack
            px="md"
            py="sm"
            gap="xs"
            style={{
              borderTop: '1px solid #e2e8f0',
              flexShrink: 0,
              backgroundColor: '#ffffff',
            }}
          >
            <ChatInput
              onSend={handleSendMessage}
              model={model}
              disabled={!session.isReady}
              loading={chat.isSending}
            />
          </Stack>
        </Box>
      </AppShell.Main>
      </AppShell>
    </>
  )
}
