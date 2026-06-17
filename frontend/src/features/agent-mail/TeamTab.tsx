import { BellRing, Edit3, Handshake, HelpCircle, Mail, Search } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type {
  MailMemberResponse,
  MailMemberStatus,
  MailMessageKind,
  MailSessionResponse,
} from '@/types/agentMail'
import {
  formatDateTime,
  sessionSourceLabel,
  sessionSourceTitle,
  sessionStatusLabel,
  sessionStatusTitle,
  statusBadgeClass,
  statusLabel,
  statusTitle,
  wakeMethodLabel,
  wakeStateBadgeClass,
  wakeStateLabel,
  wakeStateTitle,
} from './utils'

export type TeamStatusFilter = 'all' | MailMemberStatus

type DisplaySession = MailSessionResponse & {
  bridgeObserved: boolean
}

interface TeamTabProps {
  members: MailMemberResponse[]
  loading: boolean
  repoSearch: string
  statusFilter: TeamStatusFilter
  onRepoSearchChange: (value: string) => void
  onStatusFilterChange: (value: TeamStatusFilter) => void
  onEdit: (member: MailMemberResponse) => void
  onCompose: (kind: Exclude<MailMessageKind, 'answer' | 'broadcast'>, member: MailMemberResponse) => void
  onQueueInboxCheck: (member: MailMemberResponse) => void
  nudgingMemberId?: number | null
}

function sameRuntime(session: MailSessionResponse, observation: MailSessionResponse): boolean {
  return Boolean(
    session.provider === observation.provider &&
      session.cwd &&
      observation.cwd &&
      session.cwd === observation.cwd
  )
}

function hasConnectedReplacement(session: MailSessionResponse, sessions: MailSessionResponse[]): boolean {
  if (session.source !== 'mcp' || session.mailbox_status !== 'offline') {
    return false
  }
  return sessions.some(
    (candidate) =>
      candidate.id !== session.id &&
      candidate.source === 'mcp' &&
      candidate.mailbox_status === 'connected' &&
      sameRuntime(candidate, session)
  )
}

function displaySessions(sessions: MailSessionResponse[]): DisplaySession[] {
  const bridgeObservations = sessions.filter((session) => session.source === 'observed')
  const foldedBridgeIds = new Set<number>()
  const supersededSessionIds = new Set(
    sessions
      .filter((session) => hasConnectedReplacement(session, sessions))
      .map((session) => session.id)
  )

  const communicativeSessions = sessions.filter((session) => !supersededSessionIds.has(session.id)).map((session) => {
    if (session.source === 'observed' || session.mailbox_status !== 'connected') {
      return { ...session, bridgeObserved: false }
    }

    const bridgeObservation = bridgeObservations.find(
      (observation) => !foldedBridgeIds.has(observation.id) && sameRuntime(session, observation)
    )
    if (!bridgeObservation) {
      return { ...session, bridgeObserved: false }
    }

    foldedBridgeIds.add(bridgeObservation.id)
    return { ...session, bridgeObserved: true }
  })

  return communicativeSessions.filter((session) => !foldedBridgeIds.has(session.id))
}

