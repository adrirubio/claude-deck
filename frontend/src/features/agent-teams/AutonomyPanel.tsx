import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { KeyRound, Plus, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
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
  TeamGithubScope,
} from '@/types/agentTeams'
import { BacklogCoordination } from './BacklogCoordination'
import { workItemAttention } from './workItemAttention'
import { useOperatorTokenFlow } from './useOperatorTokenFlow'
import { fetchGithubRecoveryGate, fetchGithubRecoveryGateActive } from './api'

export { OperatorTokenDialog } from './OperatorTokenDialog'

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
}) {
  const enableTriggerRef = useRef<HTMLButtonElement | null>(null)
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
          <Link className={buttonVariants({})} to={`/repositories/new?team_id=${preset.id}`}>
            <Plus className="mr-2 h-4 w-4" />
            Add a repository
          </Link>
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
              <li>Add a repository with an existing primary checkout under your home directory and labels to watch. Use Add a repository above.</li>
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
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <p className="min-w-0 break-all font-semibold">{scope.repo_owner}/{scope.repo_name}</p>
                  <Badge variant="outline">
                    {!scope.enabled ? 'Off' : preset.autonomy_enabled ? 'On' : 'Off · team autonomy off'}
                  </Badge>
                </div>
                <Link className="font-medium underline underline-offset-4" to={`/repositories/${scope.id}`} aria-label={`Manage ${scope.repo_owner}/${scope.repo_name}`}>Manage ›</Link>
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
