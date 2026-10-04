import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { AgentActivityObservation } from '@/types/agentTeams'

const reasons: Record<string, string> = {
  native_turn_started: 'The current harness reported a working turn.',
  native_turn_completed: 'The current harness reported that its turn finished. It can still be waiting for review, a merge or another instruction.',
  native_turn_interrupted: 'The harness reported an interrupted turn or an error.',
  native_event_stale: 'No recent native progress event. Working activity can no longer be confirmed.',
  native_event_before_process: 'The native events belong to an earlier process. Current activity cannot be confirmed.',
  process_stopped: 'The bound process is suspended, stopped or has exited.',
  process_ended: 'The bound process has ended.',
  provider_unsupported: 'This harness does not yet have a native activity adapter.',
  no_current_binding: 'No authenticated current session binding is available.',
  ambiguous_binding: 'More than one current session matches this slot.',
  duplicate_native_identity: 'More than one Deck slot is configured to resume this native conversation. Per-agent activity cannot be distinguished.',
  session_identity_unavailable: 'An explicit native session identity is required to observe activity.',
  session_mismatch: 'The running process and native session identity do not match.',
  binding_changed: 'The session binding changed during observation.',
  native_log_unavailable: 'The native activity log is unavailable.',
  no_native_event: 'No supported native turn event is available.',
  observation_incomplete: 'The latest native activity record is incomplete.',
  observation_invalid: 'The native activity observation could not be validated.',
  observation_unavailable: 'The controller cannot read or validate this activity observation.',
}

export function AgentActivityBadge({ activity }: { activity?: AgentActivityObservation }) {
  const state = activity?.state ?? 'unknown'
  const label = state === 'unknown' ? 'Activity unknown' : state === 'working' ? 'Working' : state === 'idle' ? 'Idle' : 'Stopped'
  const reason = activity ? reasons[activity.reason] ?? 'Activity could not be confirmed.' : 'Activity is unavailable, refreshing or expired.'
  const observed = activity?.observed_at ? ` Last native event: ${new Date(activity.observed_at).toLocaleString()}.` : ''
  return (
    <Badge variant="outline" title={reason + observed} aria-label={`Agent activity: ${label}. ${reason}`} className={cn(
      'gap-1.5 whitespace-nowrap',
      state === 'working' ? 'agent-working-pulse border-primary/50 bg-primary/10 text-primary' : 'text-muted-foreground',
    )}>
      <span aria-hidden="true" className={cn('h-1.5 w-1.5 rounded-full', state === 'working' ? 'bg-primary' : 'bg-muted-foreground/60')} />
      {label}
    </Badge>
  )
}
