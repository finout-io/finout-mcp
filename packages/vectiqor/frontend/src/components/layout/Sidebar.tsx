import { Button, Divider, Group, Image, Stack, Text } from '@mantine/core'
import { AccountSelector } from '../sidebar/AccountSelector'
import { ModelSelector } from '../sidebar/ModelSelector'
import { ConversationList } from '../sidebar/ConversationList'
import type { Account, ConversationSummary, ModelId } from '../../types'

interface Props {
  accounts: Account[]
  selectedAccountId: string | null
  onSelectAccount: (id: string) => void
  isInitializing: boolean
  model: ModelId
  onModelChange: (model: ModelId) => void
  activeConversationId?: string
  onSelectConversation: (conversation: ConversationSummary) => void
  onNewConversation: () => void
}

export function Sidebar({
  accounts,
  selectedAccountId,
  onSelectAccount,
  isInitializing,
  model,
  onModelChange,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
}: Props) {
  return (
    <Stack gap="md" style={{ height: '100%', overflow: 'hidden' }}>
      {/* Brand logo */}
      <Group justify="center">
        <Image
          src="/vectiqor-logo.svg"
          alt="Vectiqor"
          h={52}
          fit="contain"
          fallbackSrc="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='52'%3E%3Crect width='100%25' height='100%25' fill='%2325272b'/%3E%3Ctext x='50%25' y='54%25' text-anchor='middle' fill='%23E6E8ED' font-family='Arial' font-weight='700' font-size='22'%3EVECTIQOR%3C/text%3E%3C/svg%3E"
        />
      </Group>

      <AccountSelector
        accounts={accounts}
        value={selectedAccountId}
        onChange={onSelectAccount}
        disabled={isInitializing}
      />

      <ModelSelector value={model} onChange={onModelChange} />

      <Button
        variant="light"
        color="finoutTeal"
        size="sm"
        fullWidth
        onClick={onNewConversation}
      >
        New conversation
      </Button>

      <Divider />

      <Text size="xs" c="dimmed" fw={500}>
        Saved conversations
      </Text>

      <ConversationList
        accountId={selectedAccountId}
        activeId={activeConversationId}
        onSelect={onSelectConversation}
      />
    </Stack>
  )
}
