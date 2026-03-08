import { Select } from '@mantine/core'
import type { Account } from '../../types'

interface Props {
  accounts: Account[]
  value: string | null
  onChange: (accountId: string) => void
  disabled?: boolean
}

export function AccountSelector({ accounts, value, onChange, disabled }: Props) {
  const options = accounts.map((a) => ({ value: a.accountId, label: a.name }))

  return (
    <Select
      label="Account"
      placeholder="Select account…"
      data={options}
      value={value}
      onChange={(v) => v && onChange(v)}
      disabled={disabled}
      searchable
      radius="md"
      size="sm"
      styles={{
        label: { color: 'rgba(255,255,255,0.6)', fontSize: 11, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.05em' },
        input: {
          backgroundColor: 'rgba(255,255,255,0.08)',
          border: '1px solid rgba(255,255,255,0.15)',
          color: '#ffffff',
        },
      }}
    />
  )
}
