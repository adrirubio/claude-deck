import { apiClient, buildEndpoint, type ApiError } from '@/lib/api'
import { API_BASE_URL } from '@/lib/constants'
import type { AgentProviderId } from '@/types/providers'
import type {
  BridgeAttachment,
  BridgeAttachmentDeleteResponse,
  BridgeAttachmentListResponse,
  BridgeAttachmentPasteRequest,
  BridgeAttachmentPasteResponse,
  CCSessionsResponse,
  CCPreviewResponse,
  CCTokenResponse,
  CodexLaunchOptionsResponse,
  SpawnSessionRequest,
  SpawnSessionResponse,
  KillSessionResponse,
} from './types'

const BASE = 'agent-bridge'

function apiErrorMessage(error: ApiError, fallback = 'An error occurred'): string {
  if (error.message) return error.message
  if (typeof error.detail === 'string') return error.detail
  if (Array.isArray(error.detail)) {
    const messages = error.detail.map((item) => item.msg).filter(Boolean)
    if (messages.length > 0) return messages.join(', ')
  }
  if (error.detail && typeof error.detail === 'object' && 'msg' in error.detail && error.detail.msg) {
    return error.detail.msg
  }
  return fallback
}

async function attachmentRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const { token } = await fetchTerminalToken()
  const headers = new Headers(options.headers)
  headers.set('X-Claude-Deck-Terminal-Token', token)
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const error: ApiError = await response.json().catch(() => ({
      message: `HTTP ${response.status}: ${response.statusText}`,
    }))
    throw new Error(apiErrorMessage(error))
  }

  return response.json()
}

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

export async function uploadBridgeAttachment(
  target: string,
  file: File
): Promise<BridgeAttachment> {
  const form = new FormData()
  form.append('file', file)
  form.append('created_by', 'deck-ui')
  return attachmentRequest<BridgeAttachment>(
    `${BASE}/sessions/${encodeURIComponent(target)}/attachments`,
    {
      method: 'POST',
      body: form,
    }
  )
}

export async function listBridgeAttachments(target: string): Promise<BridgeAttachmentListResponse> {
  return attachmentRequest<BridgeAttachmentListResponse>(
    `${BASE}/sessions/${encodeURIComponent(target)}/attachments`
  )
}

export async function pasteBridgeAttachment(
  target: string,
  attachmentId: number,
  request: BridgeAttachmentPasteRequest
): Promise<BridgeAttachmentPasteResponse> {
  return attachmentRequest<BridgeAttachmentPasteResponse>(
    `${BASE}/sessions/${encodeURIComponent(target)}/attachments/${attachmentId}/paste`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    }
  )
}

export async function deleteBridgeAttachment(
  target: string,
  attachmentId: number
): Promise<BridgeAttachmentDeleteResponse> {
  return attachmentRequest<BridgeAttachmentDeleteResponse>(
    `${BASE}/sessions/${encodeURIComponent(target)}/attachments/${attachmentId}`,
    { method: 'DELETE' }
  )
}
