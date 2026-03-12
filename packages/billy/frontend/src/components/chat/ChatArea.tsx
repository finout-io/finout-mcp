import { useEffect, useRef } from 'react'
import { Box, Group, Text } from '@mantine/core'
import { ChatMessage } from './ChatMessage'
import { MarkdownRenderer } from './MarkdownRenderer'
import { WelcomeScreen } from './WelcomeScreen'
import type { Message, ModelId } from '../../types'
import { billyAvatarUrl } from '../../assets/images'

function StreamingAssistantMessage({
  statusMessage,
  streamingText,
}: {
  statusMessage: string | null
  streamingText: string
}) {
  const hasStream = streamingText.trim().length > 0
  const hasStatus = Boolean(statusMessage && statusMessage.trim().length > 0)

  if (!hasStream && !hasStatus) {
    return null
  }

  const text = hasStream ? streamingText : (statusMessage || 'Thinking...')

  return (
    <Group align="flex-start" gap="xs" mb="md">
      <img
        src={billyAvatarUrl}
        alt="Billy"
        width={36}
        height={36}
        style={{ flexShrink: 0 }}
      />
      <Box
        style={(theme) => ({
          maxWidth: '75%',
          minWidth: 60,
          padding: `${theme.spacing.sm} ${theme.spacing.md}`,
          borderRadius: theme.radius.lg,
          backgroundColor: '#ffffff',
          color: '#1e293b',
          border: '1px solid #e2e8f0',
          boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
        })}
      >
        <MarkdownRenderer content={text} size="sm" />
        {!hasStream && hasStatus && (
          <Text size="xs" c="dimmed" mt={6}>
            {statusMessage || 'Thinking...'}
          </Text>
        )}
      </Box>
    </Group>
  )
}

interface Props {
  messages: Message[]
  isSending: boolean
  statusMessage: string | null
  streamingText: string
  onSuggestedQuestion: (question: string, model: ModelId) => void
  model: ModelId
  sessionReady: boolean
  accountId?: string | null
  userName?: string
}

export function ChatArea({
  messages,
  isSending,
  statusMessage,
  streamingText,
  onSuggestedQuestion,
  model,
  sessionReady,
  accountId,
  userName,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const shouldFollowRef = useRef(true)
  const userPausedRef = useRef(false)
  const prevIsSendingRef = useRef(false)
  const userScrollIntentUntilRef = useRef(0)

  const isNearBottom = (): boolean => {
    const el = containerRef.current
    if (!el) return true
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    return distanceFromBottom < 80
  }

  useEffect(() => {
    // New request cycle: re-enable auto-follow.
    if (!prevIsSendingRef.current && isSending) {
      userPausedRef.current = false
      shouldFollowRef.current = true
    }
    prevIsSendingRef.current = isSending
  }, [isSending])

  useEffect(() => {
    if (shouldFollowRef.current && !userPausedRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, isSending, streamingText])

  const markUserScrollIntent = () => {
    // Small window to associate the next scroll event with explicit user input.
    userScrollIntentUntilRef.current = Date.now() + 600
  }

  return (
    <Box
      ref={containerRef}
      onWheel={markUserScrollIntent}
      onTouchStart={markUserScrollIntent}
      onKeyDown={markUserScrollIntent}
      onScroll={() => {
        // Pause auto-follow only for explicit user scrolling while streaming.
        // Programmatic scroll (from render updates) should not disable follow mode.
        if (isSending && Date.now() <= userScrollIntentUntilRef.current) {
          userPausedRef.current = true
        }
        shouldFollowRef.current = isNearBottom()
      }}
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {messages.length === 0 ? (
        <WelcomeScreen
          onQuestion={(q) => onSuggestedQuestion(q, model)}
          disabled={!sessionReady}
          accountId={accountId}
          userName={userName}
        />
      ) : (
        <>
          {messages.map((msg, idx) => (
            <ChatMessage key={idx} message={msg} />
          ))}
          {isSending && (
            <StreamingAssistantMessage
              statusMessage={statusMessage}
              streamingText={streamingText}
            />
          )}
        </>
      )}
      <div ref={bottomRef} />
    </Box>
  )
}
