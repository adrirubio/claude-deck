import { forwardRef, useState } from 'react'
import { AlertTriangle, Circle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { buildWaiting, waitingDetail } from './conversations'
import type { MailMemberResponse } from '@/types/agentMail'

export const WAITING_PANEL_ID = 'waiting-on-someone'
const VISIBLE_ITEMS = 3

interface WaitingPanelProps {
  members: MailMemberResponse[]
  loading: boolean
  /** The recipient that the conversations list now shows. */
  recipientMemberId: number | null
  onShowRecipient: (memberId: number) => void
}

/**
 * #529: who has mail that waits, with the online state of the recipient. The
 * panel reads the counts that each member already carries. A button filters
 * the conversations to that recipient.
 */
export const WaitingPanel = forwardRef<HTMLElement, WaitingPanelProps>(function WaitingPanel(
  { members, loading, recipientMemberId, onShowRecipient },
  ref,
) {
  const [expanded, setExpanded] = useState(false)
  const items = buildWaiting(members)
  const shown = expanded ? items : items.slice(0, VISIBLE_ITEMS)
  return (
    <section
      ref={ref}
      id={WAITING_PANEL_ID}
      tabIndex={-1}
      aria-labelledby="waiting-on-someone-title"
      className="rounded-lg border px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <h2 id="waiting-on-someone-title" className="text-sm font-semibold">
        Waiting on someone ({items.length})
      </h2>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {loading ? 'Loading messages...' : 'Nobody is waiting on anyone.'}
        </p>
      ) : (
        <ul className="mt-1 divide-y">
          {shown.map((item) => (
            <li key={item.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-0.5 text-sm">
              {item.warn ? (
                <AlertTriangle role="img" aria-label="Needs attention" className="h-4 w-4 shrink-0 text-amber-700 dark:text-amber-300" />
              ) : (
                <Circle aria-hidden="true" className="h-2 w-2 shrink-0 fill-current text-muted-foreground" />
              )}
              <span className={cn('min-w-0 font-medium', item.warn && 'text-amber-800 dark:text-amber-300')}>{item.text}</span>
              <span className="min-w-0 text-muted-foreground">{waitingDetail(item)}</span>
              <Button
                size="sm"
                variant="ghost"
                className="ml-auto h-6"
                aria-pressed={recipientMemberId === item.memberId}
                aria-label={`Show conversations for ${item.name}`}
                onClick={() => onShowRecipient(item.memberId)}
              >
                Show
              </Button>
            </li>
          ))}
        </ul>
      )}
      {items.length > VISIBLE_ITEMS && (
        <Button size="sm" variant="ghost" className="mt-1 h-7" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
          {expanded ? 'Show fewer' : `Show all ${items.length}`}
        </Button>
      )}
    </section>
  )
})
