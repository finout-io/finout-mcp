import { apiFetch } from './client'
import type { WhatsNewResponse } from '../types'

export async function getWhatsNew(): Promise<WhatsNewResponse> {
  return apiFetch<WhatsNewResponse>('/api/whats-new')
}
