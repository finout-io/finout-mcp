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
      <Text size="xs" fw={500} style={{ color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
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
            backgroundColor: '#2a3244',
            border: '1px solid #3d4a5c',
          },
          label: { color: '#e2e8f0' },
          indicator: { backgroundColor: '#3d4a5c' },
        }}
      />
    </Stack>
  )
}
