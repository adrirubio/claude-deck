import type { TeamSummaryAttention, TeamSummaryHumanAction } from '@/types/agentTeams'

// Plain words for the team summary, shared by the team card and the Overview.
export const ATTENTION_TEXT: Record<TeamSummaryAttention['code'], string> = {
  attempt_stopped: 'Attempt stopped',
  recovery_decision: 'Recovery decision needed',
  human_review: 'Human review needed',
  owner_stalled: 'Owner stalled',
  observation_pause: 'Observation paused',
  hold: 'Team on HOLD',
  recovery_only: 'Team in recovery-only mode',
  hold_unavailable: 'HOLD state unknown',
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
