import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { agentStatusView, isAgentStatusCurrent } from '@/lib/agentStatus'
import { parseServerTime } from '@/lib/serverTime'
import { cn } from '@/lib/utils'
import type { AgentStatus } from '@/types/agentStatus'

interface AgentStatusBadgesProps {
  status?: AgentStatus | null
  /** Leave out the line that explains a refused wake. The reason stays in the tooltip. */
  compact?: boolean
  /** Fixed clock for tests. */
  now?: number
  className?: string
}

/** Read the clock again when the status changes and when it expires. */
function useStatusClock(status: AgentStatus | null | undefined, fixedNow?: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (fixedNow !== undefined || !status) return
    const timers = [window.setTimeout(() => setNow(Date.now()), 0)]
    const remaining = parseServerTime(status.valid_until).getTime() - Date.now()
    if (Number.isFinite(remaining) && remaining > 0) {
      timers.push(window.setTimeout(() => setNow(Date.now()), remaining + 50))
    }
    return () => timers.forEach((timer) => window.clearTimeout(timer))
  }, [status, fixedNow])
  return fixedNow ?? now
}

/** The one display of an agent's status: session, activity and wake. */
export function AgentStatusBadges({ status, compact, now, className }: AgentStatusBadgesProps) {
  const clock = useStatusClock(status, now)
  const view = agentStatusView(status, clock)
  const expired = Boolean(status) && !isAgentStatusCurrent(status, clock)
  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', className)} data-testid="agent-status">
      {/* The spaces keep copied text and text queries readable: "Online Idle for 3 h". */}
      {' '}
      <Badge
        variant="outline"
        title={view.current ? 'Whether the agent session is alive.' : expired ? 'This status has expired.' : 'Deck has no status for this agent.'}
        className={cn(
          view.session.state === 'online' && 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300',
          view.session.state !== 'online' && 'border-muted-foreground/30 bg-muted text-muted-foreground',
        )}
      >
        {view.session.label}
      </Badge>
      {' '}
      <Badge
        variant="outline"
        title={view.activity.title}
        className={cn(
          'gap-1.5 whitespace-nowrap',
          view.activity.state === 'working' ? 'agent-working-pulse border-primary/50 bg-primary/10 text-primary' : 'text-muted-foreground',
        )}
      >
        <span aria-hidden="true" className={cn('h-1.5 w-1.5 rounded-full', view.activity.state === 'working' ? 'bg-primary' : 'bg-muted-foreground/60')} />
        {view.activity.label}
      </Badge>
      {' '}
      <Badge
        variant="outline"
        title={view.wake.reason ?? (view.wake.state === 'can_wake' ? 'Deck can wake it in its terminal.' : 'Whether Deck can wake the agent. This display grants no authority.')}
        className={cn(
          view.wake.state === 'can_wake' && 'border-emerald-300 text-emerald-700 dark:text-emerald-300',
          view.wake.state === 'cannot_wake' && 'border-amber-300 text-amber-700 dark:text-amber-300',
          view.wake.state === 'unknown' && 'border-muted-foreground/30 text-muted-foreground',
        )}
      >
        {view.wake.label}
      </Badge>
      {' '}
      {view.wake.reason && !compact && <span className="w-full text-xs text-muted-foreground">{view.wake.reason}</span>}
    </div>
  )
}
