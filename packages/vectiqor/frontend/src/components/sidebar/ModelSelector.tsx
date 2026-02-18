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
      <Text size="xs" c="dimmed" fw={500}>
        Model
      </Text>
      <SegmentedControl
        size="xs"
        fullWidth
        value={value}
        onChange={(v) => onChange(v as ModelId)}
        data={MODEL_OPTIONS.map((m) => ({ value: m.value, label: m.label }))}
      />
    </Stack>
  )
}
