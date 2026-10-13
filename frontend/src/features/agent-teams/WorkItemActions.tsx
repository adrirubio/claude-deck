import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertCircle, GitPullRequest, RotateCcw, XCircle } from 'lucide-react'
import { formatServerTime } from '@/lib/serverTime'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import type {
  AgentActivityObservation,
  AgentTeamSlot,
  GithubScopeRevision,
  GithubWorkItem,
  GithubWorkspace,
  TeamGithubScope,
} from '@/types/agentTeams'
import { AgentActivityBadge } from './AgentActivityBadge'
import { WorkPublicationPanel } from './WorkPublicationPanel'
import { workItemAttention, workItemStatusLabel } from './workItemAttention'

export type ItemOperatorAction =
  | { kind: 'abandon' | 'resume' }
  | { kind: 'release_decision' | 'release_ack' | 'cancel_request' | 'cancel_revision'; revision: GithubScopeRevision }
  | { kind: 'force_release'; workspace: GithubWorkspace }

function formatDateTime(value?: string | null) {
  if (!value) return 'never'
  return formatServerTime(value)
}

function routeMethodLabel(value?: string | null) {
  if (!value) return 'not routed'
  if (value === 'label') return 'label match'
  if (value === 'leader_fallback') return 'leader fallback'
  return value.replaceAll('_', ' ')
}

function phaseHelp(phase?: string | null) {
  if (phase === 'diagnostic') return 'Diagnostic: investigating failed checks within an approved recovery revision; it is not a product-ready PR.'
  if (phase === 'implementation') return 'Implementation: working on the issue and its product PR.'
  return 'The attempt has not started a phase.'
}

const escalationReasonLabels: Record<string, string> = {
  plan_blocked: 'Plan blocked',
  launch_outcome_unknown: 'Session launch outcome unknown',
  approval_rounds_exhausted: 'Approval rounds exhausted',
  leader_offline: 'Leader offline',
  owner_offline: 'Owner offline',
  brief_unread: 'Owner has not read the brief',
  leader_ack_timeout: 'Leader acknowledgement timed out',
  owner_idle_timeout: 'Owner idle timeout',
  owner_observation_unavailable: 'Owner observation unavailable',
  integration_update_conflict: 'Integration update needs coordination',
  retry_count_exhausted: 'Verification retries exhausted',
  continuation_revision_exhausted: 'Continuation revision exhausted',
  continuation_budget_exhausted: 'Continuation budget exhausted',
  continuation_invalid_state: 'Continuation state invalid',
  continuation_pr_identity_invalid: 'Continuation PR identity invalid',
  dispatch_label_removed: 'Dispatch label removed',
  abandoned_by_operator: 'Abandoned by operator',
  prepared_owner_unavailable: 'Prepared owner unavailable',
  pr_closed_unmerged: 'PR closed without merge',
}

function escalationReasonLabel(reason?: string | null) {
  if (!reason) return 'Unknown reason'
  return escalationReasonLabels[reason] ?? reason.replaceAll('_', ' ')
}

function approvalStatusLabel(status?: string | null) {
  if (status === 'pending') return 'awaiting Leader decision'
  if (status === 'approved') return 'approved by Leader'
  if (status === 'rejected') return 'rejected by Leader'
  return status?.replaceAll('_', ' ') ?? 'awaiting Leader decision'
}

function prUrl(item: GithubWorkItem) {
  if (!item.pr_number) return null
  return `https://github.com/${item.repo_owner}/${item.repo_name}/pull/${item.pr_number}`
}

function recoveryBlockLabel(code?: string | null) {
  if (!code) return 'Recovery is available for this attempt. The owner proposes a bounded revision for the Leader to approve.'
  return code.replaceAll('_', ' ')
}

function recoverySummary(item: GithubWorkItem) {
  if (item.continuation_block_code === 'continuation_disabled') return 'Recovery policy is off for this repo. Existing work may still need attention.'
  if (item.dispatch_status === 'escalated') {
    return item.continuation_block_code
      ? `Recovery blocked: ${recoveryBlockLabel(item.continuation_block_code)}.`
      : 'This issue is escalated. Review the reason above before continuing recovery.'
  }
  if (item.pending_approval_kind === 'continuation' && item.pending_approval_status === 'pending') {
    return 'Waiting for the Leader to approve the proposed recovery revision.'
  }
  if (item.dispatch_status === 'verifying' && item.active_scope_revision > 0) {
    return `Recovery revision ${item.active_scope_revision} was submitted; Deck is checking the PR.`
  }
  if (item.dispatch_status === 'dispatched' && item.active_scope_status === 'active') {
    return `Recovery in progress: the owner is working within approved revision ${item.active_scope_revision}. No operator action is needed unless it stalls.`
  }
  if (item.continuation_block_code === 'continuation_not_escalated') return 'Recovery is not needed while this issue is progressing.'
  if (item.continuation_block_code) return `Recovery blocked: ${recoveryBlockLabel(item.continuation_block_code)}.`
  return recoveryBlockLabel()
}

