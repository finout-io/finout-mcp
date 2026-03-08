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
          src="/billy-banner.png"
          alt="Billy"
          h={72}
          fit="contain"
          fallbackSrc="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='52'%3E%3Crect width='100%25' height='100%25' fill='%231a1f2e'/%3E%3Ctext x='50%25' y='54%25' text-anchor='middle' fill='%23ffffff' font-family='Arial' font-weight='700' font-size='22'%3EBILLY%3C/text%3E%3C/svg%3E"
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
        variant="filled"
        color="finoutBlue"
        size="sm"
        fullWidth
        onClick={onNewConversation}
      >
        New conversation
      </Button>

      <Divider style={{ borderColor: 'rgba(255,255,255,0.1)' }} />

      <Text size="xs" fw={500} style={{ color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
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
