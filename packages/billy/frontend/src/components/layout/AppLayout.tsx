import { useState, useCallback, useEffect, useRef } from 'react'
import {
  AppShell,
  Box,
  Button,
  Group,
  Stack,
  Text,
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useSession } from '../../hooks/useSession'
import { useChat } from '../../hooks/useChat'
import { useConversations } from '../../hooks/useConversations'
import { Sidebar } from './Sidebar'
import { ChatArea } from '../chat/ChatArea'
import { ChatInput } from '../chat/ChatInput'
import type { ConversationSummary, ModelId } from '../../types'
import { MODEL_OPTIONS } from '../../types'
import { Link } from 'react-router-dom'

export function AppLayout() {
  const session = useSession()
  const { colorScheme, toggleColorScheme } = useMantineColorScheme()
  const accountId = session.selectedAccount?.accountId ?? null
  const chat = useChat(accountId)

  const [model, setModel] = useState<ModelId>(MODEL_OPTIONS[1]!.value)
  const [activeConversationId, setActiveConversationId] = useState<string | undefined>()
  const [shareToken, setShareToken] = useState<string | undefined>()
  // Ref so the auto-save effect always reads the latest ID without becoming a dep
  const activeConversationIdRef = useRef<string | undefined>(undefined)
  const lastAccountIdRef = useRef<string | null>(null)

  const { save, isSaving, loadConversation } = useConversations(accountId)

  // Keep ref in sync with state
  useEffect(() => { activeConversationIdRef.current = activeConversationId }, [activeConversationId])

  // Switching accounts always starts a fresh conversation.
  useEffect(() => {
    // Ignore transient null values during refetch/state propagation.
    if (!accountId) return
    if (lastAccountIdRef.current === accountId) return
    lastAccountIdRef.current = accountId

    chat.clearMessages()
    setActiveConversationId(undefined)
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
      model,
      messages: chat.messages,
      toolCalls,
      conversationId: activeConversationIdRef.current, // always current, never stale
    }).then((result) => {
      setActiveConversationId(result.id)
      setShareToken(result.share_token)
    }).catch(() => { /* ignore silent auto-save failures */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.messages])

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
    setActiveConversationId(undefined)
    setShareToken(undefined)
  }, [chat])

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
    let md = `# VECTIQOR Conversation Export\n`
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

  return (
    <AppShell
      navbar={{ width: 260, breakpoint: 'sm', collapsed: { mobile: false } }}
      padding={0}
    >
      <AppShell.Navbar p="md" style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <Sidebar
          accounts={session.accounts}
          selectedAccountId={session.selectedAccount?.accountId ?? null}
          onSelectAccount={session.selectAccount}
          isInitializing={session.isInitializing}
          model={model}
          onModelChange={setModel}
          activeConversationId={activeConversationId}
          onSelectConversation={handleSelectConversation}
          onNewConversation={handleNewConversation}
        />
      </AppShell.Navbar>

      <AppShell.Main style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        {/* Header */}
        <Group
          px="md"
          py="sm"
          justify="space-between"
          style={(theme) => ({
            borderBottom: `1px solid ${theme.colors.dark[5]}`,
            flexShrink: 0,
          })}
        >
          <Text size="sm" c="dimmed">
            {session.selectedAccount?.name ?? 'No account selected'}
            {session.isInitializing && ' · Initializing…'}
            {session.error && ` · Error: ${session.error}`}
          </Text>
          <Group gap="xs">
            {chat.messages.length > 0 && (
              <Tooltip label="Copy chat as Markdown">
                <Button size="xs" variant="subtle" onClick={handleExport}>
                  📋 Export
                </Button>
              </Tooltip>
            )}
            {shareToken && (
              <Tooltip label="Copy share link">
                <Button size="xs" variant="subtle" onClick={handleCopyShareLink}>
                  🔗 Share
                </Button>
              </Tooltip>
            )}
            <Button
              component={Link}
              to="/manage"
              size="xs"
              variant="subtle"
            >
              Manage
            </Button>
            <Button
              size="xs"
              variant="subtle"
              onClick={() => toggleColorScheme()}
            >
              {colorScheme === 'dark' ? '☀️' : '🌙'}
            </Button>
          </Group>
        </Group>

        {/* Chat area */}
        <Box style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <ChatArea
            messages={chat.messages}
            isSending={chat.isSending}
            statusMessage={chat.statusMessage}
            streamingText={chat.streamingText}
            onSuggestedQuestion={chat.sendMessage}
            model={model}
            sessionReady={session.isReady}
          />

          <Stack
            px="md"
            py="sm"
            gap="xs"
            style={(theme) => ({
              borderTop: `1px solid ${theme.colors.dark[5]}`,
              flexShrink: 0,
            })}
          >
            <ChatInput
              onSend={chat.sendMessage}
              model={model}
              disabled={!session.isReady}
              loading={chat.isSending}
            />
          </Stack>
        </Box>
      </AppShell.Main>
    </AppShell>
  )
}
