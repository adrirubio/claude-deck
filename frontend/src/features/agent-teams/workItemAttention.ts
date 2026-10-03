import type { GithubWorkItem, TeamGithubScope } from '@/types/agentTeams'

export type WorkItemAttention = { label: string; reason: string; linkLabel: string }

// Matches the server's explicit auto-merge fallback notes. A generic review
// status, live harness or green CI never proves independent review acceptance.
const humanMergeFallbacks = ['Auto-merge blocked', 'Auto-merge budget exhausted', 'Auto-merge failed', 'Auto-merge retry budget exhausted']

export function workItemAttention(item: GithubWorkItem, scope?: TeamGithubScope): WorkItemAttention | null {
  if (item.dispatch_status === 'escalated' && ['decision_hold', 'ack_hold'].includes(item.recovery_checkpoint_stage ?? '')) {
    return { label: 'Your recovery decision is needed', reason: 'Recovery is paused at an operator checkpoint. Open the details to inspect and release or cancel the hold.', linkLabel: 'Open PR' }
  }
  if (item.pending_approval_status === 'pending' && ['escalated', 'failed'].includes(item.dispatch_status)
      && item.pending_approval_kind === 'initial_plan') {
    return { label: 'Your intervention is needed', reason: 'The initial approval is stranded on a stopped attempt. Open the recovery details to inspect operator remedies; the Leader cannot decide this request.', linkLabel: 'Open PR' }
  }
  if (item.pending_approval_status === 'pending') return null // the Leader must decide
  if (item.dispatch_status === 'awaiting_human_review') {
    return { label: 'Your review is needed', reason: 'The team is waiting for your review of the design PR.', linkLabel: 'Review PR' }
  }
  if (item.dispatch_status === 'ready_for_review' && (
    scope?.merge_policy === 'human' || humanMergeFallbacks.some((prefix) => item.status_note?.startsWith(prefix))
  )) {
    return {
      label: 'Your review or merge is needed',
      reason: scope?.merge_policy === 'human'
        ? 'Human merge policy is enabled. The team is waiting for you to review the evidence and merge the PR when ready.'
        : 'Automatic merge could not proceed. Review the evidence and merge the PR when ready.',
      linkLabel: 'Review or merge PR',
    }
  }
  if (['escalated', 'failed'].includes(item.dispatch_status)) {
    return { label: 'Your intervention is needed', reason: 'Deck stopped this attempt. Open the details to inspect the reason and available recovery actions.', linkLabel: 'Open PR' }
  }
  return null
}

export function workItemStatusLabel(item: GithubWorkItem, scope?: TeamGithubScope) {
  const attention = workItemAttention(item, scope)
  if (attention) return attention.label
  if (item.pending_approval_status === 'pending') return 'Waiting for Leader approval'
  if (item.dispatch_status === 'ready_for_review' && scope?.merge_policy === 'auto') return 'Waiting for automatic merge'
  return item.dispatch_status.replaceAll('_', ' ')
}
