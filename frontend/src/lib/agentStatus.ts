import { parseServerTime } from '@/lib/serverTime'
import type { AgentStatus } from '@/types/agentStatus'

export type SessionFact = 'online' | 'offline' | 'unknown'
export type ActivityFact = 'working' | 'idle' | 'stopped' | 'unknown'
export type WakeFact = 'can_wake' | 'cannot_wake' | 'unknown'

export interface AgentStatusView {
  current: boolean
  session: { state: SessionFact; label: string }
  activity: { state: ActivityFact; label: string; title: string }
  wake: { state: WakeFact; label: string; reason: string | null }
}

const WAKE_REASONS: Record<string, string> = {
  wake_target_unbound: 'No session is bound to this agent.',
  wake_target_stale: 'The wake target is out of date. Deck cannot confirm it.',
  wake_target_ambiguous: 'More than one session matches this agent.',
  wake_opted_out: 'Wake participation is turned off for this agent.',
  observation_unavailable: 'Deck cannot read or confirm the wake path.',
}

const ACTIVITY_REASONS: Record<string, string> = {
  native_turn_started: 'The harness reported a working turn.',
  native_turn_completed: 'The harness reported that its turn finished. It can still wait for review, a merge or another instruction.',
  native_turn_interrupted: 'The harness reported an interrupted turn or an error.',
  native_event_stale: 'No recent native progress event. Working activity cannot be confirmed.',
  process_stopped: 'The bound process is suspended, stopped or has exited.',
  process_ended: 'The bound process has ended.',
  provider_unsupported: 'This harness has no native activity adapter yet.',
  no_current_binding: 'No authenticated current session binding is available.',
  restart_needed_for_observation: 'Restart this session in resume mode through Deck to see its activity.',
  observation_unavailable: 'The controller cannot read or validate this activity observation.',
}

export function wakeReasonText(reason: string | null | undefined): string {
  if (!reason) return 'Deck gave no reason.'
  return WAKE_REASONS[reason] ?? 'Deck cannot confirm a wake path.'
}

/** True while the backend still stands behind the status. */
export function isAgentStatusCurrent(status: AgentStatus | null | undefined, now: number): boolean {
  if (!status) return false
  const validUntil = parseServerTime(status.valid_until).getTime()
  return Number.isFinite(validUntil) && validUntil > now
}

/** "3 h" or "12 min". Only an idle_since time gives a duration. */
export function formatIdleDuration(idleSince: string, now: number): string | null {
  const since = parseServerTime(idleSince).getTime()
  if (!Number.isFinite(since) || since > now) return null
  const minutes = Math.floor((now - since) / 60_000)
  if (minutes < 1) return 'under 1 min'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} h`
  return `${Math.floor(hours / 24)} d`
}

/** One place for the words. After valid_until every fact is Unknown. */
export function agentStatusView(status: AgentStatus | null | undefined, now: number): AgentStatusView {
  const current = isAgentStatusCurrent(status, now)
  if (!status || !current) {
    return {
      current: false,
      session: { state: 'unknown', label: 'Status unknown' },
      activity: {
        state: 'unknown',
        label: 'Activity unknown',
        title: status ? 'This status has expired. Deck is reading it again.' : 'Deck has no status for this agent.',
      },
      wake: { state: 'unknown', label: 'Wake unknown', reason: null },
    }
  }

  const activityReason = ACTIVITY_REASONS[status.activity_reason] ?? 'Activity could not be confirmed.'
  let activityLabel = 'Activity unknown'
  if (status.activity_state === 'working') activityLabel = 'Working'
  else if (status.activity_state === 'stopped') activityLabel = 'Stopped'
  else if (status.activity_state === 'idle') {
    const duration = status.idle_since ? formatIdleDuration(status.idle_since, now) : null
    activityLabel = duration ? `Idle for ${duration}` : 'Idle'
  }

  return {
    current: true,
    session: {
      state: status.session_state,
      label: status.session_state === 'online' ? 'Online' : status.session_state === 'offline' ? 'Offline' : 'Status unknown',
    },
    activity: { state: status.activity_state, label: activityLabel, title: activityReason },
    wake: {
      state: status.wake_state,
      label: status.wake_state === 'can_wake' ? 'Can be woken' : status.wake_state === 'cannot_wake' ? 'Cannot be woken' : 'Wake unknown',
      reason: status.wake_state === 'cannot_wake' ? wakeReasonText(status.wake_reason) : null,
    },
  }
}
