import { ActionIcon, Button, Divider, Group, Stack, Text, Tooltip } from '@mantine/core'
import { AccountSelector } from '../sidebar/AccountSelector'
import { ModelSelector } from '../sidebar/ModelSelector'
import { ConversationList } from '../sidebar/ConversationList'
import type { Account, ConversationSummary, ModelId } from '../../types'

interface Props {
  accounts: Account[]
  selectedAccountId: string | null
  onSelectAccount: (id: string) => void
  isInitializing: boolean
  isEmbedded: boolean
  collapsed: boolean
  onToggleCollapsed: () => void
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
  isEmbedded,
  collapsed,
  onToggleCollapsed,
  model,
  onModelChange,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
}: Props) {
  if (collapsed) {
    return (
      <Stack align="center" gap="sm" py="xs">
        <Tooltip label="New conversation" position="right">
          <ActionIcon
            variant="filled"
            color="finoutBlue"
            size="lg"
            onClick={onNewConversation}
            aria-label="New conversation"
          >
            <Text size="lg" fw={700}>+</Text>
          </ActionIcon>
        </Tooltip>
        <Tooltip label="Expand sidebar" position="right">
          <ActionIcon
            variant="subtle"
            color="gray"
            size="lg"
            onClick={onToggleCollapsed}
            aria-label="Expand sidebar"
          >
            <Text size="sm" fw={700}>{'>>'}</Text>
          </ActionIcon>
        </Tooltip>
      </Stack>
    )
  }

  return (
    <Stack gap="md" style={{ height: '100%', overflow: 'hidden' }}>
      <Group justify="space-between" align="center">
        {!isEmbedded ? (
          <img src="/billy-banner-transparent.png" alt="Billy" height={56} style={{ objectFit: 'contain' }} />
        ) : (
          <div />
        )}
        <Tooltip label="Collapse sidebar" position="right">
          <ActionIcon
            variant="subtle"
            color="gray"
            size="lg"
            onClick={onToggleCollapsed}
            aria-label="Collapse sidebar"
          >
            <Text size="sm" fw={700}>{'<<'}</Text>
          </ActionIcon>
        </Tooltip>
      </Group>

      {!isEmbedded && (
        <AccountSelector
          accounts={accounts}
          value={selectedAccountId}
          onChange={onSelectAccount}
          disabled={isInitializing}
        />
      )}

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
