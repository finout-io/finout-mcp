import { createTheme, MantineColorsTuple } from '@mantine/core'

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
  primaryColor: 'finoutTeal',
  colors: {
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
  },
})
