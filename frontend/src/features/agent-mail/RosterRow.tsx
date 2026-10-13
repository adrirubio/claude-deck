import { useId, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { AgentStatusBadges } from '@/components/shared/AgentStatusBadges'
import { Badge } from '@/components/ui/badge'
import type { MailMemberResponse, MailMessageKind } from '@/types/agentMail'
import { RowMenu, type RowMenuItem } from './RowMenu'
import { displaySessions, harnessLabel, notAcknowledged } from './roster'
import {
  formatDateTime,
  sessionSourceLabel,
  sessionSourceTitle,
  sessionStatusLabel,
  sessionStatusTitle,
  statusBadgeClass,
  wakeMethodLabel,
} from './utils'

interface RosterRowProps {
  member: MailMemberResponse
  onEdit: (member: MailMemberResponse) => void
  onCompose: (kind: Exclude<MailMessageKind, 'answer' | 'broadcast'>, member: MailMemberResponse) => void
  onQueueInboxCheck: (member: MailMemberResponse) => void
  nudging: boolean
}

function Detail({ member }: { member: MailMemberResponse }) {
  const sessions = displaySessions(member.sessions)
  const wakeMethods = (member.wake_methods ?? []).map(wakeMethodLabel).join(', ')
  const warnings = [
    member.unseen_pending_count > 0
      ? `${member.unseen_pending_count} pending request(s) have not been read by this agent.`
      : null,
    member.stale_pending_count > 0 ? `${member.stale_pending_count} pending request(s) are stale.` : null,
    !member.can_nudge && (member.unread_count > 0 || member.pending_count > 0)
      ? 'No wake path is available; the visible agent must check its inbox.'
      : null,
  ].filter(Boolean)
  return (
    <div className="space-y-3 border-t bg-muted/30 px-4 py-3 text-sm">
      <div className="grid gap-3 md:grid-cols-3">
        <div>
          <p className="text-xs font-medium uppercase text-muted-foreground">Role</p>
          <p className="mt-1">{member.role || 'Unassigned'}</p>
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase text-muted-foreground">Repo</p>
          <p className="mt-1 break-all">{member.repo_name}</p>
          <p className="break-all text-xs text-muted-foreground">{member.repo_path}</p>
        </div>
        <div>
          <p className="text-xs font-medium uppercase text-muted-foreground">Inbox check</p>
          <p className="mt-1">{formatDateTime(member.last_inbox_checked_at)}</p>
          <AgentStatusBadges status={member.agent_status} className="mt-2" />
          {member.agent_status?.wake_state === 'can_wake' && wakeMethods && (
            <p className="text-xs text-muted-foreground" title="How Deck wakes this agent.">Wake method: {wakeMethods}</p>
          )}
        </div>
      </div>
      {warnings.length > 0 && (
        <div className="rounded-lg border border-amber-300/60 bg-amber-50/60 px-3 py-2 text-amber-800 dark:bg-amber-950/20 dark:text-amber-200">
          {warnings.join(' ')}
        </div>
      )}
      {member.charter && <p className="rounded-lg bg-muted/50 p-3 leading-6">{member.charter}</p>}
      <div className="space-y-2">
        <p className="text-xs font-medium uppercase text-muted-foreground">Sessions ({sessions.length})</p>
        {sessions.length > 0 ? sessions.map((session) => (
          <div key={session.id} className="flex flex-col gap-2 rounded-lg border bg-background px-3 py-2 md:flex-row md:items-center md:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" title={sessionSourceTitle(session.source)}>{sessionSourceLabel(session.source)}</Badge>
                {session.bridgeObserved && (
                  <Badge variant="secondary" title="Agent Bridge also observes this session from tmux.">Bridge observed</Badge>
                )}
                {session.team_preset_name && (
                  <Badge variant="outline" title={session.team_slot_name ? `Slot: ${session.team_slot_name}` : undefined}>
                    {session.team_slot_name ? `${session.team_preset_name} / ${session.team_slot_name}` : session.team_preset_name}
                  </Badge>
                )}
                <span className="font-medium">{session.provider}</span>
                <span className="text-xs text-muted-foreground">{formatDateTime(session.last_seen_at)}</span>
              </div>
              <p className="mt-1 truncate text-xs text-muted-foreground">{session.activity || session.cwd || session.session_key}</p>
            </div>
            <Badge variant="outline" className={statusBadgeClass(session.mailbox_status)} title={sessionStatusTitle(session.source, session.mailbox_status)}>
              {sessionStatusLabel(session.source, session.mailbox_status)}
            </Badge>
          </div>
        )) : (
          <div className="rounded-lg border border-dashed px-3 py-3 text-muted-foreground">No sessions observed for this participant.</div>
        )}
      </div>
    </div>
  )
}

/**
 * #530: one compact row for one member. The charter, the paths and the
 * sessions stay out of the DOM until the row is expanded.
 */
export function RosterRow({ member, onEdit, onCompose, onQueueInboxCheck, nudging }: RosterRowProps) {
  const [open, setOpen] = useState(false)
  const detailId = useId()
  const waiting = notAcknowledged(member)
  const canQueue = member.can_nudge && (member.unread_count > 0 || member.pending_count > 0)
  const items: RowMenuItem[] = [
    { label: 'Message', onSelect: () => onCompose('message', member) },
    { label: 'Edit', onSelect: () => onEdit(member) },
    { label: 'Request context', onSelect: () => onCompose('context_request', member) },
    { label: 'Handoff', onSelect: () => onCompose('handoff', member) },
    ...(canQueue ? [{ label: nudging ? 'Queueing…' : 'Queue inbox check', onSelect: () => onQueueInboxCheck(member), disabled: nudging }] : []),
  ]
  return (
    <li className="border-b last:border-b-0" data-testid="roster-row">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-1.5 min-[1400px]:flex-nowrap">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={detailId}
          aria-label={`${open ? 'Hide' : 'Show'} details of ${member.display_name}`}
          onClick={() => setOpen((value) => !value)}
          className="rounded p-1 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {open ? <ChevronDown aria-hidden="true" className="h-4 w-4" /> : <ChevronRight aria-hidden="true" className="h-4 w-4" />}
        </button>
        <div className="min-w-[10rem] flex-1 basis-40">
          <span className="block truncate font-semibold">{member.display_name}</span>
          {member.role && <span className="block truncate text-xs leading-tight text-muted-foreground">{member.role}</span>}
        </div>
        <span className="w-28 shrink-0 truncate text-sm text-muted-foreground">{harnessLabel(member)}</span>
        <span className="w-52 shrink-0 whitespace-nowrap text-xs text-muted-foreground">checked mail {formatDateTime(member.last_inbox_checked_at)}</span>
        <AgentStatusBadges status={member.agent_status} compact className="shrink-0 flex-nowrap" />
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5 min-[1400px]:w-44">
          {waiting > 0 && (
            <Badge variant="outline" className="whitespace-nowrap border-amber-300 text-amber-700 dark:text-amber-300">
              ⚠ {waiting} not acknowledged
            </Badge>
          )}
          {member.unread_count > 0 && <Badge variant="secondary">{member.unread_count} unread</Badge>}
        </div>
        <RowMenu label={`Actions for ${member.display_name}`} items={items} />
      </div>
      {open && <div id={detailId}><Detail member={member} /></div>}
    </li>
  )
}
