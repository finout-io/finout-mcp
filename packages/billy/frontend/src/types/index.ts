export type MessageRole = 'user' | 'assistant'

export interface ToolCall {
  name: string
  input: Record<string, unknown>
  output?: unknown
  error?: boolean
}

export interface TokenUsage {
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
  total_tokens: number
  estimated_cost_usd: number
  model?: string
}

export interface Message {
  role: MessageRole
  content: string
  thinking_trace?: string
  tool_calls?: ToolCall[]
  usage?: TokenUsage
  model?: string
  tool_time?: number
  total_time?: number
}

export interface Account {
  accountId: string
  name: string
}

export interface Conversation {
  id: string
  name: string
  account_id: string
  account_name?: string
  model: string
  messages: Message[]
  tool_calls: ToolCall[]
  user_note?: string
  user_email?: string
  created_at: string
  updated_at: string
  share_token?: string
}

export interface ConversationSummary {
  id: string
  name: string
  account_id: string
  model: string
  created_at: string
  updated_at: string
  share_token?: string
  user_note?: string
  user_email?: string
}

export interface ChatResponse {
  response: string
  request_id?: string
  tool_calls: ToolCall[]
  usage: TokenUsage
  tool_time: number
}

export type ModelId =
  | 'claude-haiku-4-5-20251001'
  | 'claude-sonnet-4-6'
  | 'claude-opus-4-6'

export interface ModelOption {
  value: ModelId
  label: string
}

export const MODEL_OPTIONS: ModelOption[] = [
  { value: 'claude-haiku-4-5-20251001', label: 'Haiku' },
  { value: 'claude-sonnet-4-6', label: 'Sonnet' },
  { value: 'claude-opus-4-6', label: 'Opus' },
]

export interface WhatsNewEntry {
  version: string
  date: string
  title: string
  sections: {
    external_mcp: string[]
    internal_mcp: string[]
    billy: string[]
  }
}

export interface WhatsNewResponse {
  app: string
  current_version: string
  entries: WhatsNewEntry[]
}

export interface ToolEntry {
  name: string
  category: string
  availability: 'public' | 'internal'
  description: string
  when_to_use: string[]
  example_prompts: string[]
  key_params: string[]
  workflow: string | null
}

export interface ToolsResponse {
  tools: ToolEntry[]
}
