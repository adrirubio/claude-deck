import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, ExternalLink, GitPullRequest, Plus, RefreshCw, RotateCcw, Trash2 } from 'lucide-react'
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
  GithubWorkItem,
  TeamGithubMergePolicy,
  TeamGithubScope,
  TeamGithubScopeInput,
  TeamGithubScopeUpdate,
} from '@/types/agentTeams'

type ScopeDialogState = { mode: 'add' | 'edit'; scope?: TeamGithubScope } | null

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

function WorkItemDialog({
  item,
  ownerName,
  handoffTargetName,
  onOpenChange,
  onRetry,
}: {
  item: GithubWorkItem | null
  ownerName?: string
  handoffTargetName?: string
  onOpenChange: (open: boolean) => void
  onRetry: (item: GithubWorkItem) => Promise<void>
}) {
  const [retrying, setRetrying] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const open = item !== null

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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.SM}>
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
                    <dd>{item.retry_count}</dd>
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
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
              {item.dispatch_status === 'escalated' && (
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
  onDeleteScope,
  onRetryWorkItem,
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
  onDeleteScope: (scope: TeamGithubScope) => Promise<void>
  onRetryWorkItem: (item: GithubWorkItem) => Promise<void>
}) {
  const [scopeDialog, setScopeDialog] = useState<ScopeDialogState>(null)
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
                    {!scope.enabled && <Badge variant="secondary">disabled</Badge>}
                  </div>
                  <p className="mt-2 truncate text-sm text-muted-foreground">
                    Worktree parent: {scope.repo_path}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Approval rounds: {scope.max_approval_rounds} · Concurrent: {scope.max_concurrent_dispatched} · Verification retries: {scope.max_verification_retries} · Auto-merges/day: {scope.max_auto_merges_per_day} · Last polled {formatDateTime(scope.last_polled_at)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
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
                          <Badge variant={item.issue_type === 'design' ? 'default' : 'secondary'}>
                            {item.issue_type}
                          </Badge>
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
                          {item.retry_count > 0 && (
                            <p className="mt-1 text-xs text-muted-foreground">retries: {item.retry_count}</p>
                          )}
                        </td>
                        <td className="px-3 py-3 text-right">
                          <div className="flex justify-end gap-2">
                            {item.dispatch_status === 'escalated' && (
                              <Button
                                size="sm"
                                disabled={retryingWorkItemId !== null}
                                onClick={() => void retryWorkItem(item)}
                              >
                                <RotateCcw className="mr-2 h-4 w-4" />
                                {retryingWorkItemId === item.id ? 'Retrying' : 'Retry'}
                              </Button>
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
      />
    </div>
  )
}
