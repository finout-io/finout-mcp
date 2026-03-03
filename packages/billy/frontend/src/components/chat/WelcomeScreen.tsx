import { Box, Button, Stack, Text, Title } from '@mantine/core'

const SUGGESTED_QUESTIONS = [
  'What are my top 5 most expensive services this month?',
  'Show me my AWS cost trend for the last 30 days',
  'Which teams are spending the most on infrastructure?',
  'What is my estimated end-of-month spend?',
  'Show me anomalies in my recent cloud spending',
  'How much did I spend on compute vs storage last month?',
]

interface Props {
  onQuestion: (question: string) => void
  disabled?: boolean
}

export function WelcomeScreen({ onQuestion, disabled }: Props) {
  return (
    <Box
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '32px 16px',
        gap: 24,
      }}
    >
      <Stack align="center" gap="xs">
        <Title order={2} ta="center">
          Ask Finout AI
        </Title>
        <Text c="dimmed" ta="center" size="sm">
          Get instant insights into your cloud spending
        </Text>
      </Stack>

      <Stack gap="xs" style={{ width: '100%', maxWidth: 560 }}>
        {SUGGESTED_QUESTIONS.map((q) => (
          <Button
            key={q}
            variant="default"
            size="sm"
            fullWidth
            onClick={() => onQuestion(q)}
            disabled={disabled}
            style={{ textAlign: 'left', height: 'auto', padding: '8px 16px' }}
          >
            <Text size="sm" style={{ whiteSpace: 'normal' }}>
              {q}
            </Text>
          </Button>
        ))}
      </Stack>
    </Box>
  )
}
