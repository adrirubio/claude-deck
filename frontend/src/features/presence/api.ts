import { apiClient } from '@/lib/api'
import type { PresenceSessionList, PresenceSession, PresenceConfigSnippet } from '@/types/presence'

const BASE = 'presence'

export async function fetchPresenceSessions(): Promise<PresenceSessionList> {
  return apiClient<PresenceSessionList>(`${BASE}/sessions`)
}

export async function updateSessionLabel(sessionId: string, label: string): Promise<PresenceSession> {
  return apiClient<PresenceSession>(`${BASE}/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ label }),
  })
}

export async function removeSession(sessionId: string): Promise<void> {
  await apiClient<Record<string, never>>(`${BASE}/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
}

export async function clearAllSessions(): Promise<void> {
  await apiClient<Record<string, never>>(`${BASE}/sessions`, {
    method: 'DELETE',
  })
}

export async function fetchConfigSnippet(): Promise<PresenceConfigSnippet> {
  return apiClient<PresenceConfigSnippet>(`${BASE}/config-snippet`)
}

export function buildPresenceWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}/api/v1/${BASE}/ws`
}
