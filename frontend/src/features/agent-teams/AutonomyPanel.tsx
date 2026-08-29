import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, ExternalLink, GitPullRequest, KeyRound, Plus, RefreshCw, RotateCcw, Trash2, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { MODAL_SIZES } from '@/lib/constants'
import { cn } from '@/lib/utils'
import type {
  AgentTeamPreset,
  GithubScopeRevision,
  GithubWorkItem,
  TeamGithubContinuationPolicyUpdate,
  TeamGithubMergePolicy,
  TeamGithubScope,
  TeamGithubScopeInput,
  TeamGithubScopeUpdate,
} from '@/types/agentTeams'
import { clearOperatorToken, getOperatorToken, setOperatorToken } from './operatorAuth'

type ScopeDialogState = { mode: 'add' | 'edit'; scope?: TeamGithubScope } | null
type PolicyDialogState = { scope: TeamGithubScope } | null

const emptyScope: TeamGithubScopeInput = {
  repo_owner: '',
  repo_name: '',
  repo_path: '',
  dispatch_label: 'claude-deck-ready',
  design_label: 'claude-deck-design',
  merge_policy: 'human',
  max_approval_rounds: 3,
  max_concurrent_dispatched: 3,
  max_verification_retries: 2,
  max_auto_merges_per_day: 5,
  enabled: true,
}

function scopeToInput(scope: TeamGithubScope): TeamGithubScopeInput {
  return {
    repo_owner: scope.repo_owner,
    repo_name: scope.repo_name,
    repo_path: scope.repo_path,
    dispatch_label: scope.dispatch_label,
    design_label: scope.design_label,
    merge_policy: scope.merge_policy === 'auto' ? 'auto' : 'human',
    max_approval_rounds: scope.max_approval_rounds,
    max_concurrent_dispatched: scope.max_concurrent_dispatched,
    max_verification_retries: scope.max_verification_retries,
    max_auto_merges_per_day: scope.max_auto_merges_per_day,
    enabled: scope.enabled,
  }
}

