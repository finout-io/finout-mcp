import { apiFetch } from './client'
import type { ToolsResponse } from '../types'

export async function getTools(): Promise<ToolsResponse> {
  return apiFetch<ToolsResponse>('/api/tools')
}
