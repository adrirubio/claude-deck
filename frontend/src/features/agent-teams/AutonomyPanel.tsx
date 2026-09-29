import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Eye, GitPullRequest, KeyRound, Pencil, Plus, RefreshCw, RotateCcw, Settings2, Trash2, XCircle } from 'lucide-react'
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
import { SecretField } from '@/components/shared/SecretField'
import { ApiHttpError } from '@/lib/api'
import { fetchAgentMailTeam } from '@/features/agent-mail/api'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { MODAL_SIZES } from '@/lib/constants'
import { cn } from '@/lib/utils'
import type {
  AgentTeamPreset,
  AgentTeamSlot,
  GithubRecoveryGate,
  GithubScopeRevision,
  GithubWorkItem,
  GithubWorkspace,
  TeamGithubContinuationPolicyUpdate,
  TeamGithubMergePolicy,
  TeamGithubScope,
  TeamGithubScopeInput,
  TeamGithubScopeUpdate,
} from '@/types/agentTeams'
import { clearOperatorToken, getOperatorToken, setOperatorToken } from './operatorAuth'
import {
  abandonGithubWorkItem, cancelGithubActiveRevision, fetchGithubRecoveryGate,
  fetchGithubWorkspaces, forceReleaseGithubWorkspace, releaseGithubRecoveryCheckpoint,
  resumeGithubWorkItem,
} from './api'

type ScopeDialogState = { mode: 'add' | 'edit'; scope?: TeamGithubScope } | null
type PolicyDialogState = { scope: TeamGithubScope } | null
type ItemOperatorAction =
  | { kind: 'abandon' | 'resume' }
  | { kind: 'release_decision' | 'release_ack' | 'cancel_request' | 'cancel_revision'; revision: GithubScopeRevision }
  | { kind: 'force_release'; workspace: GithubWorkspace }
type ScopeNumberKey = 'max_approval_rounds' | 'max_concurrent_dispatched' | 'max_verification_retries' | 'max_auto_merges_per_day' | 'max_build_parallelism'
type PolicyNumberKey = Exclude<keyof TeamGithubContinuationPolicyUpdate, 'continuation_enabled'>

const scopeNumberKeys: ScopeNumberKey[] = [
  'max_approval_rounds', 'max_concurrent_dispatched', 'max_verification_retries', 'max_auto_merges_per_day', 'max_build_parallelism',
]
const policyNumberKeys: PolicyNumberKey[] = [
  'max_continuation_revisions', 'max_continuation_failed_heads', 'max_failed_heads_per_revision',
  'max_scope_paths', 'max_scope_commands',
]

function parsedLimit(value: string, label: string, minimum: number): number {
  const parsed = Number(value)
  if (!value.trim() || !Number.isInteger(parsed)) throw new Error(`Enter a whole number for ${label}.`)
  if (parsed < minimum) throw new Error(`${label} must be at least ${minimum}.`)
  return parsed
}

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
  base_ref: 'origin/HEAD',
  builds_out_of_tree: false,
  build_dir_template: 'build',
  build_command_hint: null,
  max_build_parallelism: 4,
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
    base_ref: scope.base_ref,
    builds_out_of_tree: scope.builds_out_of_tree,
    build_dir_template: scope.build_dir_template ?? 'build',
    build_command_hint: scope.build_command_hint,
    max_build_parallelism: scope.max_build_parallelism,
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
  if (item.pending_reason === 'queued_auth_mode_unresolved') {
    return 'queued · GitHub authentication needs configuration'
  }
  return null
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

function recoveryBlockLabel(code?: string | null) {
  if (!code) return 'Recovery can continue within the current bounded attempt.'
  return code.replaceAll('_', ' ')
}

