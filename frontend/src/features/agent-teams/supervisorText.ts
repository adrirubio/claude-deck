import type { SupervisorObservation, TeamWaitingInput } from '@/types/agentTeams'

// Plain words for the supervisor status and for a member that waits for input.
// Only the controller's status word and the fixed reason code are shown.

function minutes(from: number, to: number) {
  return Math.max(0, Math.floor((to - from) / 60000))
}

function span(count: number) {
  if (count < 1) return 'less than 1 min'
  if (count < 120) return `${count} min`
  const hours = Math.floor(count / 60)
  return hours < 48 ? `${hours} h` : `${Math.floor(hours / 24)} d`
}

export type SupervisorChip = 'None' | 'Healthy' | 'Late' | 'Absent'

export function supervisorWords(
  observation: SupervisorObservation,
  now: number,
): { chip: SupervisorChip; detail: string } {
  const checked = observation.checked_at ? Date.parse(observation.checked_at) : NaN
  const next = observation.next_check_at ? Date.parse(observation.next_check_at) : NaN
  switch (observation.status) {
    case 'none':
      return { chip: 'None', detail: 'not required' }
    case 'healthy': {
      const parts = []
      if (Number.isFinite(checked)) parts.push(`checked ${span(minutes(checked, now))} ago`)
      if (Number.isFinite(next)) parts.push(`next in ${span(minutes(now, next))}`)
      return { chip: 'Healthy', detail: parts.join(' · ') }
    }
    case 'late':
      return {
        chip: 'Late',
        detail: `check-in overdue${Number.isFinite(next) ? ` by ${span(minutes(next, now))}` : ''} · work can still run`,
      }
    default:
      return {
        chip: 'Absent',
        detail: Number.isFinite(checked) ? `no check-in since ${span(minutes(checked, now))} ago` : 'no check-in yet',
      }
  }
}

const WAIT_SCREEN: Record<TeamWaitingInput['reason'], string> = {
  question: 'a question',
  trust: 'a trust prompt',
  sign_in: 'a sign-in screen',
}

// Any other value shows a fixed fallback, never text from the screen.
export function waitingScreen(reason: string) {
  return WAIT_SCREEN[reason as TeamWaitingInput['reason']] ?? 'an input screen'
}

export function waitingText(entry: TeamWaitingInput, names: Record<number, string> | undefined) {
  return `${names?.[entry.slot_id] ?? 'A member'} is waiting at ${waitingScreen(entry.reason)}`
}
