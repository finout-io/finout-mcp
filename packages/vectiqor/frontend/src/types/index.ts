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
  model: string
  messages: Message[]
  tool_calls: ToolCall[]
  user_note?: string
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
}

export interface ChatResponse {
  response: string
  tool_calls: ToolCall[]
  usage: TokenUsage
  tool_time: number
}

export type ModelId =
  | 'claude-haiku-4-5-20251001'
  | 'claude-sonnet-4-5-20250929'
  | 'claude-opus-4-6'

export interface ModelOption {
  value: ModelId
  label: string
}

export const MODEL_OPTIONS: ModelOption[] = [
  { value: 'claude-haiku-4-5-20251001', label: 'Haiku' },
  { value: 'claude-sonnet-4-5-20250929', label: 'Sonnet' },
  { value: 'claude-opus-4-6', label: 'Opus' },
]

export interface FeedbackStats {
  total_count: number
  avg_rating: number
  positive_count: number
  negative_count: number
  by_query_type: Record<string, number>
}
