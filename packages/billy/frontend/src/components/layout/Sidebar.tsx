import { ActionIcon, Box, Button, Divider, Group, Stack, Text, Tooltip } from '@mantine/core'
import { AccountSelector } from '../sidebar/AccountSelector'
import { ModelSelector } from '../sidebar/ModelSelector'
import { ConversationList } from '../sidebar/ConversationList'
import type { Account, ConversationSummary, ModelId } from '../../types'
import { billyBannerUrl } from '../../assets/images'

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
  shareToken?: string
  onCopyShareLink?: () => void
}

function SidebarToggleIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path
        d={collapsed ? 'M4.5 3.5L8.5 7L4.5 10.5' : 'M9.5 3.5L5.5 7L9.5 10.5'}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d={collapsed ? 'M2.5 2.5V11.5' : 'M11.5 2.5V11.5'}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
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
  shareToken,
  onCopyShareLink,
}: Props) {
  if (collapsed) {
    return (
      <Box style={{ position: 'relative', height: '100%' }}>
        <Tooltip label="Expand sidebar" position="right">
          <ActionIcon
            variant="subtle"
            color="gray"
          size="sm"
          onClick={onToggleCollapsed}
          aria-label="Expand sidebar"
          style={{ position: 'absolute', top: 4, right: 4, zIndex: 1 }}
        >
          <SidebarToggleIcon collapsed />
        </ActionIcon>
      </Tooltip>
        <Stack align="center" gap="sm" pt={44} py="xs">
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
          {shareToken && onCopyShareLink && (
            <Tooltip label="Copy share link" position="right">
              <ActionIcon
                variant="subtle"
                color="gray"
                size="lg"
                onClick={onCopyShareLink}
                aria-label="Copy share link"
              >
                <Text size="md">🔗</Text>
              </ActionIcon>
            </Tooltip>
          )}
        </Stack>
      </Box>
    )
  }

  return (
    <Box style={{ position: 'relative', height: '100%' }}>
      <Tooltip label="Collapse sidebar" position="right">
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          onClick={onToggleCollapsed}
          aria-label="Collapse sidebar"
          style={{ position: 'absolute', top: 4, right: 4, zIndex: 1 }}
        >
          <SidebarToggleIcon collapsed={false} />
        </ActionIcon>
      </Tooltip>
      <Stack gap="md" style={{ height: '100%', overflow: 'hidden' }} pt="lg">
        <Group justify="space-between" align="center">
        {!isEmbedded ? (
          <img src={billyBannerUrl} alt="Billy" height={56} style={{ objectFit: 'contain' }} />
        ) : (
          <div />
        )}
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
    </Box>
  )
}