function phaseLabel(phase?: string | null) {
  if (phase === 'diagnostic') return 'Diagnostic'
  if (phase === 'implementation') return 'Implementation'
  return phase?.replaceAll('_', ' ') ?? 'Not started'
}

function readableCode(value?: string | null) {
  if (!value) return 'Not set'
  return value.replaceAll('_', ' ').replace(/^./, (first) => first.toUpperCase())
}

function safeEvidenceLinks(evidence?: Record<string, unknown> | null) {
  if (!evidence) return []
  const links: Array<{ label: string; url: string }> = []
  for (const [label, value] of Object.entries(evidence)) {
    if (typeof value !== 'string') continue
    try {
      const url = new URL(value)
      if (url.protocol === 'https:' || url.protocol === 'http:') {
        links.push({ label, url: url.toString() })
      }
    } catch {
      continue
    }
  }
  return links
}

/** The recovery and remedy actions for one work item. Moved from the Autonomy tab dialog. */
export function WorkItemActions({
  item,
  scope,
  ownerActivity,
  ownerName,
  handoffTargetName,
  onRetry,
  onFetchScopeRevisions,
  onFetchWorkspaces,
  operatorTokenStored,
  onRequestOperatorToken,
  slots,
  onOperate,
  hideSummary = false,
}: {
  item: GithubWorkItem
  scope?: TeamGithubScope
  ownerActivity?: AgentActivityObservation
  ownerName?: string
  handoffTargetName?: string
  onRetry?: (item: GithubWorkItem) => void
  onFetchScopeRevisions: (itemId: number) => Promise<GithubScopeRevision[]>
  onFetchWorkspaces: (scopeId: number) => Promise<{ workspaces: GithubWorkspace[] }>
  operatorTokenStored: boolean
  onRequestOperatorToken: () => Promise<string | null>
  slots: AgentTeamSlot[]
  // The Work item page shows status, owner and PR in its own header.
  hideSummary?: boolean
  onOperate: (
    item: GithubWorkItem,
    action: ItemOperatorAction,
    reason: string,
    reassignToSlotId?: number
  ) => Promise<string | undefined>
}) {
  const [loadingRevisions, setLoadingRevisions] = useState(false)
  const [revisions, setRevisions] = useState<GithubScopeRevision[]>([])
  const [revisionError, setRevisionError] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [actionResult, setActionResult] = useState<string | null>(null)
  const [operatorAction, setOperatorAction] = useState<ItemOperatorAction | null>(null)
  const [actionReason, setActionReason] = useState('')
  const [reassignToSlotId, setReassignToSlotId] = useState('current')
  const [actionSaving, setActionSaving] = useState(false)
  const [workspaceLoading, setWorkspaceLoading] = useState(false)
  const revisionRequestIdRef = useRef(0)
  const itemId = item?.id ?? null
  const revisionVersion = item
    ? JSON.stringify([
        item.active_scope_revision,
        item.active_scope_status,
        item.revision_delivered_at,
        item.revision_acknowledged_at,
        item.revision_failed_head_count,
        item.pending_approval_request_id,
        item.pending_approval_status,
        item.continuation_block_code,
        item.dispatch_status,
        item.updated_at,
      ])
    : null
  const attention = item ? workItemAttention(item, scope) : null

  const loadRevisions = useCallback((targetItemId: number) => {
    const requestId = ++revisionRequestIdRef.current
    queueMicrotask(() => {
      if (revisionRequestIdRef.current !== requestId) return
      setLoadingRevisions(true)
      setRevisionError(null)
      void onFetchScopeRevisions(targetItemId)
        .then((rows) => {
          if (revisionRequestIdRef.current === requestId) setRevisions(rows)
        })
        .catch((error) => {
          if (revisionRequestIdRef.current === requestId) {
            setRevisionError(error instanceof Error ? error.message : 'Failed to load recovery history')
          }
        })
        .finally(() => {
          if (revisionRequestIdRef.current === requestId) setLoadingRevisions(false)
        })
    })
  }, [onFetchScopeRevisions])

  useEffect(() => {
    if (itemId === null) return
    const requestRef = revisionRequestIdRef
    if (!operatorTokenStored) {
      const requestId = ++revisionRequestIdRef.current
      queueMicrotask(() => {
        if (revisionRequestIdRef.current === requestId) {
          setLoadingRevisions(false)
          setRevisionError('Enter the Director key to load recovery history.')
        }
      })
      return () => { requestRef.current++ }
    }
    loadRevisions(itemId)
    return () => { requestRef.current++ }
  }, [itemId, revisionVersion, operatorTokenStored, loadRevisions])

  const retryLoadRevisions = () => {
    if (itemId === null) return
    if (!operatorTokenStored) {
      // A key found in storage turns the stored flag on, and the effect above loads the history.
      void onRequestOperatorToken()
      return
    }
    loadRevisions(itemId)
  }

  const inspectWorkspace = async () => {
    if (!item) return
    setWorkspaceLoading(true)
    setErrorMessage(null)
    try {
      const response = await onFetchWorkspaces(item.scope_id)
      const workspace = response.workspaces.find((candidate) => candidate.leased_item_id === item.id)
      if (!workspace?.leased_at) throw new Error('No current lease was found for this work item.')
      setOperatorAction({ kind: 'force_release', workspace })
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to inspect workspace')
    } finally {
      setWorkspaceLoading(false)
    }
  }

  const submitOperatorAction = async () => {
    if (!item || !operatorAction) return
    if (['abandon', 'cancel_revision', 'force_release'].includes(operatorAction.kind) && !actionReason.trim()) {
      setErrorMessage('Enter a reason before continuing.')
      return
    }
    setActionSaving(true)
    setErrorMessage(null)
    setActionResult(null)
    try {
      const action = operatorAction
      const result = await onOperate(item, action, actionReason.trim(), reassignToSlotId === 'current' ? undefined : Number(reassignToSlotId))
      const actionMessages: Record<ItemOperatorAction['kind'], string> = {
        abandon: 'Work item abandoned.',
        resume: 'Prepared attempt queued for resumption.',
        release_decision: 'Decision hold released. The Leader can now decide.',
        release_ack: 'Acknowledgement hold released. The owner can now acknowledge.',
        cancel_request: 'Continuation request cancelled.',
        cancel_revision: 'Active continuation cancelled.',
        force_release: 'Workspace lease released.',
      }
      setActionResult(result ?? actionMessages[action.kind])
      setOperatorAction(null)
      setActionReason('')
      loadRevisions(item.id)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Operator action failed')
    } finally {
      setActionSaving(false)
    }
  }

  return (
    <div className="space-y-4 break-words [&_dd]:min-w-0 [&_dd]:[overflow-wrap:anywhere]" aria-label="Item actions">
              {attention && (
                <section className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-4" aria-label="Your action needed">
                  <h3 className="font-medium">{attention.label}</h3>
                  <p className="mt-2 text-sm">{attention.reason}</p>
                  {item.last_verified_sha && (
                    <p className="mt-2 text-xs text-muted-foreground">Last head verified by Deck: <code>{item.last_verified_sha.slice(0, 12)}</code>. Check the current PR head and review evidence before merging.</p>
                  )}
                  {prUrl(item) ? (
                    <a href={prUrl(item)!} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-2 font-medium text-primary">
                      <GitPullRequest className="h-4 w-4" />
                      {attention.linkLabel} #{item.pr_number}
                    </a>
                  ) : <p className="mt-2 text-sm">No PR is linked. Inspect the issue and recovery details below.</p>}
                </section>
              )}
              {item.dispatch_status === 'escalated' && (
                <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4">
                  <div className="flex items-center gap-2 font-medium text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    Why this escalated
                  </div>
                  <p className="mt-2 text-sm">{escalationReasonLabel(item.escalation_reason)}</p>
                  {item.status_note && (
                    <p className="mt-2 text-sm text-muted-foreground">{item.status_note}</p>
                  )}
                </div>
              )}
              {errorMessage && (
                <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                  {errorMessage}
                </div>
              )}
              {actionResult && <p role="status" className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">{actionResult}</p>}
              {item.handoff_state && (
                <div className="rounded-lg border border-sky-500/40 bg-sky-500/10 p-4 text-sm">
                  <span className="font-medium">{ownerName ?? 'Current owner'}</span>
                  <span className="mx-2 text-muted-foreground">→ {readableCode(item.handoff_state)} handoff →</span>
                  <span className="font-medium">{handoffTargetName ?? 'target slot'}</span>
                </div>
              )}
              {!hideSummary && (
              <div className="rounded-lg border">
                <dl className="grid gap-0 text-sm">
                  <div className="grid grid-cols-1 gap-1 sm:grid-cols-[150px_minmax(0,1fr)] border-b p-3">
                    <dt className="text-muted-foreground">Status</dt>
                    <dd>{workItemStatusLabel(item, scope)}</dd>
                  </div>
                  <div className="grid grid-cols-1 gap-1 sm:grid-cols-[150px_minmax(0,1fr)] border-b p-3">
                    <dt className="text-muted-foreground">Owner</dt>
                    <dd className="space-y-2">
                      <p>{ownerName ?? 'Unassigned'} ({routeMethodLabel(item.routing_method)})</p>
                      {item.owner_slot_id && <AgentActivityBadge activity={ownerActivity} />}
                    </dd>
                  </div>
                  <div className="grid grid-cols-1 gap-1 sm:grid-cols-[150px_minmax(0,1fr)] border-b p-3">
                    <dt className="text-muted-foreground">Retries</dt>
                    <dd>implementation checks {item.retry_count} · diagnostic heads {item.diagnostic_retry_count}</dd>
                  </div>
                  <div className="grid grid-cols-1 gap-1 sm:grid-cols-[150px_minmax(0,1fr)] border-b p-3">
                    <dt className="text-muted-foreground">Attempt</dt>
                    <dd>{phaseLabel(item.attempt_phase)} · revision {item.active_scope_revision}</dd>
                  </div>
                  <div className="grid grid-cols-1 gap-1 sm:grid-cols-[150px_minmax(0,1fr)] border-b p-3">
                    <dt className="text-muted-foreground">Workspace</dt>
                    <dd className="truncate">{item.workspace_path ?? 'None leased'}</dd>
                  </div>
                  <div className="grid grid-cols-1 gap-1 sm:grid-cols-[150px_minmax(0,1fr)] p-3">
                    <dt className="text-muted-foreground">PR</dt>
                    <dd>{item.pr_number ? `#${item.pr_number}` : 'None yet'}</dd>
                  </div>
                </dl>
              </div>
              )}
              <WorkPublicationPanel item={item} ownerName={ownerName} ownerActivity={ownerActivity} />
              <section className="space-y-3 rounded-lg border p-4" aria-labelledby="attempt-recovery-title">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 id="attempt-recovery-title" className="font-semibold">Attempt recovery</h3>
                    <p className="text-sm text-muted-foreground">
                      {recoverySummary(item)}
                    </p>
                  </div>
                </div>
                {loadingRevisions && <p className="text-sm text-muted-foreground">Loading recovery history…</p>}
                {!loadingRevisions && !revisionError && revisions.length === 0 && (
                  <p className="text-sm text-muted-foreground">No continuation revisions recorded.</p>
                )}
                {!loadingRevisions && revisionError && (
                  <div className="flex flex-wrap items-center gap-2 text-sm text-destructive" role="alert">
                    <span>{revisionError}</span>
                    <Button variant="outline" size="sm" onClick={retryLoadRevisions}>
                      Retry loading history
                    </Button>
                  </div>
                )}
                {revisions.map((revision) => {
                  const approval = revision.approval_request
                  const links = safeEvidenceLinks(revision.evidence)
                  const sameAttempt = item.dispatch_nonce === revision.dispatch_nonce
                    && item.owner_slot_id === revision.owner_slot_id
                  const holdEligible = sameAttempt && item.dispatch_status === 'escalated'
                    && item.escalation_reason === revision.originating_escalation_reason
                  const activeCancellationEligible = sameAttempt && item.dispatch_status === 'dispatched'
                    && item.active_scope_revision === revision.revision && item.pr_number != null
                    && !item.handoff_state
                  const decisionReleaseEligible = holdEligible && revision.status === 'proposed'
                    && approval?.status === 'pending'
                  const acknowledgementReleaseEligible = holdEligible && revision.status === 'approved'
                    && approval?.status === 'approved' && !!revision.delivered_at
                  return (
                    <article key={revision.id} className="space-y-3 rounded-md border bg-muted/20 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">revision {revision.revision}</Badge>
                        <Badge variant="secondary" title={phaseHelp(revision.phase)}>{phaseLabel(revision.phase)}</Badge>
                        <span className="text-sm font-medium">{readableCode(revision.status)}</span>
                        <span className="text-xs text-muted-foreground">
                          failed heads {revision.failed_head_count}/{revision.max_failed_heads}
                        </span>
                      </div>
                      <p className="whitespace-pre-wrap text-sm">{revision.summary}</p>
                      <dl className="grid gap-2 text-sm md:grid-cols-2">
                        <div><dt className="text-muted-foreground">Origin</dt><dd>{escalationReasonLabel(revision.originating_escalation_reason)}</dd></div>
                        <div><dt className="text-muted-foreground">Execution</dt><dd>{readableCode(revision.execution_target)}</dd></div>
                        <div><dt className="text-muted-foreground">Owner</dt><dd title={`Member #${revision.owner_member_id}`}>{slots.find((slot) => slot.id === revision.owner_slot_id)?.display_name ?? `slot #${revision.owner_slot_id}`}</dd></div>
                        <div><dt className="text-muted-foreground">Workspace</dt><dd title={`Workspace #${revision.expected_workspace_id}`}>{sameAttempt && item.active_scope_revision === revision.revision && item.workspace_path ? item.workspace_path : `#${revision.expected_workspace_id}`}</dd></div>
                        {approval && (
                          <>
                            <div><dt className="text-muted-foreground">Approval</dt><dd title={`Request #${approval.id}`}>{approvalStatusLabel(approval.status)}</dd></div>
                            <div><dt className="text-muted-foreground">Approver</dt><dd title={`Member #${approval.leader_member_id}`}>Leader agent</dd></div>
                          </>
                        )}
                        <div><dt className="text-muted-foreground">Delivered</dt><dd>{formatDateTime(revision.delivered_at)}</dd></div>
                        <div><dt className="text-muted-foreground">Acknowledged</dt><dd>{formatDateTime(revision.acknowledged_at)}</dd></div>
                      </dl>
                      <div className="grid gap-2 text-sm">
                        <div><span className="text-muted-foreground">Paths:</span> <span className="break-all">{revision.allowed_paths.join(', ') || 'none'}</span></div>
                        <div><span className="text-muted-foreground">Actions:</span> <span className="break-all">{revision.allowed_actions.join(', ') || 'none'}</span></div>
                        <div><span className="text-muted-foreground">Commands:</span> <span className="whitespace-pre-wrap break-all">{revision.allowed_commands.join('\n') || 'none'}</span></div>
                      </div>
                      {revision.result_summary && <p className="text-sm">Result: {revision.result_summary}</p>}
                      {links.length > 0 && (
                        <div className="flex flex-wrap gap-2">
                          {links.map((link) => (
                            <a
                              key={`${revision.id}-${link.label}`}
                              href={link.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-sm text-primary underline-offset-4 hover:underline"
                            >
                              {readableCode(link.label)}
                            </a>
                          ))}
                        </div>
                      )}
                      {approval?.status === 'pending' && (
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={!sameAttempt || item.dispatch_status !== 'escalated'}
                          title={!sameAttempt || item.dispatch_status !== 'escalated' ? 'This request is no longer current.' : undefined}
                          onClick={() => setOperatorAction({ kind: 'cancel_request', revision })}
                        >
                          <XCircle className="mr-2 h-4 w-4" />
                          Cancel request #{approval.id}
                        </Button>
                      )}
                      {revision.recovery_checkpoint_stage === 'decision_hold' && (
                        <Button variant="outline" size="sm" disabled={!decisionReleaseEligible} title={decisionReleaseEligible ? 'Recovery is paused. Release opens a time-limited window for the Leader to decide.' : 'This decision hold is no longer releasable.'} onClick={() => setOperatorAction({ kind: 'release_decision', revision })}>
                          Release decision hold
                        </Button>
                      )}
                      {revision.recovery_checkpoint_stage === 'ack_hold' && (
                        <Button variant="outline" size="sm" disabled={!acknowledgementReleaseEligible} title={acknowledgementReleaseEligible ? 'Recovery is paused. Release opens a time-limited window for the owner to acknowledge.' : 'This acknowledgement hold is no longer releasable.'} onClick={() => setOperatorAction({ kind: 'release_ack', revision })}>
                          Release acknowledgement hold
                        </Button>
                      )}
                      {revision.status === 'active' && (
                        <Button variant="destructive" size="sm" disabled={!activeCancellationEligible} title={!activeCancellationEligible ? 'This revision is no longer the active dispatched attempt.' : undefined} onClick={() => setOperatorAction({ kind: 'cancel_revision', revision })}>
                          Cancel active revision
                        </Button>
                      )}
                    </article>
                  )
                })}
              </section>
              <section className="space-y-3 rounded-lg border p-4" aria-labelledby="operator-actions-title">
                <div>
                  <h3 id="operator-actions-title" className="font-semibold">Operator remedies</h3>
                  <p className="text-sm text-muted-foreground">Only remedies valid for this state appear. Deck checks current authority before changing the issue.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {item.escalation_reason === 'prepared_owner_unavailable' && (
                    <Button variant="outline" size="sm" onClick={() => setOperatorAction({ kind: 'resume' })}>
                      Resume prepared attempt
                    </Button>
                  )}
                  {['ready_for_review', 'awaiting_human_review', 'dispatched', 'verifying'].includes(item.dispatch_status) && (
                    <Button variant="outline" size="sm" onClick={() => setOperatorAction({ kind: 'abandon' })}>
                      Abandon work item
                    </Button>
                  )}
                  {item.workspace_path && (
                    <Button variant="destructive" size="sm" title="Reclaim the leased worktree if the owner is gone; this may discard unpushed work." disabled={workspaceLoading} onClick={() => void inspectWorkspace()}>
                      {workspaceLoading ? 'Checking lease…' : 'Force-release workspace…'}
                    </Button>
                  )}
                </div>
              </section>
      {onRetry && item.retry_allowed && (
        <Button onClick={() => onRetry(item)}>
          <RotateCcw className="mr-2 h-4 w-4" />
          Retry
        </Button>
      )}
            <AlertDialog open={operatorAction !== null} onOpenChange={(next) => { if (!next) { setOperatorAction(null); setActionReason('') } }}>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>
                    {operatorAction?.kind === 'force_release' ? 'Force-release leased workspace?' :
                      operatorAction?.kind === 'resume' ? 'Resume prepared attempt?' :
                      operatorAction?.kind === 'abandon' ? 'Abandon work item?' :
                      operatorAction?.kind === 'cancel_revision' ? 'Cancel active revision?' :
                      operatorAction?.kind === 'cancel_request' ? 'Cancel continuation request?' :
                      'Release recovery checkpoint?'}
                  </AlertDialogTitle>
                  <AlertDialogDescription>
                    {operatorAction?.kind === 'force_release'
                      ? `This may discard dirty or unpushed work in ${operatorAction.workspace.path}. Lease acquired ${formatDateTime(operatorAction.workspace.leased_at)}. Verify the owner is finished before continuing.`
                      : operatorAction?.kind === 'release_decision' || operatorAction?.kind === 'release_ack'
                        ? 'This starts a time-limited decision or acknowledgement window. Confirm the responsible agent is available now.'
                        : 'Deck will check current authority and reject stale or ineligible requests.'}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                {operatorAction?.kind === 'resume' && (
                  <div className="grid gap-2">
                    <Label htmlFor="resume-slot">Assign owner slot</Label>
                    <Select value={reassignToSlotId} onValueChange={setReassignToSlotId}>
                      <SelectTrigger id="resume-slot"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="current">Keep current owner</SelectItem>
                        {slots.filter((slot) => slot.enabled).map((slot) => (
                          <SelectItem key={slot.id} value={String(slot.id)}>{slot.display_name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                {operatorAction && ['abandon', 'cancel_revision', 'force_release'].includes(operatorAction.kind) && (
                  <div className="grid gap-2">
                    <Label htmlFor="operator-action-reason">Reason for audit</Label>
                    <Input id="operator-action-reason" value={actionReason} onChange={(event) => setActionReason(event.target.value)} />
                  </div>
                )}
                {errorMessage && <p className="text-sm text-destructive" role="alert">{errorMessage}</p>}
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction disabled={actionSaving} onClick={(event) => { event.preventDefault(); void submitOperatorAction() }}>
                    {actionSaving ? 'Applying…' : 'Confirm action'}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
    </div>
  )
}
