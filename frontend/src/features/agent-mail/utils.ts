import type {
  MailMemberResponse,
  MailMemberStatus,
  MailMessageKind,
  MailMessageResponse,
  MailRequestStatus,
} from '@/types/agentMail'

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

export function sessionSourceLabel(source: string): string {
  if (source === 'observed') return 'Bridge'
  if (source === 'mcp') return 'MCP'
  if (source === 'hook') return 'Hooks'
  return source
}

export function sessionSourceTitle(source: string): string {
  if (source === 'observed') return 'Discovered by Agent Bridge from a tmux pane.'
  if (source === 'mcp') return 'Registered by an Agent Mail MCP tool call.'
  if (source === 'hook') return 'Registered by Claude Code Agent Mail hooks.'
  return source
}

export function requestBadgeClass(status?: MailRequestStatus | null): string {
  if (status === 'pending') return 'border-amber-300 bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
  if (status === 'answered') return 'border-blue-300 bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
  if (status === 'acknowledged') return 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
  return 'border-muted-foreground/30 bg-muted text-muted-foreground'
}

export function formatDateTime(value?: string | null): string {
  if (!value) return 'Never'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
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
