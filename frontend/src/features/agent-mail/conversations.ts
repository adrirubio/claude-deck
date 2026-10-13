import type { MailMemberResponse, MailMessageResponse } from '@/types/agentMail'
import { memberName, senderName } from './utils'

// #529: the Conversations tab and the "Waiting on someone" panel. This module
// only groups, counts and words what the page already loads. It sends nothing
// and changes no message. The list endpoint returns thread roots, so a thread
// is its root message and has no reply count.

export type ChipId = 'all' | 'to_you' | 'requests' | 'handoffs' | 'notices'

export const CHIPS: Array<{ id: ChipId; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'to_you', label: 'To you' },
  { id: 'requests', label: 'Requests' },
  { id: 'handoffs', label: 'Handoffs' },
  { id: 'notices', label: 'Deck notices' },
]

export const NO_TEAM_LABEL = 'No team'

export type ThreadState = 'Open' | 'Answered' | 'Acknowledged'

export interface Conversation {
  key: string
  /** The newest message of the thread (or of the collapsed notices). Opens the thread dialog. */
  message: MailMessageResponse
  subject: string
  recipient: string
  recipientMemberId: number | null
  toYou: boolean
  /** The team of the recipient, else of the sender. Null when neither is in a team. */
  team: string | null
  lastAt: string
  state: ThreadState | null
  stale: boolean
  /** Deck notices with the same subject and recipient collapse into one row. */
  notice: boolean
  count: number
}

function teamOf(member: MailMemberResponse | undefined): string | null {
  return member?.participant_kind === 'team_slot' && member.team_preset_name ? member.team_preset_name : null
}

function isToDirector(message: MailMessageResponse): boolean {
  return message.kind !== 'broadcast' && !message.recipient_member_id && message.audience_type === 'operator_global'
}

/** The recipient of a row. The Director reads "You", as in the mockup of screen 14. */
export function conversationRecipient(message: MailMessageResponse, members: MailMemberResponse[]): string {
  if (message.kind === 'broadcast') return 'All members'
  if (isToDirector(message)) return 'You'
  if (!message.recipient_member_id) return 'All members'
  return memberName(members, message.recipient_member_id)
}

function stateOf(message: MailMessageResponse): ThreadState | null {
  switch (message.request_status) {
    case 'pending': return 'Open'
    case 'answered': return 'Answered'
    case 'acknowledged': return 'Acknowledged'
    default: return null
  }
}

function isNotice(message: MailMessageResponse): boolean {
  return message.sender_type === 'system' && (message.kind === 'message' || message.kind === 'broadcast')
}

/** One row for each thread and one row for each group of Deck notices. Newest first. */
export function buildConversations(messages: MailMessageResponse[], members: MailMemberResponse[]): Conversation[] {
  const byId = new Map(members.map((member) => [member.id, member]))
  const rows = new Map<string, Conversation>()
  for (const message of messages) {
    const notice = isNotice(message)
    const subject = message.subject || message.body_markdown.replace(/\s+/g, ' ').trim().slice(0, 80) || `Message ${message.id}`
    const recipient = conversationRecipient(message, members)
    const key = notice
      ? `notice|${subject}|${message.kind === 'broadcast' ? 'all' : message.recipient_member_id ?? 'none'}`
      : `thread|${message.thread_root_id ?? message.id}`
    const team = teamOf(byId.get(message.recipient_member_id ?? -1)) ?? teamOf(byId.get(message.sender_member_id ?? -1))
    const existing = rows.get(key)
    if (!existing) {
      rows.set(key, {
        key,
        message,
        subject,
        recipient,
        recipientMemberId: message.kind === 'broadcast' ? null : message.recipient_member_id ?? null,
        toYou: isToDirector(message),
        team,
        lastAt: message.created_at,
        state: stateOf(message),
        stale: message.is_stale,
        notice,
        count: 1,
      })
      continue
    }
    existing.count += 1
    existing.stale = existing.stale || message.is_stale
    if (Date.parse(message.created_at) > Date.parse(existing.lastAt)) {
      existing.lastAt = message.created_at
      existing.message = message
      existing.state = stateOf(message)
    }
  }
  return [...rows.values()].sort((a, b) => Date.parse(b.lastAt) - Date.parse(a.lastAt))
}

