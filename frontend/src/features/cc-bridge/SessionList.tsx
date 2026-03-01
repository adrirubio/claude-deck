import { Loader2, RefreshCw, MonitorX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { SessionCard } from './SessionCard'
import type { CCSession } from './types'

interface SessionListProps {
  sessions: CCSession[]
  loading: boolean
  error: string | null
  selectedTarget: string | null
  onSelect: (target: string) => void
  onRefresh: () => void
}

export function SessionList({
  sessions,
  loading,
  error,
  selectedTarget,
  onSelect,
  onRefresh,
}: SessionListProps) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-3 border-b">
        <span className="text-sm font-medium">
          Sessions ({sessions.length})
        </span>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onRefresh}>
          <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
        </Button>
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
            <p className="text-sm">No CC sessions found</p>
            <p className="text-xs mt-1">Start Claude Code in a tmux session</p>
          </div>
        )}

        {sessions.map((session) => (
          <SessionCard
            key={session.pane_id}
            session={session}
            isSelected={selectedTarget === session.tmux_target}
            onClick={() => onSelect(session.tmux_target)}
          />
        ))}
      </div>
    </div>
  )
}
