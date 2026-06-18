import { apiClient, buildEndpoint } from '@/lib/api'
import type { AgentProviderId } from '@/types/providers'
import type {
  CCSessionsResponse,
  CCPreviewResponse,
  CCTokenResponse,
  CodexLaunchOptionsResponse,
  SpawnSessionRequest,
  SpawnSessionResponse,
  KillSessionResponse,
} from './types'

const BASE = 'agent-bridge'

export async function fetchCCSessions(provider?: AgentProviderId): Promise<CCSessionsResponse> {
  return apiClient<CCSessionsResponse>(buildEndpoint(BASE + '/sessions', { provider }))
}

export async function fetchSessionPreview(target: string): Promise<CCPreviewResponse> {
  return apiClient<CCPreviewResponse>(`${BASE}/sessions/${encodeURIComponent(target)}/preview`)
}

export async function fetchTerminalToken(): Promise<CCTokenResponse> {
  return apiClient<CCTokenResponse>(BASE + '/token')
}

export function buildTerminalWsUrl(target: string, token: string, mode: 'readonly' | 'interactive' = 'readonly'): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}/api/v1/${BASE}/sessions/${encodeURIComponent(target)}/terminal?token=${token}&mode=${mode}`
}

export async function spawnSession(request: SpawnSessionRequest): Promise<SpawnSessionResponse> {
  return apiClient<SpawnSessionResponse>(BASE + '/sessions', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export async function fetchCodexLaunchOptions(): Promise<CodexLaunchOptionsResponse> {
  return apiClient<CodexLaunchOptionsResponse>('providers/codex-cli/launch-options')
}

export async function killSession(target: string, cleanupWorktree: boolean = false): Promise<KillSessionResponse> {
  const params = cleanupWorktree ? '?cleanup_worktree=true' : ''
  return apiClient<KillSessionResponse>(`${BASE}/sessions/${encodeURIComponent(target)}${params}`, {
    method: 'DELETE',
  })
}
