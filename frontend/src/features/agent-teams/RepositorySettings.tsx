import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import type { TeamGithubScope, TeamGithubScopeUpdate } from '@/types/agentTeams'
import {
  ContinuationPolicyDialog, ScopeDialog,
  type PolicyDialogState, type ScopeDialogState,
} from './ScopeSettingsDialogs'
import { authStatus } from './scopeAuthStatus'
import { useScopeSettings } from './useScopeSettings'

function Section({ title, editLabel, onEdit, children }: {
  title: string
  editLabel: string
  onEdit: (element: HTMLButtonElement) => void
  children: React.ReactNode
}) {
  return (
    <section aria-label={title} className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold">{title}</h3>
        <Button variant="outline" size="sm" aria-label={editLabel} onClick={(event) => onEdit(event.currentTarget)}>
          Edit
        </Button>
      </div>
      <dl className="space-y-2 text-sm">{children}</dl>
    </section>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[12rem_1fr]">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 wrap-break-word">{children}</dd>
    </div>
  )
}

/**
 * The settings of one watched repository. The edit dialogs and the remove
 * confirmation moved here from the Autonomy tab (#536), with the same
 * requests, Director key prompts and confirmations.
 */
export function RepositorySettings({ scope, autonomyEnabled, refresh, onRemoved }: {
  scope: TeamGithubScope
  autonomyEnabled: boolean
  refresh: () => Promise<void>
  onRemoved: () => void
}) {
  const { saveScope, savePolicy, removeScope, tokenDialog } = useScopeSettings({ refresh })
  const [scopeDialog, setScopeDialog] = useState<ScopeDialogState>(null)
  const [policyDialog, setPolicyDialog] = useState<PolicyDialogState>(null)
  const [scopeToRemove, setScopeToRemove] = useState<TeamGithubScope | null>(null)
  const [removalPending, setRemovalPending] = useState(false)
  const trigger = useRef<HTMLButtonElement | null>(null)
  const auth = authStatus(scope)

  const remove = async (target: TeamGithubScope) => {
    setRemovalPending(true)
    try {
      await removeScope(target)
      setScopeToRemove(null)
      onRemoved()
    } catch {
      // The handler shows the error message.
    } finally {
      setRemovalPending(false)
    }
  }

  return (
    <div className="space-y-4">
      <Section
        title="Labels and routing"
        editLabel={`Edit labels and routing for ${scope.repo_owner}/${scope.repo_name}`}
        onEdit={(element) => { trigger.current = element; setScopeDialog({ mode: 'edit', scope }) }}
      >
        <Row label="Ready for the team"><code>{scope.dispatch_label}</code></Row>
        <Row label="Needs design review"><code>{scope.design_label}</code></Row>
        <Row label="Branch"><code>{scope.base_ref === 'origin/HEAD' ? 'origin/HEAD (default branch)' : scope.base_ref}</code></Row>
      </Section>
      <Section
        title="Merging and limits"
        editLabel={`Edit merging and limits for ${scope.repo_owner}/${scope.repo_name}`}
        onEdit={(element) => { trigger.current = element; setScopeDialog({ mode: 'edit', scope }) }}
      >
        <Row label="Who merges">{scope.merge_policy === 'auto' ? 'Deck merges after checks pass' : 'You (human merge)'}</Row>
        <Row label="Work at the same time">{scope.max_concurrent_dispatched} {scope.max_concurrent_dispatched === 1 ? 'issue' : 'issues'}</Row>
        <Row label="Review rounds">up to {scope.max_approval_rounds}</Row>
        <Row label="Verification retries">up to {scope.max_verification_retries}</Row>
        {scope.merge_policy === 'auto' && <Row label="Automatic merges a day">up to {scope.max_auto_merges_per_day}</Row>}
      </Section>
      <Section
        title="Recovery"
        editLabel={`Edit recovery policy for ${scope.repo_owner}/${scope.repo_name}`}
        onEdit={(element) => { trigger.current = element; setPolicyDialog({ scope }) }}
      >
        <Row label="Continue after a stop">
          {scope.continuation_enabled ? 'On' : 'Off'} · up to {scope.max_continuation_revisions} revisions, {scope.max_continuation_failed_heads} failed attempts
        </Row>
      </Section>
      <details className="rounded-lg border bg-card p-4">
        <summary className="cursor-pointer font-semibold">Technical details</summary>
        <dl className="mt-3 space-y-2 text-sm">
          <Row label="Primary checkout"><code className="break-all">{scope.repo_path}</code></Row>
          <Row label="Authentication">
            <span title={auth.help}>{auth.label}</span>
          </Row>
          <Row label="Team autonomy">{autonomyEnabled ? 'On' : 'Off'}</Row>
          <Row label="Builds out of tree">{scope.builds_out_of_tree ? `Yes · ${scope.build_dir_template ?? 'build'}` : 'No'}</Row>
          <Row label="Max build parallelism">{scope.max_build_parallelism}</Row>
          {scope.build_command_hint && <Row label="Build command hint"><code className="break-all">{scope.build_command_hint}</code></Row>}
          <Row label="Team page"><Link className="underline underline-offset-4" to={`/teams/${scope.preset_id}?tab=autonomy`}>Open the team</Link></Row>
        </dl>
        <Button
          variant="destructive"
          size="sm"
          className="mt-4"
          aria-label={`Remove ${scope.repo_owner}/${scope.repo_name}`}
          onClick={(event) => { trigger.current = event.currentTarget; setScopeToRemove(scope) }}
        >
          Remove repository
        </Button>
      </details>

      <ScopeDialog
        state={scopeDialog}
        onOpenChange={setScopeDialog}
        onSave={(input) => saveScope(scope.id, input as TeamGithubScopeUpdate)}
        onReturnFocus={() => trigger.current?.focus()}
      />
      <ContinuationPolicyDialog
        state={policyDialog}
        autonomyEnabled={autonomyEnabled}
        onOpenChange={setPolicyDialog}
        onSave={(scopeId, input) => savePolicy(scopeId, input)}
      />
      <AlertDialog open={scopeToRemove !== null} onOpenChange={(open) => { if (!open && !removalPending) setScopeToRemove(null) }}>
        <AlertDialogContent onCloseAutoFocus={(event) => { event.preventDefault(); trigger.current?.focus() }}>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove watched repo?</AlertDialogTitle>
            <AlertDialogDescription>
              Remove {scopeToRemove?.repo_owner}/{scopeToRemove?.repo_name} from this team. This stops polling and permanently deletes its saved work-item history. Active work cannot be removed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removalPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction disabled={removalPending} onClick={(event) => { event.preventDefault(); if (scopeToRemove) void remove(scopeToRemove) }}>
              {removalPending ? 'Removing…' : 'Remove repo'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {tokenDialog}
    </div>
  )
}
