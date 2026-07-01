import { Monitor, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { TerminalView } from './TerminalView'
import type { CCSession, LeaderNavigationDirection } from './types'
import type { InstanceIdentity } from '@/types/status'

interface TeamLanesViewProps {
  sessions: CCSession[]
  overflowCount: number
  teamLabel?: string | null
  focusedTarget: string | null
  onFocusTarget: (target: string) => void
  onLeaderNavigate: (sourceTarget: string, direction: LeaderNavigationDirection) => void
  onLeaderStateChange: (sourceTarget: string, active: boolean) => void
  onExit: () => void
  instance?: InstanceIdentity | null
}

function laneLabel(session: CCSession): string {
  return session.team_slot_name || session.session_name || session.tmux_target
}

export function TeamLanesView({
  sessions,
  overflowCount,
  teamLabel,
  focusedTarget,
  onFocusTarget,
  onLeaderNavigate,
  onLeaderStateChange,
  onExit,
  instance,
}: TeamLanesViewProps) {
  return (
    <div className="absolute inset-0 flex flex-col bg-background">
      <div className="flex h-10 shrink-0 items-center justify-between gap-3 border-b bg-muted/30 px-3">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="text-sm font-semibold">Team lanes</span>
          <span className="truncate text-xs text-muted-foreground">
            {teamLabel ?? 'Selected team'} · {sessions.length} shown
            {overflowCount > 0 ? ` · +${overflowCount} not shown` : ''}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs text-muted-foreground">Esc exits</span>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onExit} title="Exit team lanes">
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {sessions.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center text-muted-foreground">
          <Monitor className="mb-3 h-12 w-12" />
          <p className="text-sm">No live team sessions</p>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {sessions.map((session) => (
            <div
              key={session.pane_id}
              className={cn(
                'relative flex min-w-0 flex-1 flex-col overflow-hidden border-r last:border-r-0',
                focusedTarget === session.tmux_target ? 'bg-primary/60' : 'bg-border/30'
              )}
              onMouseDown={() => onFocusTarget(session.tmux_target)}
              onFocusCapture={() => onFocusTarget(session.tmux_target)}
            >
              <div className="flex h-8 shrink-0 items-center gap-2 border-b bg-background px-2">
                <span className="truncate text-xs font-medium" title={laneLabel(session)}>
                  {laneLabel(session)}
                </span>
                {session.team_slot_role && (
                  <span className="shrink-0 truncate text-[11px] text-muted-foreground" title={session.team_slot_role}>
                    {session.team_slot_role}
                  </span>
                )}
              </div>
              <div className="relative min-h-0 flex-1">
                <div className="absolute inset-[2px] rounded-sm">
                  <TerminalView
                    target={session.tmux_target}
                    inLanes
                    focused={focusedTarget === session.tmux_target}
                    onLeaderNavigate={onLeaderNavigate}
                    onLeaderStateChange={onLeaderStateChange}
                    instance={instance}
                    session={session}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
