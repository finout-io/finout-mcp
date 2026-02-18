import { useEffect, useRef } from 'react'
import { Box, Center, Group } from '@mantine/core'
import { ChatMessage } from './ChatMessage'
import { WelcomeScreen } from './WelcomeScreen'
import type { Message, ModelId } from '../../types'

// CSS keyframe animation defined inline via style tag trick — use a CSS string instead
const bounceStyle = `
  @keyframes vectiqor-bounce {
    0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
    30% { transform: translateY(-6px); opacity: 1; }
  }
`

function TypingIndicator({ model }: { model: ModelId }) {
  const emoji = model.includes('haiku') ? '⚡' : model.includes('opus') ? '👑' : '🤖'
  return (
    <>
      <style>{bounceStyle}</style>
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
            padding: `${theme.spacing.sm} ${theme.spacing.md}`,
            borderRadius: theme.radius.lg,
            backgroundColor: theme.colors.dark[6],
          })}
        >
          <Group gap={4} align="center">
            {[0, 200, 400].map((delay) => (
              <Box
                key={delay}
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  backgroundColor: '#999',
                  animation: 'vectiqor-bounce 1.4s infinite',
                  animationDelay: `${delay}ms`,
                }}
              />
            ))}
          </Group>
        </Box>
      </Group>
    </>
  )
}

interface Props {
  messages: Message[]
  isSending: boolean
  onSuggestedQuestion: (question: string, model: ModelId) => void
  model: ModelId
  sessionReady: boolean
}

export function ChatArea({ messages, isSending, onSuggestedQuestion, model, sessionReady }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isSending])

  return (
    <Box
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
          {isSending && <TypingIndicator model={model} />}
        </>
      )}
      <div ref={bottomRef} />
    </Box>
  )
}
