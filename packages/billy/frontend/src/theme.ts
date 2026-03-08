import { createTheme, MantineColorsTuple } from '@mantine/core'

const finoutBlue: MantineColorsTuple = [
  '#eff6ff',
  '#dbeafe',
  '#bfdbfe',
  '#93c5fd',
  '#60a5fa',
  '#3b82f6',
  '#2563eb',
  '#1d4ed8',
  '#1e40af',
  '#1e3a8a',
]

const finoutTeal: MantineColorsTuple = [
  '#e6f7f3',
  '#ccefe7',
  '#99dfcf',
  '#66cfb7',
  '#38B28E',
  '#2d9176',
  '#22705e',
  '#175046',
  '#0c302e',
  '#011016',
]

export const theme = createTheme({
  primaryColor: 'finoutBlue',
  colors: {
    finoutBlue,
    finoutTeal,
  },
  defaultRadius: 'md',
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  components: {
    Button: {
      defaultProps: {
        radius: 'md',
      },
    },
    TextInput: {
      defaultProps: {
        radius: 'md',
      },
    },
    Select: {
      defaultProps: {
        radius: 'md',
      },
    },
    Card: {
      defaultProps: {
        withBorder: false,
      },
      styles: {
        root: {
          backgroundColor: '#ffffff',
          border: '1px solid #e9ecef',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        },
      },
    },
  },
})