export function TeamTab({
  members,
  loading,
  repoSearch,
  statusFilter,
  onRepoSearchChange,
  onStatusFilterChange,
  onEdit,
  onCompose,
  onQueueInboxCheck,
  nudgingMemberId,
}: TeamTabProps) {
  const normalizedSearch = repoSearch.trim().toLowerCase()
  const filtered = members.filter((member) => {
    const matchesStatus = statusFilter === 'all' || member.status === statusFilter
    const haystack = [
      member.display_name,
      member.role ?? '',
      member.charter ?? '',
      member.repo_name,
      member.repo_path,
      member.team_preset_name ?? '',
      member.team_slot_name ?? '',
      member.participant_kind,
    ].join(' ').toLowerCase()
    return matchesStatus && (!normalizedSearch || haystack.includes(normalizedSearch))
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={repoSearch}
            onChange={(event) => onRepoSearchChange(event.target.value)}
            placeholder="Search repos, roles, charters"
            className="pl-9"
          />
        </div>
        <Select value={statusFilter} onValueChange={(value) => onStatusFilterChange(value as TeamStatusFilter)}>
          <SelectTrigger className="w-full md:w-[180px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="connected">Connected</SelectItem>
            <SelectItem value="observed">Observed only</SelectItem>
            <SelectItem value="offline">Offline</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {filtered.length > 0 ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {filtered.map((member) => {
            const visibleSessions = displaySessions(member.sessions)
            const wakeState = member.wake_state ?? (member.status === 'offline' ? 'offline' : 'delivered_waiting')
            const wakeMethods = member.wake_methods ?? []
            const deliveryWarnings = [
              member.unseen_pending_count > 0
                ? `${member.unseen_pending_count} pending request(s) have not been read by this agent.`
                : null,
              member.stale_pending_count > 0
                ? `${member.stale_pending_count} pending request(s) are stale.`
                : null,
              !member.can_nudge && (member.unread_count > 0 || member.pending_count > 0)
                ? 'No wake path is available; the visible agent must check its inbox.'
                : null,
            ].filter(Boolean)
            const showQueueInboxCheck = member.can_nudge && (member.unread_count > 0 || member.pending_count > 0)
            const wakeMethodText = wakeMethods.map(wakeMethodLabel).join(', ')

            return (
              <Card key={member.id} className="rounded-lg">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <CardTitle className="truncate text-lg">{member.display_name}</CardTitle>
                        {member.participant_kind === 'team_slot' && (
                          <Badge variant="outline" title={member.team_preset_name ?? undefined}>
                            Team slot
                          </Badge>
                        )}
                      </div>
                      <p className="truncate text-sm text-muted-foreground">{member.repo_path}</p>
                      {member.team_preset_name && (
                        <p className="truncate text-xs text-muted-foreground">
                          {member.team_slot_name
                            ? `${member.team_preset_name} / ${member.team_slot_name}`
                            : member.team_preset_name}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-wrap justify-end gap-2">
                      <Badge
                        variant="outline"
                        className={statusBadgeClass(member.status)}
                        title={statusTitle(member.status)}
                      >
                        {statusLabel(member.status)}
                      </Badge>
                      {wakeState !== 'offline' && (
                        <Badge
                          variant="outline"
                          className={wakeStateBadgeClass(wakeState)}
                          title={wakeStateTitle(wakeState)}
                        >
                          {wakeStateLabel(wakeState)}
                          {wakeMethodText ? `: ${wakeMethodText}` : ''}
                        </Badge>
                      )}
                      {member.pending_count > 0 && (
                        <Badge variant="outline" className="border-amber-300 text-amber-700">
                          {member.pending_count} pending
                        </Badge>
                      )}
                      {member.unseen_pending_count > 0 && (
                        <Badge variant="outline" className="border-blue-300 text-blue-700">
                          {member.unseen_pending_count} unseen
                        </Badge>
                      )}
                      {member.stale_pending_count > 0 && (
                        <Badge variant="outline" className="border-amber-300 text-amber-700">
                          {member.stale_pending_count} stale
                        </Badge>
                      )}
                      {member.unread_count > 0 && (
                        <Badge variant="secondary">{member.unread_count} unread</Badge>
                      )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    <div>
                      <p className="text-xs font-medium uppercase text-muted-foreground">Role</p>
                      <p className="mt-1 text-sm">{member.role || 'Unassigned'}</p>
                    </div>
                    <div>
                      <p className="text-xs font-medium uppercase text-muted-foreground">Repo</p>
                      <p className="mt-1 text-sm">{member.repo_name}</p>
                    </div>
                    <div>
                      <p className="text-xs font-medium uppercase text-muted-foreground">Inbox check</p>
                      <p className="mt-1 text-sm">{formatDateTime(member.last_inbox_checked_at)}</p>
                    </div>
                  </div>
                  {deliveryWarnings.length > 0 && (
                    <div className="rounded-lg border border-amber-300/60 bg-amber-50/60 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/20 dark:text-amber-200">
                      {deliveryWarnings.join(' ')}
                    </div>
                  )}
                  {member.charter && (
                    <p className="rounded-lg bg-muted/50 p-3 text-sm leading-6">{member.charter}</p>
                  )}

                  <div className="space-y-2">
                    <p className="text-xs font-medium uppercase text-muted-foreground">
                      Sessions ({visibleSessions.length})
                    </p>
                    {visibleSessions.length > 0 ? (
                      <div className="space-y-2">
                        {visibleSessions.map((session) => (
                          <div
                            key={session.id}
                            className="flex flex-col gap-2 rounded-lg border px-3 py-2 text-sm md:flex-row md:items-center md:justify-between"
                          >
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant="outline" title={sessionSourceTitle(session.source)}>
                                  {sessionSourceLabel(session.source)}
                                </Badge>
                                {session.bridgeObserved && (
                                  <Badge
                                    variant="secondary"
                                    title="Agent Bridge also observes this session from tmux."
                                  >
                                    Bridge observed
                                  </Badge>
                                )}
                                {session.team_preset_name && (
                                  <Badge
                                    variant="outline"
                                    title={session.team_slot_name ? `Slot: ${session.team_slot_name}` : undefined}
                                  >
                                    {session.team_slot_name
                                      ? `${session.team_preset_name} / ${session.team_slot_name}`
                                      : session.team_preset_name}
                                  </Badge>
                                )}
                                <span className="font-medium">{session.provider}</span>
                                <span className="text-xs text-muted-foreground">
                                  {formatDateTime(session.last_seen_at)}
                                </span>
                              </div>
                              <p className="mt-1 truncate text-xs text-muted-foreground">
                                {session.activity || session.cwd || session.session_key}
                              </p>
                            </div>
                            <Badge
                              variant="outline"
                              className={statusBadgeClass(session.mailbox_status)}
                              title={sessionStatusTitle(session.source, session.mailbox_status)}
                            >
                              {sessionStatusLabel(session.source, session.mailbox_status)}
                            </Badge>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
                        No sessions observed for this participant.
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" onClick={() => onEdit(member)}>
                      <Edit3 className="mr-2 h-4 w-4" />
                      Edit
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => onCompose('message', member)}>
                      <Mail className="mr-2 h-4 w-4" />
                      Message
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => onCompose('context_request', member)}>
                      <HelpCircle className="mr-2 h-4 w-4" />
                      Request context
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => onCompose('handoff', member)}>
                      <Handshake className="mr-2 h-4 w-4" />
                      Handoff
                    </Button>
                    {showQueueInboxCheck && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onQueueInboxCheck(member)}
                        disabled={nudgingMemberId === member.id}
                      >
                        <BellRing className="mr-2 h-4 w-4" />
                        {nudgingMemberId === member.id ? 'Queueing...' : 'Queue inbox check'}
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      ) : (
        <Card className="rounded-lg border-dashed">
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            {loading ? 'Loading participants...' : 'No participants match the current filters.'}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
