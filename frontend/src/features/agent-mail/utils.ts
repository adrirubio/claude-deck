import type {
  MailMemberResponse,
  MailMemberStatus,
  MailMessageKind,
  MailMessageResponse,
  MailRequestStatus,
} from '@/types/agentMail'
import { formatServerTime } from '@/lib/serverTime'

export const KIND_LABEL: Record<MailMessageKind, string> = {
  message: 'Message',
  broadcast: 'Broadcast',
  context_request: 'Context request',
  handoff: 'Handoff',
  answer: 'Answer',
}

export function memberName(members: MailMemberResponse[], memberId?: number | null): string {
  if (!memberId) return 'Director'
  return members.find((member) => member.id === memberId)?.display_name ?? `Member ${memberId}`
}

/** Who a message came from, read only from its sender_type (#527, #639). */
export type SenderKind = 'deck' | 'director' | 'legacy' | 'external' | 'agent' | 'unknown'

export function senderKind(message: MailMessageResponse): SenderKind {
  switch (message.sender_type) {
    case 'system': return 'deck'
    case 'director': return 'director'
    case 'legacy': return 'legacy'
    case 'external_actor': return 'external'
    case 'member': return 'agent'
    default: return 'unknown'
  }
}

export const LEGACY_SENDER_LABEL = 'Deck or Director (recorded before v3.1)'

/**
 * The sender label. Deck's own messages say Deck, never Director. A sender
 * with no known type reads "Unknown sender". The label grants no authority.
 */
export function senderName(message: MailMessageResponse, members: MailMemberResponse[]): string {
  switch (senderKind(message)) {
    case 'deck': return 'Deck'
    case 'director': return 'Director'
    case 'legacy': return message.sender_name || LEGACY_SENDER_LABEL
    case 'external': return message.sender_name || 'External actor'
    case 'agent': return message.sender_member_id
      ? memberName(members, message.sender_member_id)
      : message.sender_name || 'Unknown sender'
    default: return 'Unknown sender'
  }
}

export function senderTypeLabel(message: MailMessageResponse): string | null {
  if (message.sender_type === 'external_actor') {
    if (message.sender_actor_kind === 'external_tool') return 'External'
    return message.sender_actor_kind || 'External'
  }
  return null
}

export function recipientName(message: MailMessageResponse, members: MailMemberResponse[]): string {
  if (message.kind === 'broadcast' || !message.recipient_member_id) return 'All members'
  return memberName(members, message.recipient_member_id)
}

export function statusBadgeClass(status: MailMemberStatus | string): string {
  if (status === 'connected') return 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
  if (status === 'observed') return 'border-blue-300 bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
  return 'border-muted-foreground/30 bg-muted text-muted-foreground'
}

export function statusLabel(status: MailMemberStatus | string): string {
  if (status === 'connected') return 'Connected'
  if (status === 'observed') return 'Observed only'
  if (status === 'offline') return 'Offline'
  return status
}

export function statusTitle(status: MailMemberStatus | string): string {
  if (status === 'connected') return 'This repo has checked in through Agent Mail.'
  if (status === 'observed') return 'Agent Bridge sees a tmux session, but Agent Mail has not received an MCP or hook check-in.'
  if (status === 'offline') return 'No recent Agent Mail check-in or live Agent Bridge observation.'
  return status
}

export function wakeMethodLabel(method: string): string {
  if (method === 'tmux') return 'tmux'
  return method
}

export function sessionSourceLabel(source: string): string {
  if (source === 'observed') return 'Bridge'
  if (source === 'mcp') return 'MCP'
  if (source === 'hook') return 'Hooks'
  return source
}

export function sessionSourceTitle(source: string): string {
  if (source === 'observed') return 'Discovered by Agent Bridge from a tmux pane.'
  if (source === 'mcp') return 'Registered by an Agent Mail MCP tool call.'
  if (source === 'hook') return 'Registered by Agent Mail lifecycle hooks.'
  return source
}

export function sessionStatusLabel(source: string, status: MailMemberStatus | string): string {
  if (source === 'hook' && status === 'connected') return 'Recent event'
  if (source === 'hook' && status === 'offline') return 'No recent event'
  return statusLabel(status)
}

export function sessionStatusTitle(source: string, status: MailMemberStatus | string): string {
  if (source === 'hook' && status === 'connected') return 'A lifecycle hook checked in recently.'
  if (source === 'hook' && status === 'offline') return 'No recent lifecycle hook event has checked in. This does not mean the agent is disconnected.'
  return statusTitle(status)
}

export function requestBadgeClass(status?: MailRequestStatus | null): string {
  if (status === 'pending') return 'border-amber-300 bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
  if (status === 'answered') return 'border-blue-300 bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
  if (status === 'acknowledged') return 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
  return 'border-muted-foreground/30 bg-muted text-muted-foreground'
}

export function formatDateTime(value?: string | null): string {
  if (!value) return 'Never'
  return formatServerTime(value, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function messageSummary(message: MailMessageResponse): string {
  const compact = message.body_markdown.replace(/\s+/g, ' ').trim()
  if (compact.length <= 180) return compact
  return `${compact.slice(0, 177)}...`
}

export function splitLines(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}
