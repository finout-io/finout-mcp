import { useCallback } from 'react'
import { Accordion, Badge, Box, Button, Code, Group, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import type { ToolCall } from '../../types'

interface Props {
  toolCall: ToolCall
  index: number
}

function extractCurl(output: unknown): string | string[] | null {
  try {
    const parsed = typeof output === 'string' ? JSON.parse(output) : output
    if (parsed && typeof parsed === 'object' && '_debug_curl' in parsed) {
      return (parsed as Record<string, unknown>)['_debug_curl'] as string | string[]
    }
  } catch {
    // not JSON or no _debug_curl
  }
  return null
}

export function ToolCallCard({ toolCall, index }: Props) {
  const hasError = toolCall.error === true
  const curl = extractCurl(toolCall.output)

  const copyCurl = useCallback(() => {
    if (!curl) return
    const text = Array.isArray(curl) ? curl.join('\n\n') : curl
    navigator.clipboard.writeText(text).then(
      () => notifications.show({ message: '✓ Copied', color: 'teal', autoClose: 1500 }),
      () => notifications.show({ message: 'Failed to copy', color: 'red', autoClose: 1500 }),
    )
  }, [curl])

  return (
    <Box
      style={(theme) => ({
        border: `1px solid ${hasError ? theme.colors.red[7] : theme.colors.dark[4]}`,
        borderRadius: theme.radius.md,
        overflow: 'hidden',
        marginTop: theme.spacing.xs,
      })}
    >
      <Accordion variant="default" chevronPosition="right">
        <Accordion.Item value={`tool-${index}`}>
          <Accordion.Control>
            <Group gap="xs">
              <Badge size="sm" color={hasError ? 'red' : 'teal'} variant="light">
                tool
              </Badge>
              <Text size="sm" fw={500}>
                {toolCall.name}
              </Text>
              {hasError && (
                <Badge size="sm" color="red" variant="filled">
                  error
                </Badge>
              )}
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="xs">
              <Box>
                <Text size="xs" c="dimmed" mb={4}>Input</Text>
                <Code block style={{ fontSize: 12 }}>
                  {JSON.stringify(toolCall.input, null, 2)}
                </Code>
              </Box>
              {toolCall.output !== undefined && (
                <Box>
                  <Text size="xs" c={hasError ? 'red' : 'dimmed'} mb={4}>
                    {hasError ? 'Error' : 'Output'}
                  </Text>
                  <Code block style={{ fontSize: 12 }}>
                    {typeof toolCall.output === 'string'
                      ? toolCall.output
                      : JSON.stringify(toolCall.output, null, 2)}
                  </Code>
                </Box>
              )}
              {curl && (
                <Button size="xs" variant="subtle" color="gray" onClick={copyCurl}>
                  📋 Copy curl
                </Button>
              )}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Box>
  )
}
