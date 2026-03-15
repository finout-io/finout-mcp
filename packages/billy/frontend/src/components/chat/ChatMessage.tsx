import { Box, Center, Group, Stack, Text } from '@mantine/core'
import { ToolCallCard } from './ToolCallCard'
import { ChartPanel } from './ChartPanel'
import { MermaidPanel } from './MermaidPanel'
import { MarkdownRenderer } from './MarkdownRenderer'
import type { Message } from '../../types'
import { billyAvatarUrl } from '../../assets/images'

function modelLabel(model?: string): string {
  if (!model) return 'Assistant'
  if (model.includes('haiku')) return 'Haiku 4.5'
  if (model.includes('opus')) return 'Opus 4.6'
  return 'Sonnet 4.6'
}

interface Props {
  message: Message
  isEmbedded?: boolean
}

export function ChatMessage({ message, isEmbedded }: Props) {
  const isUser = message.role === 'user'

  const avatar = isUser ? (
    <Center
      style={(theme) => ({
        width: 36,
        height: 36,
        borderRadius: '50%',
        fontSize: 18,
        flexShrink: 0,
        backgroundColor: theme.colors.finoutBlue[6],
      })}
    >
      {'👤'}
    </Center>
  ) : (
    <img
      src={billyAvatarUrl}
      alt="Billy"
      width={36}
      height={36}
      style={{ flexShrink: 0 }}
    />
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
          backgroundColor: isUser ? theme.colors.finoutBlue[6] : '#ffffff',
          color: isUser ? '#ffffff' : '#1e293b',
          border: isUser ? 'none' : '1px solid #e2e8f0',
          boxShadow: isUser ? 'none' : '0 1px 3px rgba(0,0,0,0.08)',
        })}
      >
        <Stack gap="xs">
          {isUser ? (
            <Text size="sm" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: '#ffffff' }}>
              {message.content}
            </Text>
          ) : (
            <MarkdownRenderer content={message.content} size="sm" />
          )}

          {!isUser && message.tool_calls?.filter((tc) => tc.name === 'render_chart').map((tc, idx) => (
            <ChartPanel
              key={`${tc.name}-${idx}-${JSON.stringify(tc.input ?? {}).length}`}
              output={tc.output}
            />
          ))}

          {!isUser && message.tool_calls?.filter((tc) => ['analyze_virtual_tags', 'get_object_usages', 'check_delete_safety'].includes(tc.name)).map((tc, idx) => (
            <MermaidPanel key={idx} output={tc.output} />
          ))}

          {!isUser && !isEmbedded && (
            (message.thinking_trace?.trim().length ?? 0) > 0 ||
            (message.tool_calls && message.tool_calls.length > 0) ||
            message.usage ||
            message.total_time
          ) && (
            <Box
              component="details"
              style={(theme) => ({
                fontSize: theme.fontSizes.xs,
                color: theme.colors.gray[6],
                border: '1px solid #e2e8f0',
                borderRadius: theme.radius.sm,
                padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
              })}
            >
              <Box
                component="summary"
                style={{
                  cursor: 'pointer',
                  userSelect: 'none',
                  fontWeight: 600,
                  opacity: 0.9,
                }}
              >
                Diagnostics
                {message.total_time != null && (
                  <Text component="span" size="xs" c="dimmed" ml="xs" style={{ fontWeight: 400 }}>
                    {message.total_time.toFixed(1)}s
                    {message.usage?.estimated_cost_usd != null && ` · ~$${message.usage.estimated_cost_usd.toFixed(4)}`}
                  </Text>
                )}
              </Box>

              <Stack gap="xs" mt="xs">
                {message.thinking_trace && message.thinking_trace.trim().length > 0 && (
                  <Box
                    component="details"
                    style={(theme) => ({
                      fontSize: theme.fontSizes.xs,
                      color: theme.colors.gray[6],
                    })}
                  >
                    <Box
                      component="summary"
                      style={{ cursor: 'pointer', userSelect: 'none', fontWeight: 600, opacity: 0.9 }}
                    >
                      Thinking
                    </Box>
                    <Box
                      component="pre"
                      style={(theme) => ({
                        margin: `${theme.spacing.xs} 0 0`,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        fontSize: theme.fontSizes.xs,
                        lineHeight: 1.35,
                        color: theme.colors.gray[7],
                        maxHeight: 260,
                        overflowY: 'auto',
                      })}
                    >
                      {message.thinking_trace}
                    </Box>
                  </Box>
                )}

                {message.tool_calls && message.tool_calls.length > 0 && (
                  <Stack gap={4}>
                    {message.tool_calls.map((tc, idx) => (
                      <ToolCallCard key={idx} toolCall={tc} index={idx} />
                    ))}
                  </Stack>
                )}

                {(message.usage || message.total_time) && (
                  <Group
                    gap="xs"
                    p="xs"
                    style={(theme) => ({
                      background: '#f8fafc',
                      borderRadius: theme.radius.sm,
                      flexWrap: 'wrap',
                      border: '1px solid #e2e8f0',
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
                      <Text size="xs" c="teal.6">
                        🧮 {message.usage.total_tokens.toLocaleString()} tokens
                      </Text>
                    )}

                    {message.usage?.estimated_cost_usd != null && (
                      <Text size="xs" fw={700} c="teal.7">
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
          )}
        </Stack>
      </Box>
    </Group>
  )
}