function formatDateTime(value?: string | null) {
  if (!value) return 'never'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function routeMethodLabel(value?: string | null) {
  if (!value) return 'not routed'
  if (value === 'label') return 'label match'
  if (value === 'leader_fallback') return 'leader fallback'
  return value.replaceAll('_', ' ')
}

function pendingReasonLabel(item: GithubWorkItem, ownerName?: string) {
  if (item.pending_reason === 'queued_slot_busy') {
    return `queued · behind ${ownerName ?? 'assigned slot'}`
  }
  if (item.pending_reason === 'queued_repo_cap') return 'queued · repo cap reached'
  if (item.pending_reason === 'queued_no_workspace') return 'queued · no free workspace'
  if (item.pending_reason === 'queued_low_memory') return 'queued · low memory'
  if (item.pending_reason === 'queued_ambiguous_sessions') {
    return `queued · ${ownerName ?? 'owner'} has multiple sessions`
  }
  return null
}

function statusBadgeClass(status: string) {
  if (status === 'escalated' || status === 'failed') return 'border-destructive text-destructive'
  if (status === 'merged') return 'border-emerald-500/70 text-emerald-400'
  if (status === 'awaiting_human_review' || status === 'ready_for_review') {
    return 'border-sky-500/70 text-sky-400'
  }
  if (status === 'verifying' || status === 'dispatched') return 'border-primary/70 text-primary'
  return 'border-muted-foreground/50 text-muted-foreground'
}

function prUrl(item: GithubWorkItem) {
  if (!item.pr_number) return null
  return `https://github.com/${item.repo_owner}/${item.repo_name}/pull/${item.pr_number}`
}

function requestOperatorToken(): string | null {
  const current = getOperatorToken()
  if (current) return current
  const entered = window.prompt(
    'Enter the Deck operator token for this tab. It is stored only in sessionStorage.'
  )?.trim()
  if (!entered) return null
  setOperatorToken(entered)
  return entered
}

function recoveryBlockLabel(code?: string | null) {
  if (!code) return 'Recovery can continue within the current bounded attempt.'
  return code.replaceAll('_', ' ')
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

function ScopeDialog({
  state,
  onOpenChange,
  onSave,
}: {
  state: ScopeDialogState
  onOpenChange: (state: ScopeDialogState) => void
  onSave: (scope: TeamGithubScopeInput | TeamGithubScopeUpdate) => Promise<void>
}) {
  const [form, setForm] = useState<TeamGithubScopeInput>(emptyScope)
  const [saving, setSaving] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const open = state !== null

  useEffect(() => {
    if (!state) return
    queueMicrotask(() => {
      setForm(state.scope ? scopeToInput(state.scope) : emptyScope)
      setErrorMessage(null)
    })
  }, [state])

  const update = (patch: Partial<TeamGithubScopeInput>) => {
    setForm((current) => ({ ...current, ...patch }))
  }

  const numberValue = (value: string, fallback: number, min: number) => {
    const parsed = Number.parseInt(value, 10)
    return Number.isFinite(parsed) ? Math.max(parsed, min) : fallback
  }

  const submit = async () => {
    setSaving(true)
    setErrorMessage(null)
    try {
      await onSave({
        ...form,
        repo_owner: form.repo_owner.trim(),
        repo_name: form.repo_name.trim(),
        repo_path: form.repo_path.trim(),
        dispatch_label: form.dispatch_label?.trim() || 'claude-deck-ready',
        design_label: form.design_label?.trim() || 'claude-deck-design',
      })
      onOpenChange(null)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to save watched repo')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => onOpenChange(next ? state : null)}>
      <DialogContent className={MODAL_SIZES.SM}>
        <DialogHeader>
          <DialogTitle>{state?.mode === 'edit' ? 'Edit watched repo' : 'Add watched repo'}</DialogTitle>
          <DialogDescription>
            This team will poll the repo for labeled issues and dispatch them automatically.
          </DialogDescription>
        </DialogHeader>
        {errorMessage && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {errorMessage}
          </div>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="scope-owner">Repo owner</Label>
            <Input
              id="scope-owner"
              value={form.repo_owner}
              onChange={(event) => update({ repo_owner: event.target.value })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="scope-name">Repo name</Label>
            <Input
              id="scope-name"
              value={form.repo_name}
              onChange={(event) => update({ repo_name: event.target.value })}
            />
          </div>
          <div className="grid gap-2 md:col-span-2">
            <Label htmlFor="scope-path">Local checkout path</Label>
            <Input
              id="scope-path"
              value={form.repo_path}
              onChange={(event) => update({ repo_path: event.target.value })}
            />
            <p className="text-xs text-muted-foreground">
              Used as the per-dispatch repo override; it does not change any slot&apos;s saved repo path.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="dispatch-label">Dispatch label</Label>
            <Input
              id="dispatch-label"
              value={form.dispatch_label}
              onChange={(event) => update({ dispatch_label: event.target.value })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="design-label">Design label</Label>
            <Input
              id="design-label"
              value={form.design_label}
              onChange={(event) => update({ design_label: event.target.value })}
            />
          </div>
          <div className="grid gap-2 md:col-span-2">
            <Label>Merge policy</Label>
            <Select
              value={form.merge_policy}
              onValueChange={(mergePolicy) => update({ merge_policy: mergePolicy as TeamGithubMergePolicy })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="human">Human reviews and merges</SelectItem>
                <SelectItem value="auto">Auto-merge after checks pass</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-amber-400">
              Applies to the code pipeline only. Design-pipeline PRs always require a human review.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="approval-rounds">Max approval rounds</Label>
            <Input
              id="approval-rounds"
              type="number"
              min={1}
              value={form.max_approval_rounds}
              onChange={(event) => update({
                max_approval_rounds: numberValue(event.target.value, 3, 1),
              })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="concurrent-dispatches">Max concurrent dispatched</Label>
            <Input
              id="concurrent-dispatches"
              type="number"
              min={1}
              value={form.max_concurrent_dispatched}
              onChange={(event) => update({
                max_concurrent_dispatched: numberValue(event.target.value, 3, 1),
              })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="verification-retries">Max verification retries</Label>
            <Input
              id="verification-retries"
              type="number"
              min={0}
              value={form.max_verification_retries}
              onChange={(event) => update({
                max_verification_retries: numberValue(event.target.value, 2, 0),
              })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="auto-merges">Max auto-merges per day</Label>
            <Input
              id="auto-merges"
              type="number"
              min={0}
              value={form.max_auto_merges_per_day}
              onChange={(event) => update({
                max_auto_merges_per_day: numberValue(event.target.value, 5, 0),
              })}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={form.enabled} onCheckedChange={(checked) => update({ enabled: checked === true })} />
            Enabled
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(null)}>Cancel</Button>
          <Button
            onClick={submit}
            disabled={saving || !form.repo_owner.trim() || !form.repo_name.trim() || !form.repo_path.trim()}
          >
            {saving ? 'Saving' : 'Save repo'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ContinuationPolicyDialog({
  state,
  autonomyEnabled,
  onOpenChange,
  onSave,
}: {
  state: PolicyDialogState
  autonomyEnabled: boolean
  onOpenChange: (state: PolicyDialogState) => void
  onSave: (
    scopeId: number,
    input: TeamGithubContinuationPolicyUpdate,
    operatorToken: string
  ) => Promise<void>
}) {
  const scope = state?.scope ?? null
  const [form, setForm] = useState<TeamGithubContinuationPolicyUpdate | null>(null)
  const [saving, setSaving] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!scope) return
    queueMicrotask(() => {
      setForm({
        continuation_enabled: scope.continuation_enabled,
        max_continuation_revisions: scope.max_continuation_revisions,
        max_continuation_failed_heads: scope.max_continuation_failed_heads,
        max_failed_heads_per_revision: scope.max_failed_heads_per_revision,
        max_scope_paths: scope.max_scope_paths,
        max_scope_commands: scope.max_scope_commands,
      })
      setErrorMessage(null)
    })
  }, [scope])

  const updateNumber = (key: keyof TeamGithubContinuationPolicyUpdate, value: string) => {
    const parsed = Number.parseInt(value, 10)
    setForm((current) => current ? { ...current, [key]: Number.isFinite(parsed) ? Math.max(1, parsed) : 1 } : current)
  }

  const submit = async () => {
    if (!scope || !form) return
    if (form.max_failed_heads_per_revision > form.max_continuation_failed_heads) {
      setErrorMessage('Per-revision failed heads cannot exceed the attempt-wide failed-head cap.')
      return
    }
    if (
      form.continuation_enabled
      && !scope.continuation_enabled
      && autonomyEnabled
      && !window.confirm(
        'Autonomy is already enabled. Enabling continuation lets eligible escalated attempts recover automatically. Continue?'
      )
    ) return
    const token = requestOperatorToken()
    if (!token) {
      setErrorMessage('The Deck operator token is required for policy changes.')
      return
    }
    setSaving(true)
    setErrorMessage(null)
    try {
      await onSave(scope.id, form, token)
      onOpenChange(null)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to save recovery policy')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={state !== null} onOpenChange={(open) => onOpenChange(open ? state : null)}>
      <DialogContent className={MODAL_SIZES.SM}>
        <DialogHeader>
          <DialogTitle>Attempt recovery policy</DialogTitle>
          <DialogDescription>
            {scope ? `${scope.repo_owner}/${scope.repo_name}` : 'Configure finite continuation limits.'}
          </DialogDescription>
        </DialogHeader>
        {errorMessage && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {errorMessage}
          </div>
        )}
        {form && (
          <div className="grid gap-4 md:grid-cols-2">
            <label className="flex items-center gap-2 text-sm md:col-span-2">
              <Checkbox
                checked={form.continuation_enabled}
                onCheckedChange={(checked) => setForm({ ...form, continuation_enabled: checked === true })}
              />
              Enable bounded attempt continuation
            </label>
            {([
              ['max_continuation_revisions', 'Attempt revision cap'],
              ['max_continuation_failed_heads', 'Attempt failed-head cap'],
              ['max_failed_heads_per_revision', 'Per-revision failed-head cap'],
              ['max_scope_paths', 'Paths per revision'],
              ['max_scope_commands', 'Commands per revision'],
            ] as const).map(([key, label]) => (
              <div className="grid gap-2" key={key}>
                <Label htmlFor={`policy-${key}`}>{label}</Label>
                <Input
                  id={`policy-${key}`}
                  type="number"
                  min={1}
                  value={form[key]}
                  onChange={(event) => updateNumber(key, event.target.value)}
                />
              </div>
            ))}
            <p className="text-xs text-muted-foreground md:col-span-2">
              Recovery runs only when both this policy and team autonomy are enabled. Finite caps stop repeated recovery honestly.
            </p>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(null)}>Cancel</Button>
          <Button onClick={submit} disabled={saving || !form}>
            {saving ? 'Saving' : 'Save recovery policy'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function WorkItemDialog({
  item,
  ownerName,
  handoffTargetName,
  onOpenChange,
  onRetry,
  onFetchScopeRevisions,
  onCancelContinuationRequest,
}: {
  item: GithubWorkItem | null
  ownerName?: string
  handoffTargetName?: string
  onOpenChange: (open: boolean) => void
  onRetry: (item: GithubWorkItem) => Promise<void>
  onFetchScopeRevisions: (
    item: GithubWorkItem,
    operatorToken: string
  ) => Promise<GithubScopeRevision[]>
  onCancelContinuationRequest: (
    item: GithubWorkItem,
    requestId: number,
    operatorToken: string
  ) => Promise<void>
}) {
  const [retrying, setRetrying] = useState(false)
  const [loadingRevisions, setLoadingRevisions] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [revisions, setRevisions] = useState<GithubScopeRevision[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const loadedItemIdRef = useRef<number | null>(null)
  const open = item !== null

  useEffect(() => {
    if (!item || loadedItemIdRef.current === item.id) return
    loadedItemIdRef.current = item.id
    const token = requestOperatorToken()
    if (!token) {
      queueMicrotask(() => setErrorMessage('Operator token required to load exact recovery history.'))
      return
    }
    let cancelled = false
    queueMicrotask(() => setLoadingRevisions(true))
    void onFetchScopeRevisions(item, token)
      .then((rows) => {
        if (!cancelled) setRevisions(rows)
      })
      .catch((error) => {
        if (!cancelled) {
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load recovery history')
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingRevisions(false)
      })
    return () => {
      cancelled = true
    }
  }, [item, onFetchScopeRevisions])

  const retry = async () => {
    if (!item) return
    setRetrying(true)
    setErrorMessage(null)
    try {
      await onRetry(item)
      onOpenChange(false)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to retry work item')
    } finally {
      setRetrying(false)
    }
  }

  const cancelPending = async (revision: GithubScopeRevision) => {
    if (!item || !revision.approval_request || revision.approval_request.status !== 'pending') return
    const approval = revision.approval_request
    if (!window.confirm(
      `Cancel continuation request #${approval.id} for revision ${revision.revision}?`
    )) return
    const token = requestOperatorToken()
    if (!token) {
      setErrorMessage('The Deck operator token is required to cancel a continuation request.')
      return
    }
    setCancelling(true)
    setErrorMessage(null)
    try {
      await onCancelContinuationRequest(item, approval.id, token)
      const refreshed = await onFetchScopeRevisions(item, token)
      setRevisions(refreshed)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to cancel continuation')
    } finally {
      setCancelling(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(MODAL_SIZES.LG, 'overflow-y-auto')}>
        {item && (
          <>
            <DialogHeader>
              <DialogTitle>#{item.issue_number} — {item.issue_title}</DialogTitle>
              <DialogDescription>
                {item.repo_owner}/{item.repo_name} · updated {formatDateTime(item.updated_at)}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              {item.dispatch_status === 'escalated' && (
                <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4">
                  <div className="flex items-center gap-2 font-medium text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    Why this escalated
                  </div>
                  <p className="mt-2 text-sm">{item.escalation_reason ?? 'Unknown reason'}</p>
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
              {item.handoff_state && (
                <div className="rounded-lg border border-sky-500/40 bg-sky-500/10 p-4 text-sm">
                  <span className="font-medium">{ownerName ?? 'Current owner'}</span>
                  <span className="mx-2 text-muted-foreground">→ handoff {item.handoff_state} →</span>
                  <span className="font-medium">{handoffTargetName ?? 'target slot'}</span>
                </div>
              )}
              <div className="rounded-lg border">
                <dl className="grid gap-0 text-sm">
                  <div className="grid grid-cols-[150px_1fr] border-b p-3">
                    <dt className="text-muted-foreground">Status</dt>
                    <dd>{item.dispatch_status}</dd>
                  </div>
                  <div className="grid grid-cols-[150px_1fr] border-b p-3">
                    <dt className="text-muted-foreground">Owner</dt>
                    <dd>{ownerName ?? 'Unassigned'} ({routeMethodLabel(item.routing_method)})</dd>
                  </div>
                  <div className="grid grid-cols-[150px_1fr] border-b p-3">
                    <dt className="text-muted-foreground">Retries</dt>
                    <dd>product {item.retry_count} · diagnostic {item.diagnostic_retry_count}</dd>
                  </div>
                  <div className="grid grid-cols-[150px_1fr] border-b p-3">
                    <dt className="text-muted-foreground">Attempt</dt>
                    <dd>{item.attempt_phase} · revision {item.active_scope_revision}</dd>
                  </div>
                  <div className="grid grid-cols-[150px_1fr] border-b p-3">
                    <dt className="text-muted-foreground">Workspace</dt>
                    <dd className="truncate">{item.workspace_path ?? 'None leased'}</dd>
                  </div>
                  <div className="grid grid-cols-[150px_1fr] p-3">
                    <dt className="text-muted-foreground">PR</dt>
                    <dd>{item.pr_number ? `#${item.pr_number}` : 'None yet'}</dd>
                  </div>
                </dl>
              </div>
              <section className="space-y-3 rounded-lg border p-4" aria-labelledby="attempt-recovery-title">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 id="attempt-recovery-title" className="font-semibold">Attempt recovery</h3>
                    <p className="text-sm text-muted-foreground">
                      {recoveryBlockLabel(item.continuation_block_code)}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      clearOperatorToken()
                      setErrorMessage('Operator token cleared for this tab.')
                    }}
                  >
                    <KeyRound className="mr-2 h-4 w-4" />
                    Clear operator token
                  </Button>
                </div>
                {loadingRevisions && <p className="text-sm text-muted-foreground">Loading recovery history...</p>}
                {!loadingRevisions && revisions.length === 0 && (
                  <p className="text-sm text-muted-foreground">No continuation revisions recorded.</p>
                )}
                {revisions.map((revision) => {
                  const approval = revision.approval_request
                  const links = safeEvidenceLinks(revision.evidence)
                  return (
                    <article key={revision.id} className="space-y-3 rounded-md border bg-muted/20 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">revision {revision.revision}</Badge>
                        <Badge variant="secondary">{revision.phase}</Badge>
                        <span className="text-sm font-medium">{revision.status}</span>
                        <span className="text-xs text-muted-foreground">
                          failed heads {revision.failed_head_count}/{revision.max_failed_heads}
                        </span>
                      </div>
                      <p className="whitespace-pre-wrap text-sm">{revision.summary}</p>
                      <dl className="grid gap-2 text-sm md:grid-cols-2">
                        <div><dt className="text-muted-foreground">Origin</dt><dd>{revision.originating_escalation_reason}</dd></div>
                        <div><dt className="text-muted-foreground">Execution</dt><dd>{revision.execution_target}</dd></div>
                        <div><dt className="text-muted-foreground">Owner</dt><dd>slot #{revision.owner_slot_id} · member #{revision.owner_member_id}</dd></div>
                        <div><dt className="text-muted-foreground">Workspace</dt><dd>#{revision.expected_workspace_id}</dd></div>
                        {approval && (
                          <>
                            <div><dt className="text-muted-foreground">Approval</dt><dd>request #{approval.id} · {approval.status}</dd></div>
                            <div><dt className="text-muted-foreground">Leader</dt><dd>member #{approval.leader_member_id}</dd></div>
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
                              {link.label}
                            </a>
                          ))}
                        </div>
                      )}
                      {approval?.status === 'pending' && (
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={cancelling}
                          onClick={() => void cancelPending(revision)}
                        >
                          <XCircle className="mr-2 h-4 w-4" />
                          {cancelling ? 'Cancelling' : `Cancel request #${approval.id}`}
                        </Button>
                      )}
                    </article>
                  )
                })}
              </section>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
              {item.retry_allowed && (
                <Button onClick={retry} disabled={retrying}>
                  <RotateCcw className="mr-2 h-4 w-4" />
                  {retrying ? 'Retrying' : 'Retry'}
                </Button>
              )}
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function AutonomyPanel({
  preset,
  scopes,
  workItems,
  loading,
  refreshing,
  onRefresh,
  onToggleAutonomy,
  onCreateScope,
  onUpdateScope,
  onUpdateContinuationPolicy,
  onDeleteScope,
  onRetryWorkItem,
  onFetchScopeRevisions,
  onCancelContinuationRequest,
}: {
  preset: AgentTeamPreset
  scopes: TeamGithubScope[]
  workItems: GithubWorkItem[]
  loading: boolean
  refreshing: boolean
  onRefresh: () => Promise<void>
  onToggleAutonomy: (enabled: boolean) => Promise<void>
  onCreateScope: (input: TeamGithubScopeInput) => Promise<void>
  onUpdateScope: (scopeId: number, input: TeamGithubScopeUpdate) => Promise<void>
  onUpdateContinuationPolicy: (
    scopeId: number,
    input: TeamGithubContinuationPolicyUpdate,
    operatorToken: string
  ) => Promise<void>
  onDeleteScope: (scope: TeamGithubScope) => Promise<void>
  onRetryWorkItem: (item: GithubWorkItem) => Promise<void>
  onFetchScopeRevisions: (
    item: GithubWorkItem,
    operatorToken: string
  ) => Promise<GithubScopeRevision[]>
  onCancelContinuationRequest: (
    item: GithubWorkItem,
    requestId: number,
    operatorToken: string
  ) => Promise<void>
}) {
  const [scopeDialog, setScopeDialog] = useState<ScopeDialogState>(null)
  const [policyDialog, setPolicyDialog] = useState<PolicyDialogState>(null)
  const [detailItemId, setDetailItemId] = useState<number | null>(null)
  const [toggleSaving, setToggleSaving] = useState(false)
  const [retryingWorkItemId, setRetryingWorkItemId] = useState<number | null>(null)
  const slotById = useMemo(
    () => new Map(preset.slots.map((slot) => [slot.id, slot])),
    [preset.slots]
  )
  const scopeCount = scopes.length
  const detailItem = useMemo(
    () => workItems.find((item) => item.id === detailItemId) ?? null,
    [detailItemId, workItems]
  )

  const toggle = async (enabled: boolean) => {
    setToggleSaving(true)
    try {
      await onToggleAutonomy(enabled)
    } catch {
      // Parent handlers surface the error toast; keep the controlled switch stable.
    } finally {
      setToggleSaving(false)
    }
  }

  const saveScope = async (input: TeamGithubScopeInput | TeamGithubScopeUpdate) => {
    if (scopeDialog?.mode === 'edit' && scopeDialog.scope) {
      await onUpdateScope(scopeDialog.scope.id, input)
    } else {
      await onCreateScope(input as TeamGithubScopeInput)
    }
  }

  const deleteScope = async (scope: TeamGithubScope) => {
    try {
      await onDeleteScope(scope)
    } catch {
      // Parent handlers surface the error toast.
    }
  }

  const retryWorkItem = async (item: GithubWorkItem) => {
    if (retryingWorkItemId !== null) return
    setRetryingWorkItemId(item.id)
    try {
      await onRetryWorkItem(item)
    } catch {
      // Parent handlers surface the error toast.
    } finally {
      setRetryingWorkItemId(null)
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-semibold">Autonomous GitHub dispatch</p>
            <p className="text-sm text-muted-foreground">
              Poll watched repos for labeled issues and dispatch work into this team automatically.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">
              {preset.autonomy_enabled ? 'Enabled' : 'Disabled'}
            </span>
            <Switch
              checked={preset.autonomy_enabled}
              disabled={toggleSaving}
              onCheckedChange={toggle}
            />
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Watched repos</h2>
          <p className="text-sm text-muted-foreground">{scopeCount} configured scope{scopeCount === 1 ? '' : 's'}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={() => {
              clearOperatorToken()
              window.alert('The operator token for this tab has been cleared.')
            }}
          >
            <KeyRound className="mr-2 h-4 w-4" />
            Clear operator token
          </Button>
          <Button variant="outline" onClick={onRefresh} disabled={refreshing}>
            <RefreshCw className={cn('mr-2 h-4 w-4', refreshing && 'animate-spin')} />
            Refresh
          </Button>
          <Button onClick={() => setScopeDialog({ mode: 'add' })}>
            <Plus className="mr-2 h-4 w-4" />
            Add repo
          </Button>
        </div>
      </div>

      <div className="grid gap-3">
        {loading && <div className="rounded-lg border p-5 text-sm text-muted-foreground">Loading autonomy state...</div>}
        {!loading && scopes.length === 0 && (
          <div className="rounded-lg border p-5 text-sm text-muted-foreground">
            No watched repos yet. Add a scope before enabling autonomy for useful work.
          </div>
        )}
        {scopes.map((scope) => (
          <Card key={scope.id} className={cn(!scope.enabled && 'opacity-70')}>
            <CardContent className="p-4">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold">{scope.repo_owner}/{scope.repo_name}</p>
                    <Badge variant="outline">{scope.dispatch_label}</Badge>
                    <Badge variant="secondary">{scope.design_label}</Badge>
                    <Badge
                      variant="outline"
                      className={scope.merge_policy === 'auto' ? 'border-primary text-primary' : 'border-amber-500/70 text-amber-400'}
                    >
                      code merge: {scope.merge_policy}
                    </Badge>
                    <Badge
                      variant="outline"
                      className={scope.continuation_enabled ? 'border-emerald-500/70 text-emerald-600 dark:text-emerald-400' : undefined}
                    >
                      recovery: {scope.continuation_enabled ? 'enabled' : 'off'}
                    </Badge>
                    {!scope.enabled && <Badge variant="secondary">disabled</Badge>}
                  </div>
                  <p className="mt-2 truncate text-sm text-muted-foreground">
                    Worktree parent: {scope.repo_path}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Approval rounds: {scope.max_approval_rounds} · Concurrent: {scope.max_concurrent_dispatched} · Verification retries: {scope.max_verification_retries} · Auto-merges/day: {scope.max_auto_merges_per_day} · Last polled {formatDateTime(scope.last_polled_at)}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Recovery limits: {scope.max_continuation_revisions} revisions · {scope.max_continuation_failed_heads} failed heads total · {scope.max_failed_heads_per_revision} per revision · {scope.max_scope_paths} paths · {scope.max_scope_commands} commands
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" onClick={() => setPolicyDialog({ scope })}>
                    <KeyRound className="mr-2 h-4 w-4" />
                    Recovery policy
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setScopeDialog({ mode: 'edit', scope })}>
                    Edit
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => void deleteScope(scope)}>
                    <Trash2 className="mr-2 h-4 w-4" />
                    Remove
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3">
          <div>
            <CardTitle>Activity</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">Recent GitHub work items across this preset&apos;s scopes.</p>
          </div>
          <Badge variant="secondary">auto-refreshes</Badge>
        </CardHeader>
        <CardContent>
          {workItems.length === 0 ? (
            <div className="rounded-lg border p-5 text-sm text-muted-foreground">
              No GitHub work items yet.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Issue</th>
                    <th className="px-3 py-2 font-medium">Type</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Owner</th>
                    <th className="px-3 py-2 font-medium">PR</th>
                    <th className="px-3 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {workItems.map((item) => {
                    const owner = item.owner_slot_id ? slotById.get(item.owner_slot_id) : undefined
                    const handoffTarget = item.handoff_target_slot_id
                      ? slotById.get(item.handoff_target_slot_id)
                      : undefined
                    const pendingLabel = pendingReasonLabel(item, owner?.display_name)
                    const pullUrl = prUrl(item)
                    return (
                      <tr key={item.id} className="border-b last:border-0">
                        <td className="min-w-[280px] px-3 py-3">
                          <a
                            href={item.issue_url}
                            target="_blank"
                            rel="noreferrer"
                            className="font-medium text-foreground hover:text-primary"
                          >
                            #{item.issue_number} — {item.issue_title}
                          </a>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {item.repo_owner}/{item.repo_name} · updated {formatDateTime(item.updated_at)}
                          </p>
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex flex-wrap gap-1">
                            <Badge variant={item.issue_type === 'design' ? 'default' : 'secondary'}>
                              {item.issue_type}
                            </Badge>
                            <Badge variant="outline">{item.attempt_phase}</Badge>
                          </div>
                          {item.active_scope_revision > 0 && (
                            <p className="mt-1 text-xs text-muted-foreground">revision {item.active_scope_revision}</p>
                          )}
                        </td>
                        <td className="px-3 py-3">
                          <Badge variant="outline" className={statusBadgeClass(item.dispatch_status)}>
                            {item.dispatch_status.replaceAll('_', ' ')}
                          </Badge>
                          {pendingLabel && <p className="mt-1 text-xs text-muted-foreground">{pendingLabel}</p>}
                          {item.handoff_state && (
                            <p className="mt-1 text-xs text-sky-400">
                              handoff {item.handoff_state}
                              {handoffTarget ? ` → ${handoffTarget.display_name}` : ''}
                            </p>
                          )}
                          {item.escalation_reason && (
                            <p className="mt-1 text-xs text-destructive">{item.escalation_reason}</p>
                          )}
                          {item.pending_approval_request_id && (
                            <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                              approval #{item.pending_approval_request_id} · {item.pending_approval_status ?? 'pending'}
                            </p>
                          )}
                          {item.pr_number && item.dispatch_status === 'escalated' && (
                            <p className="mt-1 text-xs text-primary">
                              Continue attempt · {recoveryBlockLabel(item.continuation_block_code)}
                            </p>
                          )}
                        </td>
                        <td className="px-3 py-3">
                          <span>{owner?.display_name ?? 'Unassigned'}</span>
                          <p className="mt-1 text-xs text-muted-foreground">{routeMethodLabel(item.routing_method)}</p>
                        </td>
                        <td className="px-3 py-3">
                          {pullUrl ? (
                            <a
                              href={pullUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-primary"
                            >
                              <GitPullRequest className="h-3.5 w-3.5" />
                              #{item.pr_number}
                            </a>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                          <p className="mt-1 text-xs text-muted-foreground">
                            product retries: {item.retry_count} · diagnostic heads: {item.diagnostic_retry_count}
                          </p>
                          {item.revision_failed_head_budget != null && (
                            <p className="mt-1 text-xs text-muted-foreground">
                              revision heads: {item.revision_failed_head_count ?? 0}/{item.revision_failed_head_budget}
                            </p>
                          )}
                        </td>
                        <td className="px-3 py-3 text-right">
                          <div className="flex justify-end gap-2">
                            {item.retry_allowed && (
                              <Button
                                size="sm"
                                disabled={retryingWorkItemId !== null}
                                onClick={() => void retryWorkItem(item)}
                              >
                                <RotateCcw className="mr-2 h-4 w-4" />
                                {retryingWorkItemId === item.id ? 'Retrying' : 'Retry'}
                              </Button>
                            )}
                            {item.dispatch_status === 'escalated' && !item.retry_allowed && (
                              <span className="max-w-44 text-left text-xs text-muted-foreground">
                                Retry blocked: {recoveryBlockLabel(item.retry_block_code)}
                              </span>
                            )}
                            <Button variant="outline" size="sm" onClick={() => setDetailItemId(item.id)}>
                              <ExternalLink className="mr-2 h-4 w-4" />
                              View
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <ScopeDialog state={scopeDialog} onOpenChange={setScopeDialog} onSave={saveScope} />
      <ContinuationPolicyDialog
        state={policyDialog}
        autonomyEnabled={preset.autonomy_enabled}
        onOpenChange={setPolicyDialog}
        onSave={onUpdateContinuationPolicy}
      />
      <WorkItemDialog
        key={detailItem?.id ?? 'closed'}
        item={detailItem}
        ownerName={detailItem?.owner_slot_id ? slotById.get(detailItem.owner_slot_id)?.display_name : undefined}
        handoffTargetName={
          detailItem?.handoff_target_slot_id
            ? slotById.get(detailItem.handoff_target_slot_id)?.display_name
            : undefined
        }
        onOpenChange={(open) => setDetailItemId(open ? detailItemId : null)}
        onRetry={onRetryWorkItem}
        onFetchScopeRevisions={onFetchScopeRevisions}
        onCancelContinuationRequest={onCancelContinuationRequest}
      />
    </div>
  )
}
