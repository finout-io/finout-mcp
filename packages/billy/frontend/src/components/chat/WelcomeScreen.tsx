import { useMemo } from 'react'
import { Box, Button, Image, Skeleton, Stack, Text, Title } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { getSuggestedQueries } from '../../api/suggestions'

const FALLBACK_QUESTIONS = [
  'What are my top 5 most expensive services this month?',
  'Show me my AWS cost trend for the last 30 days',
  'Which teams are spending the most on infrastructure?',
  'What is my estimated end-of-month spend?',
  'Show me anomalies in my recent cloud spending',
  'How much did I spend on compute vs storage last month?',
]

const GREETINGS = [
  'What cloud mysteries shall we uncover today?',
  'Ready to hunt down some sneaky cloud costs?',
  'Your cloud costs called — they want to be understood.',
  "Let's find where the money's hiding today.",
  'Another day, another dollar (or a few thousand in the cloud).',
  "Cloud costs don't stand a chance against us.",
]

function getGreeting(userName?: string): { title: string; subtitle: string } {
  const greeting = GREETINGS[Math.floor(Math.random() * GREETINGS.length)]!
  const hour = new Date().getHours()
  let timeOfDay = 'Hey'
  if (hour < 12) timeOfDay = 'Good morning'
  else if (hour < 17) timeOfDay = 'Good afternoon'
  else timeOfDay = 'Good evening'

  const title = userName ? `${timeOfDay}, ${userName.split(' ')[0]}!` : 'Ask Billy'
  return { title, subtitle: greeting }
}

interface Props {
  onQuestion: (question: string) => void
  disabled?: boolean
  accountId?: string | null
  userName?: string
}

export function WelcomeScreen({ onQuestion, disabled, accountId, userName }: Props) {
  const { data: dynamicQueries, isLoading } = useQuery({
    queryKey: ['suggested-queries', accountId],
    queryFn: () => getSuggestedQueries(accountId!),
    enabled: !!accountId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  })

  const questions: string[] = dynamicQueries ?? FALLBACK_QUESTIONS
  // Stabilize greeting so it doesn't re-randomize on every render
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const { title, subtitle } = useMemo(() => getGreeting(userName), [userName, accountId])

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
        <Image
          src="/billy-welcome.png"
          alt="Billy mascot"
          maw={260}
          radius="md"
        />
        <Title order={2} ta="center" style={{ color: '#1e293b' }}>
          {title}
        </Title>
        <Text ta="center" size="sm" style={{ color: '#64748b' }}>
          {subtitle}
        </Text>
      </Stack>

      <Stack gap="xs" style={{ width: '100%', maxWidth: 560 }}>
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} height={40} radius="sm" />
            ))
          : questions.map((q) => (
              <Button
                key={q}
                variant="light"
                color="finoutBlue"
                size="sm"
                fullWidth
                onClick={() => onQuestion(q)}
                disabled={disabled}
                style={{
                  textAlign: 'left',
                  height: 'auto',
                  padding: '8px 16px',
                  backgroundColor: '#ffffff',
                  border: '1px solid #e2e8f0',
                  color: '#1e293b',
                }}
              >
                <Text size="sm" style={{ whiteSpace: 'normal', color: '#1e293b' }}>
                  {q}
                </Text>
              </Button>
            ))}
      </Stack>
    </Box>
  )
}