function authModeLabel(mode: string) {
  if (mode === 'app') return 'GitHub App'
  if (mode === 'ambient') return 'Host credential'
  return 'Auth unresolved'
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

function OperatorTokenDialog({
  open,
  value,
  error,
  onValueChange,
  onSubmit,
  onCancel,
}: {
  open: boolean
  value: string
  error: string | null
  onValueChange: (value: string) => void
  onSubmit: () => void
  onCancel: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onCancel() }}>
      <DialogContent className={MODAL_SIZES.SM}>
        <DialogHeader>
          <DialogTitle>Operator token</DialogTitle>
          <DialogDescription>
            Enter the token configured as OPERATOR_TOKEN in backend/.env. It stays in this browser tab only.
          </DialogDescription>
        </DialogHeader>
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        <SecretField
          id="autonomy-operator-token"
          label="Operator token"
          value={value}
          onChange={onValueChange}
          required
        />
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>Cancel</Button>
          <Button onClick={onSubmit} disabled={!value.trim()}>Use token</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
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
  const [numberInputs, setNumberInputs] = useState<Record<ScopeNumberKey, string>>({
    max_approval_rounds: '3',
    max_concurrent_dispatched: '3',
    max_verification_retries: '2',
    max_auto_merges_per_day: '5',
    max_build_parallelism: '4',
  })
  const [saving, setSaving] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const open = state !== null

  useEffect(() => {
    if (!state) return
    queueMicrotask(() => {
      const initial = state.scope ? scopeToInput(state.scope) : emptyScope
      setForm(initial)
      setNumberInputs(Object.fromEntries(scopeNumberKeys.map((key) => [key, String(initial[key])])) as Record<ScopeNumberKey, string>)
      setErrorMessage(null)
    })
  }, [state])

  const update = (patch: Partial<TeamGithubScopeInput>) => {
    setForm((current) => ({ ...current, ...patch }))
  }

  const submit = async () => {
    setSaving(true)
    setErrorMessage(null)
    try {
      await onSave({
        ...form,
        max_approval_rounds: parsedLimit(numberInputs.max_approval_rounds, 'max approval rounds', 1),
        max_concurrent_dispatched: parsedLimit(numberInputs.max_concurrent_dispatched, 'max concurrent dispatched', 1),
        max_verification_retries: parsedLimit(numberInputs.max_verification_retries, 'max verification retries', 0),
        max_auto_merges_per_day: parsedLimit(numberInputs.max_auto_merges_per_day, 'max auto-merges per day', 0),
        max_build_parallelism: parsedLimit(numberInputs.max_build_parallelism, 'max build parallelism', 1),
        repo_owner: form.repo_owner.trim(),
        repo_name: form.repo_name.trim(),
        repo_path: form.repo_path.trim(),
        base_ref: form.base_ref?.trim() || 'origin/HEAD',
        build_dir_template: form.build_dir_template?.trim() || 'build',
        build_command_hint: form.build_command_hint?.trim() || null,
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
            <Label htmlFor="scope-path">Primary checkout path</Label>
            <Input
              id="scope-path"
              value={form.repo_path}
              onChange={(event) => update({ repo_path: event.target.value })}
              placeholder="/home/user/repos/project"
            />
            <p className="text-xs text-muted-foreground">
              Existing checkout used to create dispatch worktrees beside it. This does not change slot settings.
            </p>
          </div>
          <div className="grid gap-2 md:col-span-2">
            <Label htmlFor="scope-base-ref">Base ref</Label>
            <Input
              id="scope-base-ref"
              value={form.base_ref ?? ''}
              onChange={(event) => update({ base_ref: event.target.value })}
              placeholder="origin/main"
            />
            <p className="text-xs text-muted-foreground">
              Git ref used as the dispatch base. Changing it while a workspace is active is blocked.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="dispatch-label">Dispatch label</Label>
            <Input
              id="dispatch-label"
              value={form.dispatch_label}
              onChange={(event) => update({ dispatch_label: event.target.value })}
            />
            <p className="text-xs text-muted-foreground">Issues need this GitHub label to enter the dispatch queue.</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="design-label">Design label</Label>
            <Input
              id="design-label"
              value={form.design_label}
              onChange={(event) => update({ design_label: event.target.value })}
            />
            <p className="text-xs text-muted-foreground">Issues with this label use the design-review pipeline.</p>
          </div>
          <div className="grid gap-2 md:col-span-2">
            <Label htmlFor="scope-merge-policy">Merge policy</Label>
            <Select
              value={form.merge_policy}
              onValueChange={(mergePolicy) => update({ merge_policy: mergePolicy as TeamGithubMergePolicy })}
            >
              <SelectTrigger id="scope-merge-policy">
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
              value={numberInputs.max_approval_rounds}
              onChange={(event) => setNumberInputs((current) => ({ ...current, max_approval_rounds: event.target.value }))}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="concurrent-dispatches">Max concurrent dispatched</Label>
            <Input
              id="concurrent-dispatches"
              type="number"
              min={1}
              value={numberInputs.max_concurrent_dispatched}
              onChange={(event) => setNumberInputs((current) => ({ ...current, max_concurrent_dispatched: event.target.value }))}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="verification-retries">Max verification retries</Label>
            <Input
              id="verification-retries"
              type="number"
              min={0}
              value={numberInputs.max_verification_retries}
              onChange={(event) => setNumberInputs((current) => ({ ...current, max_verification_retries: event.target.value }))}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="auto-merges">Max auto-merges per day</Label>
            <Input
              id="auto-merges"
              type="number"
              min={0}
              value={numberInputs.max_auto_merges_per_day}
              disabled={form.merge_policy !== 'auto'}
              onChange={(event) => setNumberInputs((current) => ({ ...current, max_auto_merges_per_day: event.target.value }))}
            />
          </div>
          <label className="flex items-center gap-2 text-sm md:col-span-2">
            <Checkbox checked={form.builds_out_of_tree ?? false} onCheckedChange={(checked) => update({ builds_out_of_tree: checked === true })} />
            Builds out of tree
          </label>
          <div className="grid gap-2">
            <Label htmlFor="scope-build-dir">Build directory template</Label>
            <Input
              id="scope-build-dir"
              value={form.build_dir_template ?? ''}
              onChange={(event) => update({ build_dir_template: event.target.value })}
              placeholder="build"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="scope-build-parallelism">Max build parallelism</Label>
            <Input
              id="scope-build-parallelism"
              type="number"
              min={1}
              value={numberInputs.max_build_parallelism}
              onChange={(event) => setNumberInputs((current) => ({ ...current, max_build_parallelism: event.target.value }))}
            />
          </div>
          <div className="grid gap-2 md:col-span-2">
            <Label htmlFor="scope-build-hint">Build command hint</Label>
            <Input
              id="scope-build-hint"
              value={form.build_command_hint ?? ''}
              onChange={(event) => update({ build_command_hint: event.target.value })}
              placeholder="meson test -C build"
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
    input: TeamGithubContinuationPolicyUpdate
  ) => Promise<void>
}) {
  const scope = state?.scope ?? null
  const [form, setForm] = useState<TeamGithubContinuationPolicyUpdate | null>(null)
  const [numberInputs, setNumberInputs] = useState<Record<PolicyNumberKey, string> | null>(null)
  const [saving, setSaving] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [confirmLiveEnable, setConfirmLiveEnable] = useState(false)

  useEffect(() => {
    if (!scope) return
    queueMicrotask(() => {
      const initial = {
        continuation_enabled: scope.continuation_enabled,
        max_continuation_revisions: scope.max_continuation_revisions,
        max_continuation_failed_heads: scope.max_continuation_failed_heads,
        max_failed_heads_per_revision: scope.max_failed_heads_per_revision,
        max_scope_paths: scope.max_scope_paths,
        max_scope_commands: scope.max_scope_commands,
      }
      setForm(initial)
      setNumberInputs(Object.fromEntries(policyNumberKeys.map((key) => [key, String(initial[key])])) as Record<PolicyNumberKey, string>)
      setErrorMessage(null)
      setConfirmLiveEnable(false)
    })
  }, [scope])

  const submit = async () => {
    if (!scope || !form || !numberInputs) return
    if (form.continuation_enabled && !scope.continuation_enabled && autonomyEnabled && !confirmLiveEnable) {
      setErrorMessage('Confirm the live recovery effect before saving this policy.')
      return
    }
    setSaving(true)
    setErrorMessage(null)
    try {
      const limits = Object.fromEntries(policyNumberKeys.map((key) => [
        key, parsedLimit(numberInputs[key], key.replaceAll('_', ' '), 1),
      ])) as Record<PolicyNumberKey, number>
      if (limits.max_failed_heads_per_revision > limits.max_continuation_failed_heads) {
        throw new Error('Per-revision failed heads cannot exceed the attempt-wide failed-head cap.')
      }
      await onSave(scope.id, { ...form, ...limits })
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
        {form && numberInputs && (
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
                  value={numberInputs[key]}
                  onChange={(event) => setNumberInputs((current) => current ? { ...current, [key]: event.target.value } : current)}
                />
              </div>
            ))}
            <p className="text-xs text-muted-foreground md:col-span-2">
              Recovery runs only when both this policy and team autonomy are enabled. Finite caps stop repeated recovery honestly.
            </p>
            {form.continuation_enabled && !scope?.continuation_enabled && autonomyEnabled && (
              <label className="flex items-start gap-2 text-sm text-amber-600 dark:text-amber-400 md:col-span-2">
                <Checkbox checked={confirmLiveEnable} onCheckedChange={(checked) => setConfirmLiveEnable(checked === true)} />
                Autonomy is already on. I understand that eligible escalated attempts may recover immediately.
              </label>
            )}
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
  onFetchWorkspaces,
  operatorTokenStored,
  onRequestOperatorToken,
  slots,
  onOperate,
}: {
  item: GithubWorkItem | null
  ownerName?: string
  handoffTargetName?: string
  onOpenChange: (open: boolean) => void
  onRetry: (item: GithubWorkItem) => void
  onFetchScopeRevisions: (itemId: number) => Promise<GithubScopeRevision[]>
  onFetchWorkspaces: (scopeId: number) => Promise<{ workspaces: GithubWorkspace[] }>
  operatorTokenStored: boolean
  onRequestOperatorToken: () => Promise<string | null>
  slots: AgentTeamSlot[]
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
  const open = item !== null

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
          setRevisionError('Enter an operator token to load recovery history.')
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
      const result = await onOperate(item, operatorAction, actionReason.trim(), reassignToSlotId === 'current' ? undefined : Number(reassignToSlotId))
      setActionResult(result ?? 'Operator action completed.')
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
              <div className="rounded-lg border">
                <dl className="grid gap-0 text-sm">
                  <div className="grid grid-cols-[150px_1fr] border-b p-3">
                    <dt className="text-muted-foreground">Status</dt>
                    <dd>{readableCode(item.dispatch_status)}</dd>
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
                    <dd>{phaseLabel(item.attempt_phase)} · revision {item.active_scope_revision}</dd>
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
                        <Badge variant="secondary">{phaseLabel(revision.phase)}</Badge>
                        <span className="text-sm font-medium">{readableCode(revision.status)}</span>
                        <span className="text-xs text-muted-foreground">
                          failed heads {revision.failed_head_count}/{revision.max_failed_heads}
                        </span>
                      </div>
                      <p className="whitespace-pre-wrap text-sm">{revision.summary}</p>
                      <dl className="grid gap-2 text-sm md:grid-cols-2">
                        <div><dt className="text-muted-foreground">Origin</dt><dd>{escalationReasonLabel(revision.originating_escalation_reason)}</dd></div>
                        <div><dt className="text-muted-foreground">Execution</dt><dd>{readableCode(revision.execution_target)}</dd></div>
                        <div><dt className="text-muted-foreground">Owner</dt><dd>{slots.find((slot) => slot.id === revision.owner_slot_id)?.display_name ?? `slot #${revision.owner_slot_id}`} · member #{revision.owner_member_id}</dd></div>
                        <div><dt className="text-muted-foreground">Workspace</dt><dd>#{revision.expected_workspace_id}</dd></div>
                        {approval && (
                          <>
                            <div><dt className="text-muted-foreground">Approval</dt><dd>request #{approval.id} · {approvalStatusLabel(approval.status)}</dd></div>
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
                        <Button variant="outline" size="sm" disabled={!decisionReleaseEligible} title={!decisionReleaseEligible ? 'This decision hold is no longer releasable.' : undefined} onClick={() => setOperatorAction({ kind: 'release_decision', revision })}>
                          Release decision hold
                        </Button>
                      )}
                      {revision.recovery_checkpoint_stage === 'ack_hold' && (
                        <Button variant="outline" size="sm" disabled={!acknowledgementReleaseEligible} title={!acknowledgementReleaseEligible ? 'This acknowledgement hold is no longer releasable.' : undefined} onClick={() => setOperatorAction({ kind: 'release_ack', revision })}>
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
                  <p className="text-sm text-muted-foreground">Actions are confirmed against the current server state before changing this attempt.</p>
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
                    <Button variant="destructive" size="sm" disabled={workspaceLoading} onClick={() => void inspectWorkspace()}>
                      {workspaceLoading ? 'Checking lease…' : 'Force-release workspace…'}
                    </Button>
                  )}
                </div>
              </section>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
              {item.retry_allowed && (
                <Button onClick={() => onRetry(item)}>
                  <RotateCcw className="mr-2 h-4 w-4" />
                  Retry
                </Button>
              )}
            </DialogFooter>
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
                      ? `This may discard dirty or unpushed work in ${operatorAction.workspace.path}. Lease acquired at ${operatorAction.workspace.leased_at}. Verify the owner is finished before continuing.`
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
  lastRefreshedAt,
  loadError,
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
  lastRefreshedAt: Date | null
  loadError: string | null
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
  onFetchScopeRevisions: (itemId: number, operatorToken: string) => Promise<GithubScopeRevision[]>
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
  const [retryTarget, setRetryTarget] = useState<GithubWorkItem | null>(null)
  const [enableConfirmOpen, setEnableConfirmOpen] = useState(false)
  const [enableWarnings, setEnableWarnings] = useState<string[]>([])
  const [gateOpen, setGateOpen] = useState(false)
  const [gateLoading, setGateLoading] = useState(false)
  const [gate, setGate] = useState<GithubRecoveryGate | null>(null)
  const [gateError, setGateError] = useState<string | null>(null)
  const [repoFilter, setRepoFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [operatorTokenStored, setOperatorTokenStored] = useState(() => Boolean(getOperatorToken()))
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [tokenError, setTokenError] = useState<string | null>(null)
  const tokenResolverRef = useRef<((token: string | null) => void) | null>(null)
  const tokenPromiseRef = useRef<Promise<string | null> | null>(null)
  const slotById = useMemo(
    () => new Map(preset.slots.map((slot) => [slot.id, slot])),
    [preset.slots]
  )
  const scopeCount = scopes.length
  const repoOptions = useMemo(
    () => [...new Set(workItems.map((item) => `${item.repo_owner}/${item.repo_name}`))].sort(),
    [workItems]
  )
  const visibleItems = useMemo(() => workItems.filter((item) => {
    if (repoFilter !== 'all' && `${item.repo_owner}/${item.repo_name}` !== repoFilter) return false
    if (statusFilter === 'attention') return item.dispatch_status === 'escalated' || item.dispatch_status === 'failed'
    if (statusFilter === 'active') return ['pending', 'dispatched', 'verifying'].includes(item.dispatch_status)
    if (statusFilter === 'review') return ['awaiting_human_review', 'ready_for_review'].includes(item.dispatch_status)
    if (statusFilter === 'finished') return ['merged', 'completed'].includes(item.dispatch_status)
    return true
  }), [repoFilter, statusFilter, workItems])
  const detailItem = useMemo(
    () => workItems.find((item) => item.id === detailItemId) ?? null,
    [detailItemId, workItems]
  )

  const requestToken = useCallback((message: string | null = null): Promise<string | null> => {
    const stored = getOperatorToken()
    if (stored) return Promise.resolve(stored)
    if (tokenPromiseRef.current) return tokenPromiseRef.current
    const pending = new Promise<string | null>((resolve) => {
      tokenResolverRef.current = resolve
    })
    tokenPromiseRef.current = pending
    setTokenError(message)
    setTokenDialogOpen(true)
    return pending
  }, [])

  useEffect(() => () => {
    tokenResolverRef.current?.(null)
    tokenResolverRef.current = null
    tokenPromiseRef.current = null
  }, [])

  const settleTokenDialog = (token: string | null) => {
    tokenResolverRef.current?.(token)
    tokenResolverRef.current = null
    tokenPromiseRef.current = null
    setTokenDialogOpen(false)
    setTokenInput('')
    setTokenError(null)
  }

  const submitToken = () => {
    const token = tokenInput.trim()
    if (!token) return
    setOperatorToken(token)
    setOperatorTokenStored(true)
    settleTokenDialog(token)
  }

  const clearStoredToken = () => {
    clearOperatorToken()
    setOperatorTokenStored(false)
  }

  const withOperatorToken = useCallback(async <Result,>(
    action: (token: string) => Promise<Result>
  ): Promise<Result> => {
    for (let attempt = 0; attempt < 2; attempt++) {
      const token = await requestToken(attempt > 0 ? 'The operator token was rejected. Enter a valid token to retry.' : null)
      if (!token) throw new Error('Operator token is required for this action.')
      try {
        return await action(token)
      } catch (error) {
        if (!(error instanceof ApiHttpError) || error.status !== 401) throw error
        clearOperatorToken()
        setOperatorTokenStored(false)
        if (attempt === 1) throw error
      }
    }
    throw new Error('Operator token was rejected.')
  }, [requestToken])

  const fetchRevisions = useCallback(
    (itemId: number) => withOperatorToken((token) => onFetchScopeRevisions(itemId, token)),
    [onFetchScopeRevisions, withOperatorToken]
  )

  const inspectGate = async () => {
    setGateOpen(false)
    setGateLoading(true)
    setGate(null)
    setGateError(null)
    let cancelled = false
    try {
      setGate(await withOperatorToken(fetchGithubRecoveryGate))
    } catch (error) {
      if (error instanceof Error && error.message === 'Operator token is required for this action.') {
        cancelled = true
      } else {
        setGateError(error instanceof Error ? error.message : 'Failed to read recovery gate')
      }
    } finally {
      setGateLoading(false)
      if (!cancelled) setGateOpen(true)
    }
  }

  const operateItem = async (
    item: GithubWorkItem,
    action: ItemOperatorAction,
    reason: string,
    reassignToSlotId?: number
  ) => {
    let resultMessage: string | undefined
    await withOperatorToken(async (token) => {
      if (action.kind === 'abandon') return abandonGithubWorkItem(item.id, reason, token)
      if (action.kind === 'resume') return resumeGithubWorkItem(preset.id, item.id, token, reassignToSlotId)
      if (action.kind === 'force_release') {
        const released = await forceReleaseGithubWorkspace(item.scope_id, action.workspace, reason, token)
        const discardedCount = released.discarded_paths?.split('\n').filter(Boolean).length
        resultMessage = `Released workspace from item #${released.released_item_id}. Local paths flagged: ${discardedCount ?? 'unknown'}; unpushed commits: ${released.unpushed_commits ?? 'unknown'}.`
        return
      }
      if (action.kind === 'cancel_request') {
        const approvalId = action.revision.approval_request_id
        if (!approvalId) throw new Error('This revision has no pending approval request.')
        return onCancelContinuationRequest(item, approvalId, token)
      }
      if (action.kind === 'cancel_revision') return cancelGithubActiveRevision(item.id, action.revision, reason, token)
      if (!('revision' in action)) throw new Error('Unsupported operator action.')
      if (!action.revision.approval_request_id) throw new Error('This revision has no approval request to release.')
      return releaseGithubRecoveryCheckpoint(
        item.id, action.revision, action.kind === 'release_decision' ? 'decision' : 'ack', token
      )
    })
    await onRefresh()
    return resultMessage
  }

  const applyToggle = async (enabled: boolean) => {
    setToggleSaving(true)
    try {
      await onToggleAutonomy(enabled)
    } catch {
      // Parent handlers surface the error toast; keep the controlled switch stable.
    } finally {
      setToggleSaving(false)
    }
  }

  const toggle = async (enabled: boolean) => {
    if (!enabled) {
      await applyToggle(false)
      return
    }
    const warnings: string[] = []
    if (!scopes.some((scope) => scope.enabled)) warnings.push('No watched repo is enabled, so no issues can dispatch.')
    if (scopes.some((scope) => scope.enabled && scope.merge_policy === 'auto')) {
      warnings.push('At least one watched repo can auto-merge code PRs after verification.')
    }
    const leader = [...preset.slots].filter((slot) => slot.enabled).sort((first, second) => first.position - second.position)[0]
    if (!leader) {
      warnings.push('No enabled Leader slot exists; dispatched work will not have an approver.')
    } else {
      try {
        const team = await fetchAgentMailTeam(false)
        if (!team.members.some((member) => member.team_slot_id === leader.id && member.status === 'connected')) {
          warnings.push('The Leader is not currently connected in Agent Mail. Work may wait or escalate before approval.')
        }
      } catch {
        warnings.push('Leader availability could not be checked. Confirm it before enabling unattended work.')
      }
    }
    setEnableWarnings(warnings)
    setEnableConfirmOpen(true)
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
      setDetailItemId(null)
    } catch {
      // Parent handlers surface the error toast.
    } finally {
      setRetryingWorkItemId(null)
    }
  }

  return (
    <div className="space-y-5">
      {loadError && <p role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">Refresh failed: {loadError}</p>}
      <Card>
        <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-semibold">Autonomous GitHub dispatch</p>
            <p className="text-sm text-muted-foreground">
              Poll watched repos for labeled issues and dispatch work into this team automatically.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Label htmlFor="autonomy-enabled" className="text-sm text-muted-foreground">
              {preset.autonomy_enabled ? 'Enabled' : 'Disabled'}
            </Label>
            <Switch
              id="autonomy-enabled"
              aria-label="Enable autonomous GitHub dispatch"
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
          <p className="text-sm text-muted-foreground">{scopeCount} watched repo{scopeCount === 1 ? '' : 's'}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={gateLoading} onClick={() => void inspectGate()}>{gateLoading ? 'Checking gate…' : 'Recovery gate'}</Button>
          <Button
            variant="outline"
            onClick={() => { if (operatorTokenStored) clearStoredToken(); else void requestToken() }}
          >
            <KeyRound className="mr-2 h-4 w-4" />
            {operatorTokenStored ? 'Clear operator token' : 'Set operator token'}
          </Button>
          <span className="self-center text-xs text-muted-foreground">
            {operatorTokenStored ? 'Token set for this tab' : 'No token set'}
          </span>
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
            To get started: add a watched repo and its primary checkout, label an issue with the dispatch label, then enable autonomy. Use an operator token for recovery actions.
          </div>
        )}
        {scopes.map((scope) => (
          <Card key={scope.id} className={cn(!scope.enabled && 'opacity-70')}>
            <CardContent className="p-4">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold">{scope.repo_owner}/{scope.repo_name}</p>
                    <Badge variant="outline">Dispatch: {scope.dispatch_label}</Badge>
                    <Badge variant="secondary">Design: {scope.design_label}</Badge>
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
                    <Badge variant="outline" className={scope.github_auth_mode === 'unknown' ? 'border-amber-500 text-amber-700 dark:text-amber-400' : undefined}>
                      {authModeLabel(scope.github_auth_mode)}
                    </Badge>
                  </div>
                  <p className="mt-2 truncate text-sm text-muted-foreground">
                    Primary checkout: {scope.repo_path}
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
                    <Settings2 className="mr-2 h-4 w-4" />
                    Recovery policy
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setScopeDialog({ mode: 'edit', scope })}>
                    <Pencil className="mr-2 h-4 w-4" />
                    Edit
                  </Button>
                  <Button variant="destructive" size="sm" onClick={() => void deleteScope(scope)}>
                    <Trash2 className="mr-2 h-4 w-4" />
                    Remove
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="min-w-0">
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>Activity</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">Recent GitHub work items across this preset&apos;s scopes.</p>
          </div>
          <span className="text-xs text-muted-foreground sm:shrink-0">
            {lastRefreshedAt ? `Updated ${lastRefreshedAt.toLocaleTimeString()}` : 'Not refreshed yet'} · every 5s while open
          </span>
        </CardHeader>
        <CardContent className="min-w-0">
          <div className="mb-3 flex flex-wrap gap-3">
            <div className="min-w-40 space-y-1">
              <Label htmlFor="activity-repo-filter">Repo</Label>
              <Select value={repoFilter} onValueChange={setRepoFilter}>
                <SelectTrigger id="activity-repo-filter"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All repos</SelectItem>
                  {repoOptions.map((repo) => <SelectItem key={repo} value={repo}>{repo}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="min-w-40 space-y-1">
              <Label htmlFor="activity-status-filter">Status</Label>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger id="activity-status-filter"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="attention">Needs attention</SelectItem>
                  <SelectItem value="active">In progress</SelectItem>
                  <SelectItem value="review">Needs review</SelectItem>
                  <SelectItem value="finished">Finished</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {workItems.length === 0 ? (
            <div className="rounded-lg border p-5 text-sm text-muted-foreground">
              No GitHub work items yet.
            </div>
          ) : visibleItems.length === 0 ? (
            <div className="rounded-lg border p-5 text-sm text-muted-foreground">
              No work items match these filters.
            </div>
          ) : (
            <div className="max-w-full overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Issue</th>
                    <th className="px-3 py-2 font-medium">Type</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Owner</th>
                    <th className="px-3 py-2 font-medium">PR</th>
                    <th className="px-3 py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleItems.map((item) => {
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
                            <Badge variant="outline">{phaseLabel(item.attempt_phase)}</Badge>
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
                              Handoff: {item.handoff_state.replaceAll('_', ' ')}
                              {handoffTarget ? ` → ${handoffTarget.display_name}` : ''}
                            </p>
                          )}
                          {item.escalation_reason && (
                            <p className="mt-1 text-xs text-destructive">{escalationReasonLabel(item.escalation_reason)}</p>
                          )}
                          {item.status_note && (
                            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground" title={item.status_note}>
                              {item.status_note}
                            </p>
                          )}
                          {item.pending_approval_request_id && (
                            <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                              approval #{item.pending_approval_request_id} · {approvalStatusLabel(item.pending_approval_status)}
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
                          {(item.retry_count > 0 || item.diagnostic_retry_count > 0) && (
                            <p className="mt-1 whitespace-nowrap text-xs text-muted-foreground" title={`Product retries: ${item.retry_count}; diagnostic failed heads: ${item.diagnostic_retry_count}`}>
                              Retries {item.retry_count} · diagnostics {item.diagnostic_retry_count}
                            </p>
                          )}
                        </td>
                        <td className="px-3 py-3 text-right">
                          <div className="flex justify-end gap-2">
                            {item.retry_allowed && (
                              <Button
                                size="sm"
                                disabled={retryingWorkItemId !== null}
                                onClick={() => setRetryTarget(item)}
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
                              <Eye className="mr-2 h-4 w-4" />
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
        onSave={(scopeId, input) => withOperatorToken((token) => onUpdateContinuationPolicy(scopeId, input, token))}
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
        onRetry={setRetryTarget}
        onFetchScopeRevisions={fetchRevisions}
        onFetchWorkspaces={(scopeId) => withOperatorToken((token) => fetchGithubWorkspaces(scopeId, token))}
        operatorTokenStored={operatorTokenStored}
        onRequestOperatorToken={() => requestToken()}
        slots={preset.slots}
        onOperate={operateItem}
      />
      <OperatorTokenDialog
        open={tokenDialogOpen}
        value={tokenInput}
        error={tokenError}
        onValueChange={setTokenInput}
        onSubmit={submitToken}
        onCancel={() => settleTokenDialog(null)}
      />
      <AlertDialog open={retryTarget !== null} onOpenChange={(open) => { if (!open) setRetryTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Retry issue #{retryTarget?.issue_number}?</AlertDialogTitle>
            <AlertDialogDescription>
              Retry can discard prior PR, handoff, and attempt markers. If the workspace is still leased,
              Deck defers re-dispatch until the current owner releases it. Review the work item before continuing.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => { if (retryTarget) void retryWorkItem(retryTarget) }}>
              Retry issue
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={enableConfirmOpen} onOpenChange={setEnableConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Enable autonomous dispatch?</AlertDialogTitle>
            <AlertDialogDescription>
              Deck will resume scheduled autonomy. A configured recovery-only gate limits work to its selected attempt; otherwise enabled watched repos may poll and dispatch labeled issues.
              Review these conditions before continuing.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {enableWarnings.length > 0 ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-amber-600 dark:text-amber-400">
              {enableWarnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No configuration warnings found. Continue only if this rollout is authorized.</p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void applyToggle(true)}>Enable autonomy</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Dialog open={gateOpen} onOpenChange={setGateOpen}>
        <DialogContent className={MODAL_SIZES.SM}>
          <DialogHeader>
            <DialogTitle>Recovery-only gate</DialogTitle>
            <DialogDescription>Read-only scheduler scope for a bounded recovery attempt.</DialogDescription>
          </DialogHeader>
          {gateLoading && <p className="text-sm text-muted-foreground">Checking gate…</p>}
          {gateError && <p className="text-sm text-destructive" role="alert">{gateError}</p>}
          {!gateLoading && !gateError && gate && (
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <dt>Gate</dt><dd>{gate.active ? 'active' : 'off'}</dd>
              {gate.active && <>
                <dt>Work item</dt><dd>#{gate.work_item_id}</dd>
                <dt>Identity</dt><dd>{gate.identity_matches ? 'matches' : 'mismatch'}</dd>
                <dt>Scheduler</dt><dd>{gate.scheduler_running ? 'running' : 'stopped'}</dd>
                <dt>Job</dt><dd>{gate.job_scheduled ? 'scheduled' : 'not scheduled'}</dd>
              </>}
            </dl>
          )}
          <DialogFooter><Button variant="outline" onClick={() => setGateOpen(false)}>Close</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
