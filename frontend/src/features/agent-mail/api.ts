import { apiClient, buildEndpoint } from '@/lib/api'
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

export function sendAgentMailMessage(message: MailMessageCreate): Promise<MailMessageResponse> {
  return apiClient<MailMessageResponse>('agent-mail/messages', {
    method: 'POST',
    body: JSON.stringify(message),
  })
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

export function ackAgentMailMessage(messageId: number, memberId: number): Promise<{ ok: boolean }> {
  return apiClient<{ ok: boolean }>(`agent-mail/messages/${messageId}/ack`, {
    method: 'POST',
    body: JSON.stringify({ member_id: memberId }),
  })
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

export function fetchAgentMailSnippets(): Promise<AgentMailSnippets> {
  return apiClient<AgentMailSnippets>('agent-mail/install/snippets')
}
