import type { TeamSummaryAttention, TeamSummaryHumanAction, UnansweredRequestReason } from '@/types/agentTeams'

// Plain words for the team summary, shared by the team card and the Overview.
export const ATTENTION_TEXT: Record<TeamSummaryAttention['code'], string> = {
  attempt_stopped: 'Attempt stopped',
  recovery_decision: 'Recovery decision needed',
  human_review: 'Human review needed',
  owner_stalled: 'Owner stalled',
  team_idle: 'Team idle',
  observation_pause: 'Observation paused',
  hold: 'Team on HOLD',
  recovery_only: 'Team in recovery-only mode',
  hold_unavailable: 'HOLD state unknown',
  unanswered_request: 'Unanswered request',
  unanswered_request_incomplete: 'Unanswered-request view incomplete',
}

// Plain words for the fixed reason a view of unanswered requests is not complete (#752).
export const COVERAGE_REASON_TEXT: Record<UnansweredRequestReason, string> = {
  candidate_limit: 'more candidates than the view reads',
  native_unknown: "a member's activity is unknown or not readable",
  ambiguous_legacy_request: 'an older nested request cannot be matched to a reply',
  reply_scan_limit: 'the reply check reached its limit',
  entry_limit: 'more unanswered requests than are listed',
}

// Any other value shows a fixed fallback, never text from the server.
export function coverageReasonText(reason: string | null | undefined) {
  return COVERAGE_REASON_TEXT[reason as UnansweredRequestReason] ?? 'the view could not be proven'
}

export function unansweredRequestText(item: TeamSummaryAttention) {
  const minutes = Math.floor(Math.max(0, item.unanswered_seconds ?? 0) / 60)
  return `${item.recipient ?? 'A member'} has not answered ${item.requester ?? 'a team member'}'s request for ${minutes} min`
}

export function incompleteRequestText(item: TeamSummaryAttention) {
  const more = (item.omitted_count ?? 0) > 0 ? ` · ${item.omitted_count} more not listed` : ''
  return `${coverageReasonText(item.coverage_reason)}${more}`
}

export const ACTION_TEXT: Record<TeamSummaryHumanAction['kind'], string> = {
  review_pr: 'Review the PR',
  merge_pr: 'Merge the PR',
  inspect_attempt: 'Inspect the attempt',
  inspect_checkpoint: 'Inspect the checkpoint',
  milestone_acceptance: 'Accept the milestone',
  pilot_decision: 'Make the pilot decision',
  scope_clarification: 'Clarify the scope',
  provide_evidence: 'Provide evidence',
}