export function chipMatches(row: Conversation, chip: ChipId): boolean {
  switch (chip) {
    case 'to_you': return row.toYou
    case 'requests': return row.message.kind === 'context_request'
    case 'handoffs': return row.message.kind === 'handoff'
    case 'notices': return row.notice
    default: return true
  }
}

export interface ConversationFilter {
  chip: ChipId
  search: string
  team: string
  recipientMemberId: number | null
}

export const ALL_TEAMS = ''

/** The team and recipient filters apply to the chip counts. The chip applies after them. */
export function scopeConversations(rows: Conversation[], filter: Pick<ConversationFilter, 'search' | 'team' | 'recipientMemberId'>, members: MailMemberResponse[]): Conversation[] {
  const needle = filter.search.trim().toLowerCase()
  return rows.filter((row) => {
    if (filter.team !== ALL_TEAMS && row.team !== filter.team) return false
    if (filter.recipientMemberId != null && row.recipientMemberId !== filter.recipientMemberId) return false
    if (!needle) return true
    const haystack = [
      row.subject,
      row.message.body_markdown,
      senderName(row.message, members),
      row.recipient,
      row.team ?? '',
    ].join(' ').toLowerCase()
    return haystack.includes(needle)
  })
}

/** The team names of the members, sorted. */
export function teamNames(members: MailMemberResponse[]): string[] {
  return [...new Set(members.map(teamOf).filter((name): name is string => name !== null))].sort((a, b) => a.localeCompare(b))
}

export function membersInTeam(members: MailMemberResponse[], team: string): MailMemberResponse[] {
  return team === ALL_TEAMS ? members : members.filter((member) => teamOf(member) === team)
}

export type PresenceWord = 'connected' | 'observed only' | 'offline'

export interface WaitingItem {
  key: string
  memberId: number
  name: string
  /** The sentence that says what waits. */
  text: string
  presence: PresenceWord
  team: string | null
  /** A warning mark: stale mail, or open requests to an offline member. */
  warn: boolean
  stale: number
  pending: number
  unread: number
}

function plural(count: number, one: string, many = `${one}s`): string {
  return count === 1 ? one : many
}

function presenceOf(member: MailMemberResponse): PresenceWord {
  if (member.status === 'connected') return 'connected'
  if (member.status === 'observed') return 'observed only'
  return 'offline'
}

/** One item for each member that has stale, open or unread mail. Warnings come first. */
export function buildWaiting(members: MailMemberResponse[]): WaitingItem[] {
  const items: WaitingItem[] = []
  for (const member of members) {
    const stale = member.stale_pending_count
    const pending = member.pending_count
    const unread = member.unread_count
    if (stale + pending + unread === 0) continue
    const name = member.display_name
    let text: string
    if (stale > 0) {
      text = `${stale} ${plural(stale, 'message')} to ${name} ${plural(stale, 'is', 'are')} not acknowledged`
    } else if (pending > 0) {
      text = `${pending} ${plural(pending, 'request')} to ${name} ${plural(pending, 'is', 'are')} waiting for an answer`
    } else {
      text = `${unread} unread ${plural(unread, 'message')} for ${name}`
    }
    const presence = presenceOf(member)
    items.push({
      key: `member-${member.id}`,
      memberId: member.id,
      name,
      text,
      presence,
      team: teamOf(member),
      warn: stale > 0 || (presence === 'offline' && pending > 0),
      stale,
      pending,
      unread,
    })
  }
  return items.sort((a, b) =>
    Number(b.warn) - Number(a.warn)
    || Number(b.stale + b.pending > 0) - Number(a.stale + a.pending > 0)
    || (b.stale + b.pending + b.unread) - (a.stale + a.pending + a.unread)
    || a.name.localeCompare(b.name))
}

/** The detail after the sentence: "B2 is offline · product-reposition-fork". */
export function waitingDetail(item: WaitingItem): string {
  const state = item.presence === 'offline' ? `${item.name} is offline` : item.presence === 'observed only' ? `${item.name} is observed only` : `${item.name} is connected`
  return `${state} · ${item.team ?? 'not in a team'}`
}
