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
    />
  )
}
