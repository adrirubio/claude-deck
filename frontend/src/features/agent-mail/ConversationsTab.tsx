import { Search, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { teamBadgeClass } from '@/features/factory/auditFeed'
import type { MailMemberResponse, MailMessageResponse } from '@/types/agentMail'
import { SenderLabel } from './SenderLabel'
import {
  CHIPS,
  NO_TEAM_LABEL,
  chipMatches,
  scopeConversations,
  type ChipId,
  type Conversation,
} from './conversations'
import { formatDateTime, requestBadgeClass } from './utils'

/** The API returns this many thread roots at most. A full list may hide older threads. */
export const CONVERSATION_LIMIT = 100

interface ConversationsTabProps {
  conversations: Conversation[]
  members: MailMemberResponse[]
  loading: boolean
  search: string
  chip: ChipId
  team: string
  recipientMemberId: number | null
  messageCount: number
  onSearchChange: (value: string) => void
  onChipChange: (value: ChipId) => void
  onClearRecipient: () => void
  onOpenThread: (message: MailMessageResponse) => void
}

function ConversationRow({ row, members, onOpen }: {
  row: Conversation
  members: MailMemberResponse[]
  onOpen: () => void
}) {
  return (
    <li
      data-testid="conversation-row"
      className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-3 py-1 text-sm transition-colors hover:border-primary/50"
      onClick={onOpen}
    >
      <Badge variant="outline" className={cn('shrink-0 text-xs', teamBadgeClass(row.team))}>
        {row.team ?? NO_TEAM_LABEL}
      </Badge>
      <button
        type="button"
        className="min-w-[10rem] flex-1 truncate rounded text-left font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        title={row.subject}
      >
        {row.subject}
      </button>
      {row.notice && row.count > 1 && (
        <Badge variant="secondary" aria-label={`${row.count} notices`}>×{row.count}</Badge>
      )}
      <span className="flex shrink-0 items-center gap-1 text-muted-foreground">
        <SenderLabel message={row.message} members={members} />
        <span role="img" aria-label="to">→</span>
        <span>{row.recipient}</span>
      </span>
      {row.state && (
        <Badge variant="outline" className={requestBadgeClass(row.message.request_status)}>{row.state}</Badge>
      )}
      {row.stale && (
        <Badge variant="outline" className="border-amber-300 text-amber-700 dark:text-amber-300">stale</Badge>
      )}
      <span className="w-28 shrink-0 text-right text-xs text-muted-foreground">{formatDateTime(row.lastAt)}</span>
    </li>
  )
}

/**
 * #529: one compact row for each thread. The chips narrow the list; the team
 * and recipient filters come from the page. A click opens the thread dialog.
 */
export function ConversationsTab({
  conversations,
  members,
  loading,
  search,
  chip,
  team,
  recipientMemberId,
  messageCount,
  onSearchChange,
  onChipChange,
  onClearRecipient,
  onOpenThread,
}: ConversationsTabProps) {
  const scoped = scopeConversations(conversations, { search, team, recipientMemberId }, members)
  const rows = scoped.filter((row) => chipMatches(row, chip))
  const recipient = recipientMemberId != null ? members.find((member) => member.id === recipientMemberId) : undefined

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div role="group" aria-label="Filter the conversations" className="flex flex-wrap gap-2">
          {CHIPS.map(({ id, label }) => (
            <Button
              key={id}
              size="sm"
              variant={chip === id ? 'default' : 'outline'}
              aria-pressed={chip === id}
              onClick={() => onChipChange(id)}
            >
              {label} ({scoped.filter((row) => chipMatches(row, id)).length})
            </Button>
          ))}
        </div>
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search subjects, senders, recipients, body"
            aria-label="Search conversations"
            className="h-9 pl-9"
          />
        </div>
      </div>

      {recipient && (
        <p className="flex items-center gap-2 text-sm">
          <span>Showing conversations for <span className="font-medium">{recipient.display_name}</span></span>
          <Button size="sm" variant="ghost" className="h-7" onClick={onClearRecipient}>
            <X aria-hidden="true" className="mr-1 h-4 w-4" />
            Show all
          </Button>
        </p>
      )}

      <ul aria-label="Conversations" className="space-y-1">
        {rows.map((row) => (
          <ConversationRow key={row.key} row={row} members={members} onOpen={() => onOpenThread(row.message)} />
        ))}
      </ul>

      {rows.length === 0 && (
        <p className="rounded-lg border border-dashed py-10 text-center text-sm text-muted-foreground">
          {loading ? 'Loading messages...' : 'No conversations match the current filters.'}
        </p>
      )}
      {messageCount >= CONVERSATION_LIMIT && (
        <p className="text-xs text-muted-foreground">
          Deck loads the newest {CONVERSATION_LIMIT} threads. Older threads are not listed here.
        </p>
      )}
    </div>
  )
}
