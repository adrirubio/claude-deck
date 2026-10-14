import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
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
import { MODAL_SIZES } from '@/lib/constants'
import type {
  TeamGithubContinuationPolicyUpdate,
  TeamGithubMergePolicy,
  TeamGithubScope,
  TeamGithubScopeInput,
  TeamGithubScopeUpdate,
} from '@/types/agentTeams'

// Moved from the Autonomy tab (#536). The code is unchanged.
export type ScopeDialogState = { mode: 'add' | 'edit'; scope?: TeamGithubScope } | null
export type PolicyDialogState = { scope: TeamGithubScope } | null

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

export function ScopeDialog({
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

export function ContinuationPolicyDialog({
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
