import { Box, Center, Group, Stack, Text } from '@mantine/core'
import { ToolCallCard } from './ToolCallCard'
import { ChartPanel } from './ChartPanel'
import type { Message } from '../../types'

function modelEmoji(model?: string): string {
  if (!model) return '🤖'
  if (model.includes('haiku')) return '⚡'
  if (model.includes('opus')) return '👑'
  return '🤖'
}

function modelLabel(model?: string): string {
  if (!model) return 'Assistant'
  if (model.includes('haiku')) return 'Haiku 4.5'
  if (model.includes('opus')) return 'Opus 4.6'
  return 'Sonnet 4.5'
}

interface Props {
  message: Message
}

export function ChatMessage({ message }: Props) {
  const isUser = message.role === 'user'

  const avatar = (
    <Center
      style={(theme) => ({
        width: 36,
        height: 36,
        borderRadius: '50%',
        fontSize: 18,
        flexShrink: 0,
        backgroundColor: isUser ? theme.colors.finoutTeal[6] : '#FFD632',
      })}
    >
      {isUser ? '👤' : modelEmoji(message.model)}
    </Center>
  )

  return (
    <Group
      align="flex-start"
      gap="xs"
      style={{ flexDirection: isUser ? 'row-reverse' : 'row', marginBottom: 16 }}
    >
      {avatar}
      <Box
        style={(theme) => ({
          maxWidth: '75%',
          minWidth: 60,
          padding: `${theme.spacing.sm} ${theme.spacing.md}`,
          borderRadius: theme.radius.lg,
          backgroundColor: isUser ? theme.colors.finoutTeal[6] : theme.colors.dark[6],
          color: theme.white,
        })}
      >
        <Stack gap="xs">
          <Text size="sm" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {message.content}
          </Text>

          {!isUser && message.tool_calls?.map((tc, idx) => (
            <ChartPanel key={idx} output={tc.output} />
          ))}

          {message.tool_calls && message.tool_calls.length > 0 && (
            <Stack gap={4}>
              {message.tool_calls.map((tc, idx) => (
                <ToolCallCard key={idx} toolCall={tc} index={idx} />
              ))}
            </Stack>
          )}

          {/* Timing + usage bar (assistant only) */}
          {!isUser && (message.usage || message.total_time) && (
            <Group
              gap="xs"
              mt={4}
              p="xs"
              style={(theme) => ({
                background: 'rgba(0,0,0,0.15)',
                borderRadius: theme.radius.sm,
                flexWrap: 'wrap',
              })}
            >
              <Text size="xs" fw={600} c="dimmed">
                {modelLabel(message.model)}
              </Text>

              {message.tool_time != null && message.tool_time > 0 && message.total_time != null && (
                <>
                  <Text size="xs" c="orange">🔧 {message.tool_time.toFixed(1)}s</Text>
                  <Text size="xs" c="dimmed">
                    💭 {(message.total_time - message.tool_time).toFixed(1)}s
                  </Text>
                </>
              )}

              {message.usage?.total_tokens != null && (
                <Text size="xs" c="teal.4">
                  🧮 {message.usage.total_tokens.toLocaleString()} tokens
                </Text>
              )}

              {message.usage?.estimated_cost_usd != null && (
                <Text size="xs" fw={700} c="teal.3">
                  ~${message.usage.estimated_cost_usd.toFixed(4)}
                </Text>
              )}

              {message.total_time != null && (
                <Text size="xs" c="dimmed" style={{ marginLeft: 'auto', fontFamily: 'monospace' }}>
                  {message.total_time.toFixed(1)}s total
                </Text>
              )}
            </Group>
          )}
        </Stack>
      </Box>
    </Group>
  )
}
