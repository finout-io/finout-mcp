import { useState, useCallback, KeyboardEvent } from 'react'
import { ActionIcon, Group, Stack, Textarea, Tooltip } from '@mantine/core'
import { useVoiceInput } from '../../hooks/useVoiceInput'
import type { ModelId } from '../../types'

interface Props {
  onSend: (content: string, model: ModelId) => void
  model: ModelId
  disabled?: boolean
  loading?: boolean
}

export function ChatInput({ onSend, model, disabled, loading }: Props) {
  const [value, setValue] = useState('')
  const voice = useVoiceInput()

  const handleSend = useCallback(() => {
    const trimmed = value.trim()
    if (!trimmed || disabled || loading) return
    onSend(trimmed, model)
    setValue('')
  }, [value, disabled, loading, onSend, model])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (!loading && e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend, loading],
  )

  const handleVoice = useCallback(() => {
    if (voice.isListening) {
      voice.stop()
    } else {
      voice.start((transcript) => {
        setValue((prev) => (prev ? `${prev} ${transcript}` : transcript))
      })
    }
  }, [voice])

  return (
    <Stack gap="xs">
      <Group gap="xs" align="flex-end">
        <Textarea
          style={{ flex: 1 }}
          placeholder={disabled ? 'Select an account to start chatting…' : 'Ask a question… (Enter to send, Shift+Enter for newline)'}
          value={value}
          onChange={(e) => setValue(e.currentTarget.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          autosize
          minRows={1}
          maxRows={8}
          radius="md"
        />
        {voice.isSupported && (
          <Tooltip label={voice.isListening ? 'Stop recording' : 'Voice input'}>
            <ActionIcon
              size="lg"
              variant={voice.isListening ? 'filled' : 'default'}
              color={voice.isListening ? 'red' : undefined}
              onClick={handleVoice}
              disabled={disabled}
              radius="md"
            >
              🎤
            </ActionIcon>
          </Tooltip>
        )}
        <Tooltip label="Send (Enter)">
          <ActionIcon
            size="lg"
            variant="filled"
            color="finoutTeal"
            onClick={handleSend}
            disabled={disabled || loading || !value.trim()}
            loading={loading}
            radius="md"
          >
            ↑
          </ActionIcon>
        </Tooltip>
      </Group>
    </Stack>
  )
}
