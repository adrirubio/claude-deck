import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { KeyRound, Pencil, Plus, RefreshCw, Settings2, Trash2 } from 'lucide-react'
import { formatServerTime } from '@/lib/serverTime'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
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
import { fetchAgentMailTeam } from '@/features/agent-mail/api'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { MODAL_SIZES } from '@/lib/constants'
import { cn } from '@/lib/utils'
import type {
  AgentTeamPreset,
  GithubRecoveryGate,
  GithubWorkItem,
  TeamGithubContinuationPolicyUpdate,
  TeamGithubMergePolicy,
  TeamGithubScope,
  TeamGithubScopeInput,
  TeamGithubScopeUpdate,
} from '@/types/agentTeams'
import { BacklogCoordination } from './BacklogCoordination'
import { workItemAttention } from './workItemAttention'
import { useOperatorTokenFlow } from './useOperatorTokenFlow'
import { fetchGithubRecoveryGate, fetchGithubRecoveryGateActive } from './api'

type ScopeDialogState = { mode: 'add' | 'edit'; scope?: TeamGithubScope } | null
type PolicyDialogState = { scope: TeamGithubScope } | null
type ScopeNumberKey = 'max_approval_rounds' | 'max_concurrent_dispatched' | 'max_verification_retries' | 'max_auto_merges_per_day' | 'max_build_parallelism'
type PolicyNumberKey = Exclude<keyof TeamGithubContinuationPolicyUpdate, 'continuation_enabled'>

const scopeNumberKeys: ScopeNumberKey[] = [
  'max_approval_rounds', 'max_concurrent_dispatched', 'max_verification_retries', 'max_auto_merges_per_day', 'max_build_parallelism',
]
const policyNumberKeys: PolicyNumberKey[] = [
  'max_continuation_revisions', 'max_continuation_failed_heads', 'max_failed_heads_per_revision',
  'max_scope_paths', 'max_scope_commands',
]

function parsedLimit(value: string, label: string, minimum: number, maximum?: number): number {
  const text = value.trim()
  const parsed = Number(text)
  const [mantissa, exponent = '0'] = text.toLowerCase().split('e')
  const fractionalPlaces = (mantissa.split('.')[1]?.length ?? 0) - Number(exponent)
  const digits = mantissa.replace(/[+.-]/g, '')
  // Check the decimal string too: Number can round fractions or underflow to zero.
  const hasFraction = fractionalPlaces > 0 && /[1-9]/.test(digits.slice(-fractionalPlaces))
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(text) || !Number.isInteger(parsed) || hasFraction) {
    throw new Error(`Enter a whole number for ${label}.`)
  }
  if (!Number.isSafeInteger(parsed)) throw new Error(`Enter a safely representable whole number for ${label}.`)
  return Math.max(minimum, maximum === undefined ? parsed : Math.min(parsed, maximum))
}

// Changes retain the editing string; only blur or an explicit save normalizes it.
function LimitInput({ id, label, value, minimum, maximum, disabled, onChange }: {
  id: string
  label: string
  value: string
  minimum: number
  maximum?: number
  disabled?: boolean
  onChange: (value: string) => void
}) {
  const [error, setError] = useState<string | null>(null)
  return <>
    <Input
      id={id}
      type="number"
      step={1}
      min={minimum}
      max={maximum}
      disabled={disabled}
      value={value}
      aria-invalid={Boolean(error)}
      aria-describedby={error ? `${id}-error` : undefined}
      onChange={(event) => {
        setError(null)
        onChange(event.target.value)
      }}
      onBlur={(event) => {
        try {
          const normalized = parsedLimit(event.target.value, label, minimum, maximum)
          setError(null)
          onChange(String(normalized))
        } catch (failure) {
          setError(failure instanceof Error ? failure.message : 'Enter a whole number.')
        }
      }}
    />
    {error && <p id={`${id}-error`} role="alert" className="text-sm text-destructive">{error}</p>}
  </>
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
  return formatServerTime(value)
}

