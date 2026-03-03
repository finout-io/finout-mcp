import { Box, Text } from '@mantine/core'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

interface Props {
  content: string
  size?: 'xs' | 'sm'
}

export function MarkdownRenderer({ content, size = 'sm' }: Props) {
  const normalized = content.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  const tableClassName = 'vectiqor-md-table'

  const components: Components = {
    p: ({ children }) => (
      <Text size={size} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {children}
      </Text>
    ),
    h1: ({ children }) => <Text fw={700} size="md">{children}</Text>,
    h2: ({ children }) => <Text fw={700} size="md">{children}</Text>,
    h3: ({ children }) => <Text fw={700} size="sm">{children}</Text>,
    h4: ({ children }) => <Text fw={700} size="sm">{children}</Text>,
    h5: ({ children }) => <Text fw={700} size="xs">{children}</Text>,
    h6: ({ children }) => <Text fw={700} size="xs">{children}</Text>,
    ul: ({ children }) => <Box component="ul" style={{ margin: 0, paddingLeft: 20 }}>{children}</Box>,
    ol: ({ children }) => <Box component="ol" style={{ margin: 0, paddingLeft: 20 }}>{children}</Box>,
    li: ({ children }) => (
      <Text component="li" size={size} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {children}
      </Text>
    ),
    blockquote: ({ children }) => (
      <Box
        style={(theme) => ({
          borderLeft: `3px solid ${theme.colors.dark[3]}`,
          paddingLeft: theme.spacing.sm,
          color: theme.colors.gray[4],
        })}
      >
        {children}
      </Box>
    ),
    a: ({ href, children }) => (
      <Box
        component="a"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        style={(theme) => ({
          color: theme.colors.finoutTeal[4],
          textDecoration: 'underline',
        })}
      >
        {children}
      </Box>
    ),
    code: ({ children, className }) => (
      <Box
        component="code"
        style={(theme) => ({
          backgroundColor: theme.colors.dark[5],
          borderRadius: theme.radius.xs,
          padding: className ? theme.spacing.sm : '0 4px',
          fontFamily: 'monospace',
          whiteSpace: className ? 'pre-wrap' : 'normal',
          wordBreak: className ? 'break-word' : 'normal',
          display: className ? 'block' : 'inline',
          overflowX: className ? 'auto' : 'visible',
        })}
      >
        {children}
      </Box>
    ),
    pre: ({ children }) => <>{children}</>,
    table: ({ children }) => (
      <Box
        style={(theme) => ({
          overflowX: 'auto',
          border: `1px solid ${theme.colors.dark[4]}`,
          borderRadius: theme.radius.sm,
        })}
      >
        <Box
          component="table"
          className={tableClassName}
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            minWidth: 480,
          }}
        >
          {children}
        </Box>
      </Box>
    ),
    thead: ({ children }) => <Box component="thead">{children}</Box>,
    tbody: ({ children }) => <Box component="tbody">{children}</Box>,
    tr: ({ children }) => <Box component="tr">{children}</Box>,
    th: ({ children }) => (
      <Box
        component="th"
        style={(theme) => ({
          border: `1px solid ${theme.colors.dark[4]}`,
          padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
          backgroundColor: theme.colors.dark[5],
          textAlign: 'left',
          fontWeight: 700,
          fontSize: theme.fontSizes.xs,
          whiteSpace: 'nowrap',
        })}
      >
        {children}
      </Box>
    ),
    td: ({ children }) => (
      <Box
        component="td"
        style={(theme) => ({
          border: `1px solid ${theme.colors.dark[4]}`,
          padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
          fontSize: theme.fontSizes[size],
          verticalAlign: 'top',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        })}
      >
        {children}
      </Box>
    ),
  }

  return (
    <Box style={{ display: 'grid', gap: 8 }}>
      <style>
        {`
          .${tableClassName} tbody tr:nth-child(odd) td {
            background-color: transparent;
          }
          .${tableClassName} tbody tr:nth-child(even) td {
            background-color: rgba(255, 255, 255, 0.03);
          }
        `}
      </style>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {normalized}
      </ReactMarkdown>
    </Box>
  )
}
