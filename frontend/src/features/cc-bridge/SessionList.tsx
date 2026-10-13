import { Loader2, RefreshCw, MonitorX, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { SessionCard } from './SessionCard'
import type { CCSession } from './types'
import type { AgentProviderId } from '@/types/providers'
import type { InstanceIdentity } from '@/types/status'

type ProviderFilter = 'all' | AgentProviderId

const NO_TEAM = 'Not in a team'

interface SessionListProps {
  sessions: CCSession[]
  loading: boolean
  error: string | null
  activeTargets: string[]
  onToggleTarget: (target: string) => void
  onRefresh: () => void
  onNewSession: () => void
  onKillSession: (session: CCSession) => void
  providerFilter: ProviderFilter
  teamLabel?: string | null
  canCreateSession: boolean
  createDisabledReason: string | null
  instance?: InstanceIdentity | null
}

/** Sessions grouped under their team name, in list order. Sessions with no team come last. */
function groupByTeam(sessions: CCSession[]) {
  const groups = new Map<string, { key: string; name: string; sessions: CCSession[] }>()
  for (const session of sessions) {
    const name = session.team_preset_name?.trim() || NO_TEAM
    const group = groups.get(name) ?? { key: name, name, sessions: [] }
    group.sessions.push(session)
    groups.set(name, group)
  }
  const all = [...groups.values()]
  return [...all.filter(group => group.name !== NO_TEAM), ...all.filter(group => group.name === NO_TEAM)]
}

export function SessionList({
  sessions,
  loading,
  error,
  activeTargets,
  onToggleTarget,
  onRefresh,
  onNewSession,
  onKillSession,
  providerFilter,
  teamLabel,
  canCreateSession,
  createDisabledReason,
  instance,
}: SessionListProps) {
  const emptyName = providerFilter === 'all'
    ? 'agent'
    : providerFilter === 'codex-cli'
      ? 'Codex'
      : providerFilter === 'copilot-cli'
        ? 'Copilot'
        : providerFilter === 'opencode-cli'
          ? 'OpenCode'
          : 'Claude Code'
  const emptyTitle = teamLabel
    ? providerFilter === 'all'
      ? `No sessions in ${teamLabel}`
      : `No ${emptyName} sessions in ${teamLabel}`
    : `No ${emptyName} sessions found`
  const emptyHint = createDisabledReason
    ?? (teamLabel
      ? `Use Agent Teams to launch more sessions for ${teamLabel}. New sessions from Live sessions are standalone and stay hidden while this team filter is active.`
      : providerFilter === 'all'
      ? 'Launch or start a supported CLI in tmux.'
      : `Launch ${emptyName} from Live sessions or start it in tmux.`)
  const newSessionTitle = createDisabledReason
    ?? (teamLabel ? `New standalone session (hidden until All teams is selected)` : 'New session')

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-3 border-b">
        <span className="text-sm font-medium">
          Sessions ({sessions.length})
        </span>
        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onNewSession}
            disabled={!canCreateSession}
            title={newSessionTitle}
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onRefresh} title="Refresh">
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && sessions.length === 0 && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {error && (
          <p className="text-sm text-destructive p-2">{error}</p>
        )}

        {!loading && !error && sessions.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
            <MonitorX className="h-8 w-8 mb-2" />
            <p className="text-sm">{emptyTitle}</p>
            <p className="text-xs mt-1 text-center px-3">{emptyHint}</p>
          </div>
        )}

        {groupByTeam(sessions).map((group) => (
          <section key={group.key} aria-label={group.name}>
            <h3 className="border-b bg-muted/40 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{group.name}</h3>
            {group.sessions.map((session) => {
              const pos = activeTargets.indexOf(session.tmux_target)
              return (
                <SessionCard
                  key={session.pane_id}
                  session={session}
                  gridPosition={pos === -1 ? null : pos}
                  onClick={() => onToggleTarget(session.tmux_target)}
                  onRefresh={onRefresh}
                  onKill={onKillSession}
                  instance={instance}
                />
              )
            })}
          </section>
        ))}
      </div>
    </div>
  )
}
