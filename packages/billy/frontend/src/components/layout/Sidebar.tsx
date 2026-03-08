import { Button, Divider, Group, Stack, Text } from '@mantine/core'
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
      <Group justify="center" py="xs">
        <img src="/billy-banner-transparent.png" alt="Billy" height={56} style={{ objectFit: 'contain' }} />
      </Group>

      <AccountSelector
        accounts={accounts}
        value={selectedAccountId}
        onChange={onSelectAccount}
        disabled={isInitializing}
      />

      <ModelSelector value={model} onChange={onModelChange} />

      <Button
        variant="filled"
        color="finoutBlue"
        size="sm"
        fullWidth
        onClick={onNewConversation}
      >
        New conversation
      </Button>

      <Divider style={{ borderColor: '#2d3748' }} />

      <Text size="xs" fw={500} style={{ color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
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
