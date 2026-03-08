import { SegmentedControl, Stack, Text } from '@mantine/core'
import { MODEL_OPTIONS } from '../../types'
import type { ModelId } from '../../types'

interface Props {
  value: ModelId
  onChange: (model: ModelId) => void
}

export function ModelSelector({ value, onChange }: Props) {
  return (
    <Stack gap={4}>
      <Text size="xs" fw={500} style={{ color: 'rgba(255,255,255,0.6)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Model
      </Text>
      <SegmentedControl
        size="xs"
        fullWidth
        value={value}
        onChange={(v) => onChange(v as ModelId)}
        data={MODEL_OPTIONS.map((m) => ({ value: m.value, label: m.label }))}
        styles={{
          root: {
            backgroundColor: 'rgba(255,255,255,0.08)',
            border: '1px solid rgba(255,255,255,0.15)',
          },
          label: { color: 'rgba(255,255,255,0.7)' },
          indicator: { backgroundColor: 'rgba(255,255,255,0.15)' },
        }}
      />
    </Stack>
  )
}