function authStatus(scope: TeamGithubScope) {
  if (!scope.github_poll_token_configured) return {
    label: 'Polling token not set',
    help: 'Set github_token in backend/.env and restart Deck. The watcher uses this host token to poll GitHub; private repos cannot be polled through App settings alone.',
    warning: true,
  }
  if (!scope.github_auth_configured) return {
    label: 'GitHub App setup incomplete',
    help: 'Complete the GitHub App settings in backend/.env or remove partial App settings, then restart Deck. Deck selects a dispatch auth mode when eligible work is dispatched.',
    warning: true,
  }
  if (scope.github_auth_mode === 'unknown') return {
    label: 'Dispatch auth: not selected',
    help: 'The watcher can poll with the host token, but Deck selects a dispatch authentication mode only when eligible work is dispatched. A successful poll alone does not select the mode.',
    warning: false,
  }
  return {
    label: scope.github_auth_mode === 'app' ? 'Auth mode: GitHub App' : 'Auth mode: host token',
    help: scope.last_polled_at ? 'Deck has polled this repo. Check Activity for any later GitHub errors.' : 'Authentication mode selected; Deck has not completed a poll yet.',
    warning: false,
  }
}

export { OperatorTokenDialog } from './OperatorTokenDialog'

function ScopeDialog({
  state,
  onOpenChange,
  onSave,
  onReturnFocus,
}: {
  state: ScopeDialogState
  onOpenChange: (state: ScopeDialogState) => void
  onSave: (scope: TeamGithubScopeInput | TeamGithubScopeUpdate) => Promise<void>
  onReturnFocus: () => void
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
      const input: TeamGithubScopeInput = {
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
      }
      setNumberInputs(Object.fromEntries(scopeNumberKeys.map((key) => [key, String(input[key])])) as Record<ScopeNumberKey, string>)
      if (state?.mode === 'edit' && state.scope) {
        const original = scopeToInput(state.scope)
        const changes = Object.fromEntries(
          Object.entries(input).filter(([key, value]) => value !== original[key as keyof TeamGithubScopeInput])
        ) as TeamGithubScopeUpdate
        if (Object.keys(changes).length > 0) await onSave(changes)
      } else {
        await onSave(input)
      }
      onOpenChange(null)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to save watched repo')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => onOpenChange(next ? state : null)}>
      <DialogContent className={MODAL_SIZES.SM} onCloseAutoFocus={(event) => { event.preventDefault(); onReturnFocus() }}>
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
            <p className="text-xs text-muted-foreground">GitHub owner, as in github.com/owner/name.</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="scope-name">Repo name</Label>
            <Input
              id="scope-name"
              value={form.repo_name}
              onChange={(event) => update({ repo_name: event.target.value })}
            />
            <p className="text-xs text-muted-foreground">GitHub repo name, as in github.com/owner/name.</p>
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
              Existing clone under your home directory. Deck creates one worktree per issue next to it, in the same parent folder, and launches the owner there. Normal slot sessions keep their own repo path.
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
              New worktrees start from this Git ref. origin/HEAD means the remote default branch. Changing it while a workspace is active is blocked.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="dispatch-label">Dispatch label</Label>
            <Input
              id="dispatch-label"
              value={form.dispatch_label}
              onChange={(event) => update({ dispatch_label: event.target.value })}
            />
            <p className="text-xs text-muted-foreground">Create this label on GitHub, then add it to an issue to queue it. Removing it during work escalates the attempt.</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="design-label">Design label</Label>
            <Input
              id="design-label"
              value={form.design_label}
              onChange={(event) => update({ design_label: event.target.value })}
            />
            <p className="text-xs text-muted-foreground">Add this alongside the dispatch label for design or documentation work. The Leader acknowledges the plan, and the PR always needs human review.</p>
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
            <p className="text-xs text-amber-700 dark:text-amber-400">
              Applies to the code pipeline only. Design-pipeline PRs always require a human review.
            </p>
            <p className="text-xs text-muted-foreground">Human: Deck marks the PR ready for review. Auto: merges after GitHub checks pass, within the rolling daily cap; otherwise it waits for a human.</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="approval-rounds">Max approval rounds</Label>
            <LimitInput
              id="approval-rounds"
              label="Max approval rounds"
              minimum={1}
              value={numberInputs.max_approval_rounds}
              onChange={(value) => setNumberInputs((current) => ({ ...current, max_approval_rounds: value }))}
            />
            <p className="text-xs text-muted-foreground">Times the Leader may send an owner&apos;s plan back before escalation.</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="concurrent-dispatches">Max concurrent dispatched</Label>
            <LimitInput
              id="concurrent-dispatches"
              label="Max concurrent dispatched"
              minimum={1}
              value={numberInputs.max_concurrent_dispatched}
              onChange={(value) => setNumberInputs((current) => ({ ...current, max_concurrent_dispatched: value }))}
            />
            <p className="text-xs text-muted-foreground">Issues from this repo worked on at once; extra issues wait.</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="verification-retries">Max verification retries</Label>
            <LimitInput
              id="verification-retries"
              label="Max verification retries"
              minimum={0}
              value={numberInputs.max_verification_retries}
              onChange={(value) => setNumberInputs((current) => ({ ...current, max_verification_retries: value }))}
            />
            <p className="text-xs text-muted-foreground">Distinct failing PR heads allowed before escalation.</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="auto-merges">Max auto-merges per day</Label>
            <LimitInput
              id="auto-merges"
              label="Max auto-merges per day"
              minimum={0}
              value={numberInputs.max_auto_merges_per_day}
              disabled={form.merge_policy !== 'auto'}
              onChange={(value) => setNumberInputs((current) => ({ ...current, max_auto_merges_per_day: value }))}
            />
            <p className="text-xs text-muted-foreground">Rolling 24-hour cap. Beyond it, PRs wait for human review.</p>
          </div>
          <div className="md:col-span-2">
            <h3 className="text-sm font-medium">Build instructions for the agent (optional)</h3>
            <p className="text-xs text-muted-foreground">Deck does not run a build. These settings become hints in the owner&apos;s brief.</p>
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
            <p className="text-xs text-muted-foreground">For out-of-tree builds; may include {'{issue_number}'}.</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="scope-build-parallelism">Max build parallelism</Label>
            <LimitInput
              id="scope-build-parallelism"
              label="Max build parallelism"
              minimum={1}
              value={numberInputs.max_build_parallelism}
              onChange={(value) => setNumberInputs((current) => ({ ...current, max_build_parallelism: value }))}
            />
            <p className="text-xs text-muted-foreground">Tells the agent to cap parallel build jobs at this value.</p>
          </div>
          <div className="grid gap-2 md:col-span-2">
            <Label htmlFor="scope-build-hint">Build command hint</Label>
            <Input
              id="scope-build-hint"
              value={form.build_command_hint ?? ''}
              onChange={(event) => update({ build_command_hint: event.target.value })}
              placeholder="meson test -C build"
            />
            <p className="text-xs text-muted-foreground">Sent to the agent, not executed by Deck. May use {'{build_dir}'} and {'{parallelism}'}.</p>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={form.enabled} onCheckedChange={(checked) => update({ enabled: checked === true })} />
            Enabled
          </label>
          <p className="text-xs text-muted-foreground md:col-span-2">Disable to pause this repo without deleting it. The team&apos;s Autonomy switch must also be on.</p>
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
      limits.max_failed_heads_per_revision = Math.min(limits.max_failed_heads_per_revision, limits.max_continuation_failed_heads)
      setNumberInputs(Object.fromEntries(policyNumberKeys.map((key) => [key, String(limits[key])])) as Record<PolicyNumberKey, string>)
      await onSave(scope.id, { ...form, ...limits })
      onOpenChange(null)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to save recovery policy')
    } finally {
      setSaving(false)
    }
  }

  let perRevisionMaximum: number | undefined
  if (numberInputs) {
    try {
      perRevisionMaximum = parsedLimit(numberInputs.max_continuation_failed_heads, 'Attempt failed-head cap', 1)
    } catch {
      // An invalid attempt cap cannot supply a bound for another editing field.
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
        <p className="text-sm text-muted-foreground">If an issue escalates with its PR still open, the owner can propose a scope revision: a plan with allowed files and commands. The Leader approves it, then the owner continues in the same workspace. A failed head is a pushed PR commit whose checks fail. These caps bound recovery. Saving requires the Director key.</p>
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
              ['max_continuation_revisions', 'Attempt revision cap', 'Scope revisions allowed across one attempt.'],
              ['max_continuation_failed_heads', 'Attempt failed-head cap', 'Failed PR heads allowed across the whole attempt.'],
              ['max_failed_heads_per_revision', 'Per-revision failed-head cap', 'Failed PR heads allowed within one revision.'],
              ['max_scope_paths', 'Paths per revision', 'Files an owner may list in a scope revision.'],
              ['max_scope_commands', 'Commands per revision', 'Commands an owner may list in a scope revision.'],
            ] as const).map(([key, label, help]) => (
              <div className="grid gap-2" key={key}>
                <Label htmlFor={`policy-${key}`}>{label}</Label>
                <LimitInput
                  id={`policy-${key}`}
                  label={label}
                  minimum={1}
                  maximum={key === 'max_failed_heads_per_revision' ? perRevisionMaximum : undefined}
                  value={numberInputs[key]}
                  onChange={(value) => setNumberInputs((current) => current ? { ...current, [key]: value } : current)}
                />
                <p className="text-xs text-muted-foreground">{help}</p>
              </div>
            ))}
            <p className="text-xs text-muted-foreground md:col-span-2">
              Recovery runs only when both this policy and team autonomy are enabled. Finite caps stop repeated recovery instead of looping.
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
}: {
  preset: AgentTeamPreset
  scopes: TeamGithubScope[]
  workItems: GithubWorkItem[]
  loading: boolean
  refreshing: boolean
  lastRefreshedAt: Date | null
  loadError: string | null
  onRefresh: () => Promise<void>
  onToggleAutonomy: (enabled: boolean, operatorToken: string) => Promise<void>
  onCreateScope: (input: TeamGithubScopeInput, operatorToken: string) => Promise<void>
  onUpdateScope: (scopeId: number, input: TeamGithubScopeUpdate, operatorToken: string) => Promise<void>
  onUpdateContinuationPolicy: (
    scopeId: number,
    input: TeamGithubContinuationPolicyUpdate,
    operatorToken: string
  ) => Promise<void>
  onDeleteScope: (scope: TeamGithubScope, operatorToken: string) => Promise<void>
}) {
  const [scopeDialog, setScopeDialog] = useState<ScopeDialogState>(null)
  const [scopeToRemove, setScopeToRemove] = useState<TeamGithubScope | null>(null)
  const [scopeRemovalPending, setScopeRemovalPending] = useState(false)
  const removeTriggerRef = useRef<HTMLButtonElement | null>(null)
  const scopeTriggerRef = useRef<HTMLButtonElement | null>(null)
  const enableTriggerRef = useRef<HTMLButtonElement | null>(null)
  const addRepoButtonRef = useRef<HTMLButtonElement | null>(null)
  const [policyDialog, setPolicyDialog] = useState<PolicyDialogState>(null)
  const [toggleSaving, setToggleSaving] = useState(false)
  const [enableConfirmOpen, setEnableConfirmOpen] = useState(false)
  const [enableWarnings, setEnableWarnings] = useState<string[]>([])
  const [gateOpen, setGateOpen] = useState(false)
  const [gateLoading, setGateLoading] = useState(false)
  const [gate, setGate] = useState<GithubRecoveryGate | null>(null)
  const [gateError, setGateError] = useState<string | null>(null)
  const [gateStatus, setGateStatus] = useState<'loading' | 'active' | 'inactive' | 'unknown'>('loading')
  const [enableGateActive, setEnableGateActive] = useState(false)
  const [enableError, setEnableError] = useState<string | null>(null)
  const gateRequestIdRef = useRef(0)

  const checkGateStatus = useCallback(async (): Promise<boolean | null> => {
    const requestId = ++gateRequestIdRef.current
    setGateStatus('loading')
    try {
      const { active } = await fetchGithubRecoveryGateActive()
      if (gateRequestIdRef.current === requestId) setGateStatus(active ? 'active' : 'inactive')
      return active
    } catch {
      if (gateRequestIdRef.current === requestId) setGateStatus('unknown')
      return null
    }
  }, [])

  useEffect(() => {
    void checkGateStatus()
    return () => { gateRequestIdRef.current++ }
  }, [checkGateStatus, preset.id])
  const { operatorTokenStored, requestToken, clearStoredToken, withOperatorToken, tokenDialog } = useOperatorTokenFlow('to change autonomy or recovery settings')
  const scopeCount = scopes.length
  const scopeById = useMemo(() => new Map(scopes.map((scope) => [scope.id, scope])), [scopes])
  const actionCount = useMemo(() => workItems.filter((item) => workItemAttention(item, scopeById.get(item.scope_id))).length, [scopeById, workItems])
  const activeCount = useMemo(
    () => workItems.filter((item) => ['pending', 'dispatched', 'verifying'].includes(item.dispatch_status)).length,
    [workItems]
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
      if (error instanceof Error && error.message === 'The Director key is required for this action.') {
        cancelled = true
      } else {
        setGateError(error instanceof Error ? error.message : 'Failed to read recovery gate')
      }
    } finally {
      setGateLoading(false)
      if (!cancelled) setGateOpen(true)
    }
  }

  const applyToggle = async (enabled: boolean) => {
    setToggleSaving(true)
    try {
      if (enabled) {
        const currentGate = await checkGateStatus()
        if (currentGate === null || currentGate !== enableGateActive) {
          setEnableConfirmOpen(false)
          setEnableError('Recovery-only mode changed or could not be checked. Refresh and review the enable confirmation again.')
          return
        }
      }
      await withOperatorToken((token) => onToggleAutonomy(enabled, token))
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
    setEnableError(null)
    const currentGate = await checkGateStatus()
    if (currentGate === null) {
      setEnableError('Recovery-only mode could not be checked. Refresh before enabling autonomy.')
      return
    }
    setEnableGateActive(currentGate)
    const warnings: string[] = []
    if (!scopes.some((scope) => scope.enabled)) warnings.push('No watched repo is enabled, so no issues can dispatch.')
    if (scopes.some((scope) => scope.enabled && scope.merge_policy === 'auto')) {
      warnings.push('At least one watched repo can auto-merge code PRs after verification.')
    }
    const leader = preset.slots.find((slot) => slot.id === preset.leader_slot_id && slot.enabled)
    if (!leader) {
      warnings.push('No enabled Leader slot exists; dispatched work will not have an approver.')
    } else {
      try {
        const team = await fetchAgentMailTeam(false)
        if (!team.members.some((member) => member.team_slot_id === leader.id && member.status === 'connected')) {
          warnings.push('The Leader is not currently connected in Agent Mail. Launch the assigned Leader slot from Roster before enabling autonomy.')
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
      const scopeId = scopeDialog.scope.id
      await withOperatorToken((token) => onUpdateScope(scopeId, input, token))
    } else {
      await withOperatorToken((token) => onCreateScope(input as TeamGithubScopeInput, token))
    }
  }

  const deleteScope = async (scope: TeamGithubScope) => {
    setScopeRemovalPending(true)
    try {
      await withOperatorToken((token) => onDeleteScope(scope, token))
      setScopeToRemove(null)
    } catch {
      // Parent handlers surface the error toast.
    } finally {
      setScopeRemovalPending(false)
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
              ref={enableTriggerRef}
              id="autonomy-enabled"
              aria-label="Enable autonomous GitHub dispatch"
              checked={preset.autonomy_enabled}
              disabled={toggleSaving}
              onCheckedChange={toggle}
            />
          </div>
        </CardContent>
      </Card>
      {enableError && <p role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{enableError}</p>}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Watched repos</h2>
          <p className="text-sm text-muted-foreground">{scopeCount} watched repo{scopeCount === 1 ? '' : 's'}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {gateStatus === 'active' && <Button variant="outline" disabled={gateLoading} onClick={() => void inspectGate()}>{gateLoading ? 'Checking gate…' : 'Recovery-only mode'}</Button>}
          <Button
            variant="outline"
            onClick={() => { if (operatorTokenStored) clearStoredToken(); else void requestToken() }}
          >
            <KeyRound className="mr-2 h-4 w-4" />
            {operatorTokenStored ? 'Clear Director key' : 'Set Director key'}
          </Button>
          <span className="self-center text-xs text-muted-foreground">
            {operatorTokenStored ? 'Director key set for this tab' : 'Needed for protected settings, launch, autonomy, and recovery actions'}
          </span>
          <Button variant="outline" onClick={() => { void onRefresh(); void checkGateStatus() }} disabled={refreshing}>
            <RefreshCw className={cn('mr-2 h-4 w-4', refreshing && 'animate-spin')} />
            Refresh
          </Button>
          <Button ref={addRepoButtonRef} onClick={(event) => { scopeTriggerRef.current = event.currentTarget; setScopeDialog({ mode: 'add' }) }}>
            <Plus className="mr-2 h-4 w-4" />
            Add repo
          </Button>
        </div>
      </div>

      {gateStatus === 'active' && <p role="status" className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">Recovery-only mode is active: Deck&apos;s scheduler is limited to one configured issue attempt. Select Recovery-only mode for details.</p>}
      {gateStatus === 'unknown' && <p role="alert" className="text-sm text-destructive">Recovery-only mode could not be checked. Refresh before enabling autonomy.</p>}
      {gateStatus === 'loading' && <p role="status" className="text-xs text-muted-foreground">Checking recovery-only mode…</p>}

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3">
        {loading && <div className="rounded-lg border p-5 text-sm text-muted-foreground">Loading autonomy state...</div>}
        {!loading && !loadError && scopes.length === 0 && (
          <div className="rounded-lg border p-5 text-sm text-muted-foreground">
            <h3 className="font-semibold text-foreground">Before you enable autonomy</h3>
            <ol className="mt-2 list-decimal space-y-1 pl-5">
              <li>Add <code>github_token</code> to <code>backend/.env</code> for GitHub polling, then restart Deck. For App-backed dispatch, also configure the GitHub App settings. Deck selects the dispatch mode when work becomes eligible.</li>
              <li>Add a watched repo with an existing primary checkout under your home directory and labels to watch.</li>
              <li>In Roster, assign and launch the Leader slot. It approves plans.</li>
              <li>On GitHub, label an issue for dispatch; add an area label to route it to a particular owner.</li>
              <li>Enable autonomy. Deck polls GitHub every 60 seconds by default and shows progress here.</li>
            </ol>
            <p className="mt-2">The Director key protects roster and watched-repo settings, team launch, autonomy, recovery policy, and operator remedies. It is separate from the GitHub polling token and stays in this browser tab.</p>
          </div>
        )}
        {scopes.map((scope) => (
          <Card key={scope.id} className={cn('min-w-0', !scope.enabled && 'opacity-70')}>
            <CardContent className="min-w-0 p-4">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="min-w-0 break-all font-semibold">{scope.repo_owner}/{scope.repo_name}</p>
                    <Badge variant="outline" className="max-w-full truncate" title={scope.dispatch_label}>Dispatch: {scope.dispatch_label}</Badge>
                    <Badge variant="secondary" className="max-w-full truncate" title={scope.design_label}>Design: {scope.design_label}</Badge>
                    <Badge
                      variant="outline"
                      className={scope.merge_policy === 'auto' ? 'border-primary text-primary' : 'border-amber-500/70 text-amber-700 dark:text-amber-400'}
                    >
                      code merge: {scope.merge_policy}
                    </Badge>
                    <Badge
                      variant="outline"
                      className={scope.continuation_enabled ? 'border-emerald-500/70 text-emerald-700 dark:text-emerald-400' : undefined}
                      title="Bounded recovery of escalated issues with an open PR. Configure under Recovery policy."
                    >
                      recovery: {scope.continuation_enabled ? 'enabled' : 'off'}
                    </Badge>
                    {!scope.enabled && <Badge variant="secondary">disabled</Badge>}
                    <Badge variant="outline" title={authStatus(scope).help} className={authStatus(scope).warning ? 'border-amber-500 text-amber-700 dark:text-amber-400' : undefined}>
                      {authStatus(scope).label}
                    </Badge>
                  </div>
                  <p className="mt-2 truncate text-sm text-muted-foreground">
                    Primary checkout: {scope.repo_path}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Approval rounds: {scope.max_approval_rounds} · Concurrent issues: {scope.max_concurrent_dispatched} · Verification retries: {scope.max_verification_retries} · Auto-merges/day: {scope.max_auto_merges_per_day} · Last polled {formatDateTime(scope.last_polled_at)}{!preset.autonomy_enabled ? ' (autonomy off)' : ''}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Recovery limits: {scope.max_continuation_revisions} revisions · {scope.max_continuation_failed_heads} failed heads total · {scope.max_failed_heads_per_revision} per revision · {scope.max_scope_paths} paths · {scope.max_scope_commands} commands
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" aria-label={`Recovery policy for ${scope.repo_owner}/${scope.repo_name}`} onClick={() => setPolicyDialog({ scope })}>
                    <Settings2 className="mr-2 h-4 w-4" />
                    Recovery policy
                  </Button>
                  <Button variant="outline" size="sm" aria-label={`Edit ${scope.repo_owner}/${scope.repo_name}`} onClick={(event) => { scopeTriggerRef.current = event.currentTarget; setScopeDialog({ mode: 'edit', scope }) }}>
                    <Pencil className="mr-2 h-4 w-4" />
                    Edit
                  </Button>
                  <Button variant="destructive" size="sm" aria-label={`Remove ${scope.repo_owner}/${scope.repo_name}`} onClick={(event) => { removeTriggerRef.current = event.currentTarget; setScopeToRemove(scope) }}>
                    <Trash2 className="mr-2 h-4 w-4" />
                    Remove
                  </Button>
                </div>
              </div>
              <BacklogCoordination scopeId={scope.id} withOperatorToken={withOperatorToken} />
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="min-w-0">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4 text-sm">
          <p>
            {loading ? 'Loading work items…'
              : loadError && workItems.length === 0 ? 'Work items are unavailable. Use Refresh to try again.'
              : `${workItems.length} ${workItems.length === 1 ? 'item' : 'items'} · ${activeCount} active${actionCount > 0 ? ` · ${actionCount} ${actionCount === 1 ? 'needs' : 'need'} your action` : ''}`}
          </p>
          <span className="text-xs text-muted-foreground">
            {lastRefreshedAt ? `Summary updated ${lastRefreshedAt.toLocaleTimeString()}` : 'Summary not refreshed yet'}
          </span>
          <Link className="font-medium underline underline-offset-4" to={`/work?team_id=${preset.id}`}>View in Work ›</Link>
        </CardContent>
      </Card>

      <ScopeDialog state={scopeDialog} onOpenChange={setScopeDialog} onSave={saveScope} onReturnFocus={() => (scopeTriggerRef.current?.isConnected ? scopeTriggerRef.current : addRepoButtonRef.current)?.focus()} />
      <AlertDialog open={scopeToRemove !== null} onOpenChange={(open) => { if (!open && !scopeRemovalPending) setScopeToRemove(null) }}>
        <AlertDialogContent onCloseAutoFocus={(event) => {
          event.preventDefault()
          const target = removeTriggerRef.current?.isConnected ? removeTriggerRef.current : addRepoButtonRef.current
          target?.focus()
          removeTriggerRef.current = null
        }}>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove watched repo?</AlertDialogTitle>
            <AlertDialogDescription>
              Remove {scopeToRemove?.repo_owner}/{scopeToRemove?.repo_name} from this team. This stops polling and permanently deletes its saved work-item history. Active work cannot be removed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={scopeRemovalPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction disabled={scopeRemovalPending} onClick={(event) => { event.preventDefault(); if (scopeToRemove) void deleteScope(scopeToRemove) }}>
              {scopeRemovalPending ? 'Removing…' : 'Remove repo'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <ContinuationPolicyDialog
        state={policyDialog}
        autonomyEnabled={preset.autonomy_enabled}
        onOpenChange={setPolicyDialog}
        onSave={(scopeId, input) => withOperatorToken((token) => onUpdateContinuationPolicy(scopeId, input, token))}
      />
      {tokenDialog}
      <AlertDialog open={enableConfirmOpen} onOpenChange={setEnableConfirmOpen}>
        <AlertDialogContent onCloseAutoFocus={(event) => { event.preventDefault(); enableTriggerRef.current?.focus() }}>
          <AlertDialogHeader>
            <AlertDialogTitle>Enable autonomous dispatch?</AlertDialogTitle>
            <AlertDialogDescription>
              Deck will poll enabled repos every 60 seconds by default. Issues with the dispatch label will be assigned to agents, whose sessions run in worktrees beside each primary checkout.
              {enableGateActive && ' Recovery-only mode is active, so the scheduler is limited to its configured issue attempt.'}
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
            <AlertDialogAction disabled={toggleSaving} onClick={() => void applyToggle(true)}>Enable autonomy</AlertDialogAction>
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
