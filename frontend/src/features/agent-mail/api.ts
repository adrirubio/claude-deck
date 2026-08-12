import { apiClient, buildEndpoint } from '@/lib/api'
import { actorFetch } from './actorAuth'
import type {
  AgentMailInstallStatus,
  AgentMailSnippets,
  MailInboxResponse,
  MailMemberResponse,
  MailMemberUpdate,
  MailMessageCreate,
  MailMessageResponse,
  MailThreadResponse,
  TeamListResponse,
} from '@/types/agentMail'

export function fetchAgentMailTeam(sync = true): Promise<TeamListResponse> {
  return apiClient<TeamListResponse>(buildEndpoint('agent-mail/team', { sync }))
}

export function updateAgentMailMember(
  memberId: number,
  update: MailMemberUpdate
): Promise<MailMemberResponse> {
  return apiClient<MailMemberResponse>(`agent-mail/members/${memberId}`, {
    method: 'PATCH',
    body: JSON.stringify(update),
  })
}

interface ExternalSendResponse {
  message: MailMessageResponse
  delivery_state: string
}

export async function sendAgentMailMessage(
  message: MailMessageCreate
): Promise<MailMessageResponse> {
  const payload = (message.payload ?? {}) as Record<string, unknown>
  const base = {
    recipient_member_id: message.recipient_member_id ?? undefined,
    subject: message.subject ?? undefined,
    body_markdown: message.body_markdown,
  }
  const routes: Record<string, { path: string; body: Record<string, unknown> }> = {
    message: { path: 'external/agent-mail/messages', body: base },
    broadcast: { path: 'external/agent-mail/broadcasts', body: base },
    context_request: {
      path: 'external/agent-mail/context-requests',
      body: {
        ...base,
        why_needed: payload.why_needed ?? null,
        files_or_symbols: payload.files_or_symbols ?? [],
      },
    },
    handoff: {
      path: 'external/agent-mail/handoffs',
      body: { ...base, files: payload.files ?? [], next_steps: payload.next_steps ?? [] },
    },
  }
  const route = message.kind ? routes[message.kind] : undefined
  if (!route) {
    throw new Error(`The Deck UI cannot send kind "${message.kind ?? 'unset'}"`)
  }
  const response = await actorFetch<ExternalSendResponse>(route.path, {
    method: 'POST',
    body: JSON.stringify(route.body),
  })
  return response.message
}

export function fetchAgentMailMessages(): Promise<MailMessageResponse[]> {
  return apiClient<MailMessageResponse[]>('agent-mail/messages')
}

export function fetchAgentMailThread(
  messageId: number,
  memberId?: number
): Promise<MailThreadResponse> {
  return apiClient<MailThreadResponse>(
    buildEndpoint(`agent-mail/messages/${messageId}/thread`, { member_id: memberId })
  )
}

export function fetchAgentMailInbox(memberId: number, unreadOnly = false): Promise<MailInboxResponse> {
  return apiClient<MailInboxResponse>(
    buildEndpoint('agent-mail/agent/inbox', {
      member_id: memberId,
      unread_only: unreadOnly,
    })
  )
}

export function markAgentMailRead(messageId: number, memberId: number): Promise<{ ok: boolean }> {
  return apiClient<{ ok: boolean }>(`agent-mail/messages/${messageId}/read`, {
    method: 'POST',
    body: JSON.stringify({ member_id: memberId }),
  })
}

export function queueAgentMailInboxCheck(
  memberId: number
): Promise<{ ok: boolean; method?: string; target: string; prompt: string; turn_id?: string }> {
  return apiClient<{ ok: boolean; method?: string; target: string; prompt: string; turn_id?: string }>(
    `agent-mail/members/${memberId}/queue-inbox-check`,
    { method: 'POST' }
  )
}

export async function replyInAgentMailThread(
  rootId: number,
  bodyMarkdown: string
): Promise<MailMessageResponse> {
  const response = await actorFetch<ExternalSendResponse>(
    `external/agent-mail/threads/${rootId}/replies`,
    { method: 'POST', body: JSON.stringify({ body_markdown: bodyMarkdown }) }
  )
  return response.message
}

export async function ackAgentMailRequest(
  rootId: number
): Promise<{ request_status: string }> {
  return actorFetch<{ request_status: string }>(
    `external/agent-mail/requests/${rootId}/actor-ack`,
    { method: 'POST' }
  )
}

export function fetchAgentMailInstallStatus(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>('agent-mail/install/status')
}

export function applyClaudeCodeAgentMailInstall(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>('agent-mail/install/claude-code/apply', {
    method: 'POST',
    body: JSON.stringify({ confirmed: true }),
  })
}

export function uninstallClaudeCodeAgentMail(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>('agent-mail/install/claude-code/uninstall', {
    method: 'POST',
    body: JSON.stringify({ confirmed: true }),
  })
}

export function applyCodexAgentMailInstall(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>('agent-mail/install/codex/apply', {
    method: 'POST',
    body: JSON.stringify({ confirmed: true }),
  })
}

export function uninstallCodexAgentMail(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>('agent-mail/install/codex/uninstall', {
    method: 'POST',
    body: JSON.stringify({ confirmed: true }),
  })
}

export function applyCopilotAgentMailInstall(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>('agent-mail/install/copilot/apply', {
    method: 'POST',
    body: JSON.stringify({ confirmed: true }),
  })
}

export function uninstallCopilotAgentMail(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>('agent-mail/install/copilot/uninstall', {
    method: 'POST',
    body: JSON.stringify({ confirmed: true }),
  })
}

export function applyOpenCodeAgentMailInstall(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>('agent-mail/install/opencode/apply', {
    method: 'POST',
    body: JSON.stringify({ confirmed: true }),
  })
}

export function uninstallOpenCodeAgentMail(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>('agent-mail/install/opencode/uninstall', {
    method: 'POST',
    body: JSON.stringify({ confirmed: true }),
  })
}

export function fetchAgentMailSnippets(): Promise<AgentMailSnippets> {
  return apiClient<AgentMailSnippets>('agent-mail/install/snippets')
}
