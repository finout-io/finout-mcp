import { useEffect, useRef } from 'react'
import { Box, Center, Group, Text } from '@mantine/core'
import { ChatMessage } from './ChatMessage'
import { MarkdownRenderer } from './MarkdownRenderer'
import { WelcomeScreen } from './WelcomeScreen'
import type { Message, ModelId } from '../../types'

function StreamingAssistantMessage({
  model,
  statusMessage,
  streamingText,
}: {
  model: ModelId
  statusMessage: string | null
  streamingText: string
}) {
  const emoji = model.includes('haiku') ? '⚡' : model.includes('opus') ? '👑' : '🤖'
  const hasStream = streamingText.trim().length > 0
  const hasStatus = Boolean(statusMessage && statusMessage.trim().length > 0)

  if (!hasStream && !hasStatus) {
    return null
  }

  const text = hasStream ? streamingText : (statusMessage || 'Thinking...')

  return (
    <Group align="flex-start" gap="xs" mb="md">
      <Center
        style={{
          width: 36,
          height: 36,
          borderRadius: '50%',
          fontSize: 18,
          flexShrink: 0,
          backgroundColor: '#FFD632',
        }}
      >
        {emoji}
      </Center>
      <Box
        style={(theme) => ({
          maxWidth: '75%',
          minWidth: 60,
          padding: `${theme.spacing.sm} ${theme.spacing.md}`,
          borderRadius: theme.radius.lg,
          backgroundColor: theme.colors.dark[6],
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
}

export function ChatArea({
  messages,
  isSending,
  statusMessage,
  streamingText,
  onSuggestedQuestion,
  model,
  sessionReady,
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
        />
      ) : (
        <>
          {messages.map((msg, idx) => (
            <ChatMessage key={idx} message={msg} />
          ))}
          {isSending && (
            <StreamingAssistantMessage
              model={model}
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
