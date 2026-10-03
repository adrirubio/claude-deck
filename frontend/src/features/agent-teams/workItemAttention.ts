import type { GithubWorkItem, TeamGithubScope } from '@/types/agentTeams'

export type WorkItemAttention = { label: string; reason: string; linkLabel: string }

// Matches the server's explicit auto-merge fallback notes. A generic review
// status, live harness or green CI never proves independent review acceptance.
const humanMergeFallbacks = ['Auto-merge blocked', 'Auto-merge budget exhausted', 'Auto-merge failed', 'Auto-merge retry budget exhausted']

export function workItemAttention(item: GithubWorkItem, scope?: TeamGithubScope): WorkItemAttention | null {
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
  if (item.pending_approval_status === 'pending') return 'Waiting for Leader approval'
  const attention = workItemAttention(item, scope)
  if (attention) return attention.label
  if (item.dispatch_status === 'ready_for_review' && scope?.merge_policy === 'auto') return 'Waiting for automatic merge'
  return item.dispatch_status.replaceAll('_', ' ')
}
