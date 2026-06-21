import { Loader2, RefreshCw, MonitorX, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { SessionCard } from './SessionCard'
import type { CCSession } from './types'
import type { AgentProviderId } from '@/types/providers'
import type { InstanceIdentity } from '@/types/status'

type ProviderFilter = 'all' | AgentProviderId

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
  canCreateSession: boolean
  createDisabledReason: string | null
  instance?: InstanceIdentity | null
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
        : 'Claude Code'
  const emptyHint = createDisabledReason
    ?? (providerFilter === 'all'
      ? 'Launch or start a supported CLI in tmux.'
      : `Launch ${emptyName} from Agent Bridge or start it in tmux.`)

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
            title={createDisabledReason ?? 'New session'}
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onRefresh} title="Refresh">
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-2">
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
            <p className="text-sm">No {emptyName} sessions found</p>
            <p className="text-xs mt-1 text-center px-3">{emptyHint}</p>
          </div>
        )}

        {sessions.map((session) => {
          const pos = activeTargets.indexOf(session.tmux_target)
          return (
            <SessionCard
              key={session.pane_id}
              session={session}
              gridPosition={pos === -1 ? null : pos}
              onClick={() => onToggleTarget(session.tmux_target)}
              onKill={onKillSession}
              instance={instance}
            />
          )
        })}
      </div>
    </div>
  )
}
