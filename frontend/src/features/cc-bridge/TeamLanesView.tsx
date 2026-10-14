import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Monitor, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { agentStatusView } from '@/lib/agentStatus'
import { cn } from '@/lib/utils'
import { TerminalView } from './TerminalView'
import { LANE_COUNT, canShiftLeft, canShiftRight, clampStart, windowLabel } from './teamLanesWindow'
import type { CCSession, LeaderNavigationDirection } from './types'
import type { InstanceIdentity } from '@/types/status'

const FOCUSED_PANE_RING_CLASS =
  "after:pointer-events-none after:absolute after:inset-0 after:z-10 after:ring-2 after:ring-primary after:ring-inset after:content-['']"

interface TeamLanesViewProps {
  /** Every member of the team, in slot order. */
  sessions: CCSession[]
  /** Index of the first visible member. */
  start: number
  /** The zoomed member, or null. */
  zoomed: string | null
  teamLabel?: string | null
  focusedTarget: string | null
  onFocusTarget: (target: string) => void
  onLeaderNavigate: (sourceTarget: string, direction: LeaderNavigationDirection) => void
  onLeaderStateChange: (sourceTarget: string, active: boolean) => void
  onShift: (delta: number) => void
  onShowMember: (target: string) => void
  onToggleZoom: (target: string) => void
  onExit: () => void
  instance?: InstanceIdentity | null
}

/** A clock that ticks every 30 seconds, so the activity of the members stays current. */
function useClock(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

function laneLabel(session: CCSession): string {
  return session.team_slot_name || session.session_name || session.tmux_target
}

export function TeamLanesView({
  sessions,
  start,
  zoomed,
  teamLabel,
  focusedTarget,
  onFocusTarget,
  onLeaderNavigate,
  onLeaderStateChange,
  onShift,
  onShowMember,
  onToggleZoom,
  onExit,
  instance,
}: TeamLanesViewProps) {
  const first = clampStart(start, sessions.length)
  // Only the visible members get a terminal, so at most four relays are open.
  const visible = sessions.slice(first, first + LANE_COUNT)
  const visibleTargets = new Set(visible.map((session) => session.tmux_target))
  const now = useClock()

  return (
    <div className="absolute inset-0 flex flex-col bg-background">
      <div className="flex h-10 shrink-0 items-center justify-between gap-3 border-b bg-muted/30 px-3">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="text-sm font-semibold">Team lanes</span>
          <span className="truncate text-xs text-muted-foreground">
            {teamLabel ?? 'Selected team'} · {sessions.length} {sessions.length === 1 ? 'member' : 'members'}
          </span>
          <span className="shrink-0 rounded border px-1.5 text-xs" aria-live="polite">{windowLabel(first, sessions.length)}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="hidden text-xs text-muted-foreground lg:inline">
            Shift with ‹ › or Alt+←/→ · {zoomed ? 'Esc restores the lanes' : 'zoom a lane with ⤢ · Esc exits'}
          </span>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onExit} title="Exit team lanes" aria-label="Exit team lanes">
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
        <>
          <nav aria-label="Team members" className="flex shrink-0 flex-wrap gap-1.5 border-b px-3 py-2">
            {sessions.map((session) => {
              const shown = visibleTargets.has(session.tmux_target)
              const activity = agentStatusView(session.agent_status, now).activity.label
              return (
                <button
                  key={session.pane_id}
                  type="button"
                  aria-pressed={shown}
                  className={cn(
                    'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
                    shown ? 'border-primary bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-muted',
                  )}
                  onClick={() => onShowMember(session.tmux_target)}
                  title={`${laneLabel(session)} · ${session.provider_display_name} · ${activity}`}
                >
                  <span className="font-medium">{laneLabel(session)}</span>
                  {session.team_slot_role && <span className="text-[11px]">{session.team_slot_role}</span>}
                  <span className="text-[11px]">{session.provider_display_name}</span>
                  <span className="text-[11px]">{activity}</span>
                </button>
              )
            })}
          </nav>

          <div className="flex min-h-0 flex-1 overflow-hidden">
            {!zoomed && (
              <button
                type="button"
                className="flex w-7 shrink-0 items-center justify-center border-r text-muted-foreground transition-colors hover:bg-muted disabled:opacity-30 disabled:hover:bg-transparent focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                aria-label="Show the previous member"
                disabled={!canShiftLeft(first)}
                onClick={() => onShift(-1)}
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            )}
            <div className="flex min-w-0 flex-1 overflow-hidden">
              {visible.map((session) => {
                const isZoomed = zoomed === session.tmux_target
                const hidden = zoomed !== null && !isZoomed
                return (
                  <div
                    key={session.pane_id}
                    className={cn(
                      hidden ? 'hidden' : 'relative flex min-w-0 flex-1 flex-col overflow-hidden border-r last:border-r-0',
                      !hidden && focusedTarget === session.tmux_target && FOCUSED_PANE_RING_CLASS
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
                          fullscreen={isZoomed}
                          focused={focusedTarget === session.tmux_target}
                          onToggleFullscreen={() => onToggleZoom(session.tmux_target)}
                          onLeaderNavigate={onLeaderNavigate}
                          onLeaderStateChange={onLeaderStateChange}
                          instance={instance}
                          session={session}
                        />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
            {!zoomed && (
              <button
                type="button"
                className="flex w-7 shrink-0 items-center justify-center border-l text-muted-foreground transition-colors hover:bg-muted disabled:opacity-30 disabled:hover:bg-transparent focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                aria-label="Show the next member"
                disabled={!canShiftRight(first, sessions.length)}
                onClick={() => onShift(1)}
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
