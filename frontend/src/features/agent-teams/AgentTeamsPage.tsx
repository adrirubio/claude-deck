import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  ChevronDown,
  GitBranch,
  MonitorPlay,
  Plus,
  RefreshCw,
  Rocket,
  UsersRound,
} from 'lucide-react'
import { toast } from 'sonner'
import { formatServerTime } from '@/lib/serverTime'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { TEAM_SLOT_COLOR_OPTIONS } from '@/lib/agentTeamColors'
import { cn } from '@/lib/utils'
import { ApiHttpError } from '@/lib/api'
import { autonomousLeaderSlotId } from './leaderSlot'
import { fetchCCSessions } from '@/features/cc-bridge/api'
import type { AgentSession } from '@/features/cc-bridge/types'
import { TeamMemberPicker } from './TeamMemberPicker'
import { TeamHeader } from './TeamHeader'
import { EditTeamPanel } from './EditTeamPanel'
import { TeamMemberRow } from './TeamMemberRow'
import { TeamProgress } from './TeamProgress'
import { PROVIDER_IDS, isHiddenByDefault, memberItems, sessionItems, sessionKey, sessionsToSlots, usableSessions } from './teamSources'
import type {
  AgentTeamLaunchPlan,
  AgentTeamLaunchPlanItem,
  AgentTeamLaunchRequest,
  AgentTeamLaunchResult,
  AgentTeamPreset,
  AgentTeamSlot,
  AgentTeamSlotInput,
  GithubWorkItem,
  SlotLaunchOptions,
  TeamGithubScope,
} from '@/types/agentTeams'
import type { AgentProviderId, ProviderLaunchOptionsResponse } from '@/types/providers'
import {
  addAgentTeamSlot,
  createAgentTeamFromMail,
  createAgentTeamPreset,
  deleteAgentTeamPreset,
  deleteAgentTeamSlot,
  duplicateAgentTeamPreset,
  fetchAgentTeamPresets,
  fetchGithubWorkItems,
  fetchTeamGithubScopes,
  launchAgentTeam,
  planAgentTeamLaunch,
  reorderAgentTeamSlots,
  updateAgentTeamPreset,
  updateAgentTeamLeader,
  updateAgentTeamSlot,
} from './api'
import { fetchAgentMailTeam } from '@/features/agent-mail/api'
import { fetchProviderLaunchOptions } from '@/hooks/useProviders'
import type { MailMemberResponse } from '@/types/agentMail'
import { AgentTeamsHelpDialog } from './AgentTeamsHelpDialog'
import { ProviderLaunchOptionsFields } from '@/features/providers/ProviderLaunchOptionsFields'
import { AutonomyPanel, OperatorTokenDialog } from './AutonomyPanel'
import { HumanActionSummary } from './HumanActionSummary'
import { TeamSummaryCard } from './TeamSummaryCard'
import { useAgentActivity } from './useAgentActivity'
import { clearOperatorToken, getOperatorToken, setOperatorToken } from './operatorAuth'

type PresetDialogState = 'new' | 'from-mail' | 'from-bridge' | null
type SlotDialogState = { mode: 'add' | 'edit'; slot?: AgentTeamSlot } | null
type LaunchOptionsByProvider = Partial<Record<AgentProviderId, ProviderLaunchOptionsResponse>>

const DEFAULT_SLOT_COLOR_VALUE = 'default'

const emptySlot: AgentTeamSlotInput = {
  display_name: '',
  provider: 'codex-cli',
  repo_path: '',
  role: '',
  charter: '',
  ui_color: '',
  bootstrap_prompt: '',
  controlled_language_enabled: true,
  launch_mode: 'plain',
  launch_options: {},
  area_labels: [],
  expertise: '',
  enabled: true,
}

function formatDate(value: string) {
  return formatServerTime(value, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function actionBadgeClass(action: AgentTeamLaunchPlanItem['action']) {
  if (action === 'spawn') return 'border-emerald-500/70 text-emerald-700 dark:text-emerald-400'
  if (action === 'reuse') return 'border-sky-500/70 text-sky-700 dark:text-sky-400'
  if (action === 'adopt') return 'border-amber-500/70 text-amber-700 dark:text-amber-400'
  if (action === 'blocked') return 'border-destructive/70 text-destructive'
  return 'border-muted-foreground/50 text-muted-foreground'
}

function parseLaunchOptions(raw: string): SlotLaunchOptions {
  const text = raw.trim()
  if (!text) return {}
  const parsed = JSON.parse(text)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Launch options must be a JSON object')
  }
  return parsed as SlotLaunchOptions
}

function parseLabelList(raw: string): string[] {
  const seen = new Set<string>()
  const labels: string[] = []
  for (const part of raw.split(/[,\n]/)) {
    const label = part.trim()
    if (!label || seen.has(label)) continue
    labels.push(label)
    seen.add(label)
  }
  return labels
}

function modeOptionsFor(
  provider: AgentProviderId | string,
  launchOptionsByProvider: LaunchOptionsByProvider
) {
  const modes = launchOptionsByProvider[provider as AgentProviderId]?.supported_launch_modes
  return modes && modes.length > 0 ? modes : ['plain']
}

function normalizeModeForProvider(
  provider: AgentProviderId | string,
  launchMode: string | undefined,
  launchOptionsByProvider: LaunchOptionsByProvider
) {
  const modes = modeOptionsFor(provider, launchOptionsByProvider)
  const current = launchMode || 'plain'
  return modes.includes(current) ? current : modes[0]
}

function slotToInput(slot: AgentTeamSlot): AgentTeamSlotInput {
  return {
    display_name: slot.display_name,
    provider: slot.provider,
    repo_path: slot.repo_path,
    role: slot.role ?? '',
    charter: slot.charter ?? '',
    ui_color: slot.ui_color ?? '',
    bootstrap_prompt: slot.bootstrap_prompt ?? '',
    controlled_language_enabled: slot.controlled_language_enabled ?? true,
    launch_mode: slot.launch_mode,
    launch_options: slot.launch_options ?? {},
    area_labels: slot.area_labels ?? [],
    expertise: slot.expertise ?? '',
    enabled: slot.enabled,
    position: slot.position,
  }
}

function usePresetForm(preset: AgentTeamPreset | undefined) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    queueMicrotask(() => {
      setName(preset?.name ?? '')
      setDescription(preset?.description ?? '')
    })
  }, [preset?.id, preset?.name, preset?.description])

  return { name, setName, description, setDescription }
}

function NewPresetDialog({
  mode,
  onOpenChange,
  onCreate,
}: {
  mode: PresetDialogState
  onOpenChange: (mode: PresetDialogState) => void
  onCreate: (input: {
    name: string
    description: string
    includeOffline?: boolean
    memberIds?: number[]
    sessions?: AgentSession[]
  }) => Promise<void>
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  // Offline and temporary members stay hidden until the person asks for them.
  const [showHidden, setShowHidden] = useState(false)
  const [mailMembers, setMailMembers] = useState<MailMemberResponse[]>([])
  const [selectedMemberIds, setSelectedMemberIds] = useState<number[]>([])
  const [bridgeSessions, setBridgeSessions] = useState<AgentSession[]>([])
  const [selectedSessionKeys, setSelectedSessionKeys] = useState<string[]>([])
  const [loadingMembers, setLoadingMembers] = useState(false)
  const [saving, setSaving] = useState(false)
  const open = mode !== null

  useEffect(() => {
    if (open) {
      queueMicrotask(() => {
        setName(
          mode === 'from-mail'
            ? 'Agent Mail roster'
            : mode === 'from-bridge'
              ? 'Agent Bridge sessions'
              : ''
        )
        setDescription('')
        setShowHidden(false)
        setMailMembers([])
        setSelectedMemberIds([])
        setBridgeSessions([])
        setSelectedSessionKeys([])
      })
    }
  }, [mode, open])

  useEffect(() => {
    if (!open || mode !== 'from-mail') return
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) setLoadingMembers(true)
    })
    fetchAgentMailTeam(true)
      .then((response) => {
        if (cancelled) return
        const members = response.members
        setMailMembers(members)
        // Preselect only members that are shown and not in a team.
        setSelectedMemberIds(
          members.filter((member) => member.team_preset_id == null && !isHiddenByDefault(member)).map((member) => member.id),
        )
      })
      .catch((error) => {
        toast.error(error instanceof Error ? error.message : 'Failed to load Agent Mail members')
      })
      .finally(() => {
        if (!cancelled) setLoadingMembers(false)
      })
    return () => {
      cancelled = true
    }
  }, [mode, open])

  useEffect(() => {
    if (!open || mode !== 'from-bridge') return
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) setLoadingMembers(true)
    })
    fetchCCSessions()
      .then((response) => {
        if (cancelled) return
        const usable = usableSessions(response.sessions)
        setBridgeSessions(usable)
        // Preselect only live sessions that are not in a team.
        setSelectedSessionKeys(usable.filter((session) => !session.team_preset_name).map(sessionKey))
      })
      .catch((error) => {
        toast.error(error instanceof Error ? error.message : 'Failed to load live sessions')
      })
      .finally(() => {
        if (!cancelled) setLoadingMembers(false)
      })
    return () => {
      cancelled = true
    }
  }, [mode, open])

  const visibleMembers = mailMembers.filter((member) => showHidden || !isHiddenByDefault(member))
  const selectedCount = mode === 'from-bridge' ? selectedSessionKeys.length : selectedMemberIds.length
  const countLabel = `Create team with ${selectedCount} ${selectedCount === 1 ? 'member' : 'members'}`

  const title = mode === 'from-mail'
    ? 'Create From Agent Mail'
    : mode === 'from-bridge'
      ? 'Create From Agent Bridge'
      : 'New Agent Team'

  const submit = async () => {
    setSaving(true)
    try {
      await onCreate({
        name,
        description,
        // The person saw and selected each member, offline ones included.
        includeOffline: true,
        memberIds: mode === 'from-mail' ? selectedMemberIds : undefined,
        sessions: mode === 'from-bridge'
          ? bridgeSessions.filter((session) => selectedSessionKeys.includes(sessionKey(session)))
          : undefined,
      })
      onOpenChange(null)
    } catch {
      // createPreset already showed the error. The dialog stays open so the person can fix it.
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => onOpenChange(next ? mode : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="team-name">Name</Label>
            <Input id="team-name" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="team-description">Description</Label>
            <Textarea
              id="team-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          {mode === 'from-mail' && (
            <div className="grid gap-3">
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={showHidden}
                  onCheckedChange={(checked) => {
                    const next = checked === true
                    setShowHidden(next)
                    if (!next) {
                      const shown = new Set(mailMembers.filter((member) => !isHiddenByDefault(member)).map((member) => member.id))
                      setSelectedMemberIds((current) => current.filter((memberId) => shown.has(memberId)))
                    }
                  }}
                />
                Show offline and temporary
              </label>
              <TeamMemberPicker
                items={memberItems(visibleMembers)}
                selected={selectedMemberIds.map(String)}
                loading={loadingMembers}
                emptyText="No Agent Mail members to show."
                onToggle={(id, checked) => {
                  const memberId = Number(id)
                  setSelectedMemberIds((current) =>
                    checked ? [...new Set([...current, memberId])] : current.filter((value) => value !== memberId))
                }}
              />
            </div>
          )}
          {mode === 'from-bridge' && (
            <TeamMemberPicker
              items={sessionItems(bridgeSessions)}
              selected={selectedSessionKeys}
              loading={loadingMembers}
              emptyText="No live sessions found."
              onToggle={(id, checked) =>
                setSelectedSessionKeys((current) =>
                  checked ? [...new Set([...current, id])] : current.filter((value) => value !== id))}
            />
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(null)}>Cancel</Button>
          <Button
            onClick={submit}
            disabled={saving || !name.trim() || (mode !== 'new' && mode !== null && selectedCount === 0)}
          >
            {saving ? 'Creating' : mode === 'from-mail' || mode === 'from-bridge' ? countLabel : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SlotDialog({
  state,
  onOpenChange,
  onSave,
  launchOptionsByProvider,
}: {
  state: SlotDialogState
  onOpenChange: (state: SlotDialogState) => void
  onSave: (input: AgentTeamSlotInput) => Promise<void>
  launchOptionsByProvider: LaunchOptionsByProvider
}) {
  const [form, setForm] = useState<AgentTeamSlotInput>(emptySlot)
  const [launchOptionsText, setLaunchOptionsText] = useState('{}')
  const [areaLabelsText, setAreaLabelsText] = useState('')
  const [saving, setSaving] = useState(false)
  const open = state !== null
  const selectedProvider = form.provider as AgentProviderId
  const descriptor = launchOptionsByProvider[selectedProvider]
  const modeOptions = useMemo(
    () => modeOptionsFor(form.provider, launchOptionsByProvider),
    [form.provider, launchOptionsByProvider]
  )
  const modeOptionsKey = modeOptions.join('|')

  useEffect(() => {
    if (!state) return
    const next = state.slot ? slotToInput(state.slot) : emptySlot
    queueMicrotask(() => {
      setForm(next)
      setLaunchOptionsText(JSON.stringify(next.launch_options ?? {}, null, 2))
      setAreaLabelsText((next.area_labels ?? []).join(', '))
    })
  }, [state])

  const update = (patch: Partial<AgentTeamSlotInput>) => {
    setForm((current) => ({ ...current, ...patch }))
  }

  useEffect(() => {
    if (!open || modeOptions.includes(form.launch_mode ?? 'plain')) return
    queueMicrotask(() => update({ launch_mode: modeOptions[0] }))
  }, [form.launch_mode, modeOptions, modeOptionsKey, open])

  const updateLaunchOptions = (launch_options: SlotLaunchOptions) => {
    update({ launch_options })
    setLaunchOptionsText(JSON.stringify(launch_options, null, 2))
  }

  const submit = async () => {
    setSaving(true)
    try {
      await onSave({
        ...form,
        area_labels: parseLabelList(areaLabelsText),
        launch_options: parseLaunchOptions(launchOptionsText),
      })
      onOpenChange(null)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save slot')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => onOpenChange(next ? state : null)}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{state?.mode === 'edit' ? 'Edit Slot' : 'Add Slot'}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="slot-name">Name</Label>
            <Input
              id="slot-name"
              value={form.display_name}
              onChange={(event) => update({ display_name: event.target.value })}
            />
          </div>
          <div className="grid gap-2">
            <Label>Provider</Label>
            <Select
              value={form.provider}
              onValueChange={(provider) => {
                update({ provider, launch_mode: normalizeModeForProvider(provider, form.launch_mode, launchOptionsByProvider) })
                if (provider === 'pi-cli') updateLaunchOptions({ platform: 'openrouter' })
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="codex-cli">Codex CLI</SelectItem>
                <SelectItem value="claude-code">Claude Code</SelectItem>
                <SelectItem value="copilot-cli">GitHub Copilot CLI</SelectItem>
                <SelectItem value="opencode-cli">OpenCode CLI</SelectItem>
                <SelectItem value="pi-cli">Pi (OpenRouter)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2 md:col-span-2">
            <Label htmlFor="slot-repo">Repo path</Label>
            <Input
              id="slot-repo"
              value={form.repo_path}
              onChange={(event) => update({ repo_path: event.target.value })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="slot-role">Role</Label>
            <Input
              id="slot-role"
              value={form.role ?? ''}
              onChange={(event) => update({ role: event.target.value })}
            />
            <p className="text-xs text-muted-foreground">Role text is descriptive. Set the Leader explicitly in the roster. Reordering does not change Leader authority.</p>
          </div>
          <div className="grid gap-2">
            <Label>Color</Label>
            <Select
              value={form.ui_color || DEFAULT_SLOT_COLOR_VALUE}
              onValueChange={(ui_color) => update({
                ui_color: ui_color === DEFAULT_SLOT_COLOR_VALUE ? '' : ui_color,
              })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DEFAULT_SLOT_COLOR_VALUE}>Default</SelectItem>
                {TEAM_SLOT_COLOR_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label>Launch mode</Label>
            <Select value={form.launch_mode ?? 'plain'} onValueChange={(launch_mode) => update({ launch_mode })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {modeOptions.map((mode) => (
                  <SelectItem key={mode} value={mode}>
                    {mode[0].toUpperCase() + mode.slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2 md:col-span-2">
            <Label htmlFor="slot-charter">Charter</Label>
            <Textarea
              id="slot-charter"
              value={form.charter ?? ''}
              onChange={(event) => update({ charter: event.target.value })}
            />
          </div>
          <div className="grid gap-4 rounded-lg border border-primary/30 bg-primary/5 p-4 md:col-span-2">
            <div>
              <Badge variant="outline" className="border-primary text-primary">
                GitHub dispatch routing
              </Badge>
              <p className="mt-2 text-sm text-muted-foreground">
                Optional SME routing metadata used by autonomous GitHub dispatch.
              </p>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="slot-area-labels">Area labels</Label>
              <Input
                id="slot-area-labels"
                value={areaLabelsText}
                placeholder="area:backend, area:api"
                onChange={(event) => setAreaLabelsText(event.target.value)}
              />
              <div className="flex flex-wrap gap-2">
                {parseLabelList(areaLabelsText).map((label) => (
                  <Badge key={label} variant="secondary">{label}</Badge>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                Mechanical match checked first against incoming GitHub issue labels.
              </p>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="slot-expertise">Expertise</Label>
              <Textarea
                id="slot-expertise"
                value={form.expertise ?? ''}
                placeholder="Owns the backend API, database models, and background jobs."
                onChange={(event) => update({ expertise: event.target.value })}
              />
              <p className="text-xs text-muted-foreground">
                Used only as fallback classifier input when no area label matches.
              </p>
            </div>
          </div>
          <div className="grid gap-2 md:col-span-2">
            <Label htmlFor="slot-bootstrap">Bootstrap prompt</Label>
            <Textarea
              id="slot-bootstrap"
              value={form.bootstrap_prompt ?? ''}
              onChange={(event) => update({ bootstrap_prompt: event.target.value })}
            />
          </div>
          <div className="grid gap-3 md:col-span-2">
            <Label>Launch options</Label>
            <ProviderLaunchOptionsFields
              provider={form.provider}
              value={form.launch_options ?? {}}
              onChange={updateLaunchOptions}
              descriptor={descriptor}
              disabled={saving}
            />
            <Collapsible>
              <CollapsibleTrigger asChild>
                <Button type="button" variant="ghost" size="sm" className="w-fit px-0">
                  <ChevronDown className="mr-1 h-4 w-4" />
                  Advanced raw JSON
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="grid gap-2">
                <Label htmlFor="slot-options">Launch options JSON</Label>
                <Textarea
                  id="slot-options"
                  className="min-h-[120px] font-mono"
                  value={launchOptionsText}
                  onChange={(event) => setLaunchOptionsText(event.target.value)}
                />
              </CollapsibleContent>
            </Collapsible>
          </div>
          <div className="grid gap-2 md:col-span-2">
            <div className="flex items-center gap-2">
              <Checkbox
                id="slot-controlled-language"
                checked={form.controlled_language_enabled ?? true}
                onCheckedChange={(checked) => update({ controlled_language_enabled: checked === true })}
                aria-describedby="slot-controlled-language-help"
                disabled={saving}
              />
              <Label htmlFor="slot-controlled-language">Controlled language (ASD-STE100)</Label>
            </div>
            <p id="slot-controlled-language-help" className="text-xs text-muted-foreground">
              Use short, clear English for team messages and GitHub text. Clear this option to use the member&apos;s own writing style.
              The new setting applies when the member receives new Deck instructions.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={form.enabled}
              onCheckedChange={(checked) => update({ enabled: checked === true })}
            />
            Enabled
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(null)}>Cancel</Button>
          <Button onClick={submit} disabled={saving || !form.display_name.trim() || !form.repo_path.trim()}>
            {saving ? 'Saving' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function LaunchPlanDialog({
  plan,
  result,
  loading,
  launching,
  onOpenChange,
  onLaunch,
  onReviewAdoption,
  onReviewFreshSpawn,
}: {
  plan: AgentTeamLaunchPlan | null
  result: AgentTeamLaunchResult | null
  loading: boolean
  launching: boolean
  onOpenChange: (open: boolean) => void
  onLaunch: () => Promise<void>
  onReviewAdoption: () => Promise<void>
  onReviewFreshSpawn: () => Promise<void>
}) {
  const open = Boolean(plan || loading || result)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>Launch Plan</DialogTitle>
          {plan && (
            <DialogDescription>
              {plan.reuse_count} reuse, {plan.adopt_count ?? 0} adopt, {plan.spawn_count} spawn, {plan.skipped_count} skipped, {plan.blocked_count} blocked
            </DialogDescription>
          )}
        </DialogHeader>
        {loading && <div className="py-8 text-sm text-muted-foreground">Planning launch...</div>}
        {plan && (
          <div className="space-y-3">
            {plan.items.map((item) => (
              <div key={item.slot_id} className="rounded-lg border p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold">{item.slot_name}</p>
                      <Badge variant="outline" className={actionBadgeClass(item.action)}>
                        {item.action}
                      </Badge>
                      <Badge variant="secondary">{item.provider}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">{item.repo_path}</p>
                  </div>
                  <p className="text-sm text-muted-foreground">{item.status}</p>
                </div>
                {item.reasons.length > 0 && (
                  <p className="mt-3 text-sm text-muted-foreground">{item.reasons.join('; ')}</p>
                )}
                {(item.action === 'adopt' || item.block_code === 'unbound_pane_requires_operator_adoption') && (
                  <p className="mt-2 text-sm text-amber-700 dark:text-amber-300">
                    Unbound pane: {String(item.matching_session?.tmux_target ?? 'unknown')} (PID {String(item.matching_session?.pid ?? 'unknown')}).
                    Its current prompt and authority were not created by this roster.
                  </p>
                )}
                {item.warnings && item.warnings.length > 0 && (
                  <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-sm text-amber-800 dark:text-amber-300">
                    {item.warnings.join('; ')}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {result && (
          <div className="space-y-3 border-t pt-4">
            <p className="text-sm font-medium">Launch #{result.launch_id}: {result.status}</p>
            {result.items.map((item) => (
              <div key={`${item.slot_id}-${item.status}`} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
                <div>
                  <p className="font-medium">{item.slot_name}</p>
                  <p className="text-sm text-muted-foreground">
                    {item.tmux_target ?? item.session_name ?? item.error ?? item.repo_path}
                  </p>
                  {item.message && <p className="mt-1 text-sm">{item.message}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {item.workspace_trust_changed && <Badge variant="secondary">Workspace trust changed</Badge>}
                  <Badge variant={item.status === 'failed' ? 'destructive' : 'outline'}>
                    {item.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          {plan?.items.some((item) => item.block_code === 'unbound_pane_requires_operator_adoption') && (
            <>
              <Button variant="outline" onClick={onReviewFreshSpawn} disabled={loading || launching}>
                Review fresh spawn
              </Button>
              <Button variant="outline" onClick={onReviewAdoption} disabled={loading || launching}>
                Review explicit adoption
              </Button>
            </>
          )}
          {plan && (
            <Button onClick={onLaunch} disabled={launching || !plan.can_launch || plan.spawn_count + plan.reuse_count + (plan.adopt_count ?? 0) === 0}>
              <Rocket className="mr-2 h-4 w-4" />
              {launching ? 'Launching' : (plan.adopt_count ?? 0) > 0 ? 'Adopt and launch' : 'Launch'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const DEFAULT_TOKEN_REASON = 'to change the team roster or launch the team'

export function AgentTeamsPage() {
  const { teamId } = useParams()
  const [contextParams] = useSearchParams()
  const navigate = useNavigate()
  const requestedTeamId = teamId && /^\d+$/.test(teamId) ? Number(teamId) : null
  // A team part that is not a number names no team. It must not fall back to another team.
  const hasTeamParam = Boolean(teamId)
  const requestedSlotId = Number(contextParams.get('slot_id')) || null
  const requestedTab = contextParams.get('tab')

  const [presets, setPresets] = useState<AgentTeamPreset[]>([])
  const [selectedPresetIdState, setSelectedPresetId] = useState<number | null>(requestedTeamId)
  const selectedPresetId = requestedTeamId ?? (hasTeamParam ? null : selectedPresetIdState)
  const presetRequestIdRef = useRef(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [presetDialog, setPresetDialog] = useState<PresetDialogState>(null)
  const [slotDialog, setSlotDialog] = useState<SlotDialogState>(null)
  const [plan, setPlan] = useState<AgentTeamLaunchPlan | null>(null)
  const [launchResult, setLaunchResult] = useState<AgentTeamLaunchResult | null>(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [plannedSlotIds, setPlannedSlotIds] = useState<number[] | null>(null)
  const [adoptUnboundSessions, setAdoptUnboundSessions] = useState(false)
  const [reuseExistingSessions, setReuseExistingSessions] = useState(true)
  const [helpOpen, setHelpOpen] = useState(false)
  const [editTeamOpen, setEditTeamOpen] = useState(false)
  const [launchOptionsByProvider, setLaunchOptionsByProvider] = useState<LaunchOptionsByProvider>({})
  const [githubScopes, setGithubScopes] = useState<TeamGithubScope[]>([])
  const [githubWorkItems, setGithubWorkItems] = useState<GithubWorkItem[]>([])
  const [autonomyLoading, setAutonomyLoading] = useState(false)
  const [autonomyRefreshing, setAutonomyRefreshing] = useState(false)
  const [autonomyTab, setAutonomyTab] = useState<'roster' | 'autonomy'>(requestedTab === 'autonomy' ? 'autonomy' : 'roster')
  const [autonomyLastRefreshedAt, setAutonomyLastRefreshedAt] = useState<Date | null>(null)
  const [autonomyLoadError, setAutonomyLoadError] = useState<string | null>(null)
  const [autonomyDataPresetId, setAutonomyDataPresetId] = useState<number | null>(null)
  const autonomyRequestIdRef = useRef(0)
  const autonomyManualRequestIdRef = useRef<number | null>(null)
  const autonomyDataPresetIdRef = useRef<number | null>(null)
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [tokenError, setTokenError] = useState<string | null>(null)
  const [tokenReason, setTokenReason] = useState(DEFAULT_TOKEN_REASON)
  const tokenResolverRef = useRef<((token: string | null) => void) | null>(null)
  const tokenPromiseRef = useRef<Promise<string | null> | null>(null)
  const teamContextGenerationRef = useRef(0)
  const currentTeamIdRef = useRef(selectedPresetId)

  // Retire authorization at route commit, before a pending token can resume an old action.
  useLayoutEffect(() => {
    currentTeamIdRef.current = selectedPresetId
    return () => {
      teamContextGenerationRef.current += 1
      tokenResolverRef.current?.(null)
      tokenResolverRef.current = null
      tokenPromiseRef.current = null
    }
  }, [selectedPresetId, contextParams])

  useEffect(() => () => {
    tokenResolverRef.current?.(null)
    tokenResolverRef.current = null
    tokenPromiseRef.current = null
  }, [])

  const requestOperatorToken = (error: string | null = null, reason = DEFAULT_TOKEN_REASON): Promise<string | null> => {
    const stored = getOperatorToken()
    if (stored) return Promise.resolve(stored)
    if (tokenPromiseRef.current) return tokenPromiseRef.current
    setTokenError(error)
    setTokenReason(reason)
    setTokenDialogOpen(true)
    const pending = new Promise<string | null>((resolve) => { tokenResolverRef.current = resolve })
    tokenPromiseRef.current = pending
    return pending
  }

  const settleOperatorToken = (token: string | null) => {
    tokenResolverRef.current?.(token)
    tokenResolverRef.current = null
    tokenPromiseRef.current = null
    setTokenDialogOpen(false)
    setTokenInput('')
    setTokenError(null)
  }

  const withOperatorToken = async <Result,>(action: (token: string) => Promise<Result>, reason = DEFAULT_TOKEN_REASON): Promise<Result> => {
    const generation = teamContextGenerationRef.current
    const targetId = currentTeamIdRef.current
    const assertCurrentContext = () => {
      if (generation !== teamContextGenerationRef.current || targetId !== currentTeamIdRef.current) {
        throw new Error('Team context changed. Review the current team again.')
      }
    }
    for (let attempt = 0; attempt < 2; attempt++) {
      assertCurrentContext()
      const token = await requestOperatorToken(attempt ? 'The Director key was rejected. Enter a valid key to retry.' : null, reason)
      assertCurrentContext()
      if (!token) throw new Error('The Director key is required for this action.')
      try {
        const result = await action(token)
        assertCurrentContext()
        return result
      } catch (error) {
        assertCurrentContext()
        if (!(error instanceof ApiHttpError) || error.status !== 401) throw error
        clearOperatorToken()
        if (attempt === 1) throw error
      }
    }
    throw new Error('The Director key was rejected.')
  }

  const selectedPreset = useMemo(
    () => presets.find((preset) => preset.id === selectedPresetId),
    [presets, selectedPresetId]
  )
  const { name, setName, description, setDescription } = usePresetForm(selectedPreset)
  // Per-team reads start only for a team in the loaded list.
  const knownPresetId = selectedPreset ? selectedPresetId : null
  const agentActivity = useAgentActivity(knownPresetId)

  const loadPresets = useCallback(async () => {
    const requestId = ++presetRequestIdRef.current
    setLoading(true)
    try {
      const response = await fetchAgentTeamPresets()
      if (requestId !== presetRequestIdRef.current) return
      setPresets(response.presets)
      setSelectedPresetId((current) => {
        if (hasTeamParam) return requestedTeamId
        if (current && response.presets.some((preset) => preset.id === current)) return current
        return requestedTeamId ?? response.presets[0]?.id ?? null
      })
      if (!requestedTab && !contextParams.has('review_launch')) {
        // An unknown team id gets no per-team request.
        const initial = hasTeamParam
          ? (response.presets.some((preset) => preset.id === requestedTeamId) ? requestedTeamId : null)
          : response.presets[0]?.id
        if (initial) {
          try {
            const scopes = await fetchTeamGithubScopes(initial)
            if (requestId === presetRequestIdRef.current) setAutonomyTab(scopes.scopes.length ? 'autonomy' : 'roster')
          } catch { /* Keep roster usable when the scope read is unavailable. */ }
        }
      }

    } catch (error) {
      if (requestId === presetRequestIdRef.current) toast.error(error instanceof Error ? error.message : 'Failed to load Agent Teams')
    } finally {
      if (requestId === presetRequestIdRef.current) setLoading(false)
    }
  }, [hasTeamParam, requestedTeamId, requestedTab, contextParams])

  const loadProviderLaunchOptions = useCallback(async () => {
    try {
      const descriptors = await Promise.all(
        PROVIDER_IDS.map((providerId) => fetchProviderLaunchOptions(providerId))
      )
      setLaunchOptionsByProvider(
        Object.fromEntries(
          descriptors.map((descriptor) => [descriptor.provider, descriptor])
        ) as LaunchOptionsByProvider
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to load provider launch options')
    }
  }, [])

  const loadAutonomy = useCallback(async (presetId: number, showLoading = false, manual = false) => {
    const requestId = autonomyRequestIdRef.current + 1
    autonomyRequestIdRef.current = requestId
    if (showLoading) {
      setAutonomyLoading(true)
      autonomyManualRequestIdRef.current = null
      setAutonomyRefreshing(false)
    }
    if (manual) {
      autonomyManualRequestIdRef.current = requestId
      setAutonomyRefreshing(true)
    }
    try {
      const [scopeResponse, workItemResponse] = await Promise.all([
        fetchTeamGithubScopes(presetId),
        fetchGithubWorkItems(presetId),
      ])
      if (autonomyRequestIdRef.current === requestId) {
        setGithubScopes(scopeResponse.scopes)
        setGithubWorkItems(workItemResponse.items)
        autonomyDataPresetIdRef.current = presetId
        setAutonomyDataPresetId(presetId)
        setAutonomyLastRefreshedAt(new Date())
        setAutonomyLoadError(null)
      }
    } catch (error) {
      if (autonomyRequestIdRef.current === requestId) {
        const message = error instanceof Error ? error.message : 'Failed to load autonomy state'
        if (autonomyDataPresetIdRef.current !== presetId) {
          setGithubScopes([])
          setGithubWorkItems([])
          setAutonomyLastRefreshedAt(null)
          autonomyDataPresetIdRef.current = presetId
          setAutonomyDataPresetId(presetId)
        }
        setAutonomyLoadError(message)
        if (showLoading || manual) toast.error(message)
      }
    } finally {
      if (autonomyRequestIdRef.current === requestId) {
        setAutonomyLoading(false)
      }
      if (autonomyManualRequestIdRef.current === requestId) {
        autonomyManualRequestIdRef.current = null
        setAutonomyRefreshing(false)
      }
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) {
        setPlan(null)
        setLaunchResult(null)
        setPlanLoading(false)
        setLaunching(false)
        setTokenDialogOpen(false)
        setTokenInput('')
        setTokenError(null)
        void loadPresets()
        void loadProviderLaunchOptions()
      }
    })
    return () => {
      cancelled = true
      presetRequestIdRef.current += 1
      autonomyRequestIdRef.current += 1
    }
  }, [loadPresets, loadProviderLaunchOptions])

  useEffect(() => {
    if (!knownPresetId) {
      autonomyRequestIdRef.current += 1
      autonomyDataPresetIdRef.current = null
      queueMicrotask(() => {
        setGithubScopes([])
        setGithubWorkItems([])
        setAutonomyLoading(false)
        setAutonomyRefreshing(false)
        setAutonomyLastRefreshedAt(null)
        setAutonomyLoadError(null)
        setAutonomyDataPresetId(null)
      })
      return
    }
    if (autonomyTab !== 'autonomy') return
    let cancelled = false
    queueMicrotask(() => { if (!cancelled) void loadAutonomy(knownPresetId, true) })
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') void loadAutonomy(knownPresetId)
    }, 5000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
      autonomyRequestIdRef.current += 1
      autonomyManualRequestIdRef.current = null
    }
  }, [autonomyTab, loadAutonomy, knownPresetId])

  const replacePreset = (preset: AgentTeamPreset) => {
    setPresets((current) => current.map((item) => (item.id === preset.id ? preset : item)))
    setSelectedPresetId(preset.id)
  }

  const savePreset = async (): Promise<boolean> => {
    if (!selectedPreset) return false
    setSaving(true)
    try {
      const updated = await withOperatorToken((token) => updateAgentTeamPreset(selectedPreset.id, {
        name,
        description,
      }, token))
      replacePreset(updated)
      toast.success('Team saved')
      return true
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save team')
      return false
    } finally {
      setSaving(false)
    }
  }

  const createPreset = async (input: {
    name: string
    description: string
    includeOffline?: boolean
    memberIds?: number[]
    sessions?: AgentSession[]
  }) => {
    try {
      const created = await withOperatorToken((token) => presetDialog === 'from-mail'
        ? createAgentTeamFromMail({
          name: input.name,
          description: input.description,
          member_ids: input.memberIds,
          include_offline: input.includeOffline,
        }, token)
        : presetDialog === 'from-bridge'
          // The backend route would take every live session. This creates exactly the selected ones.
          ? createAgentTeamPreset({
            name: input.name,
            description: input.description,
            created_by: 'deck-ui',
            slots: sessionsToSlots(input.sessions ?? []),
          }, token)
          : createAgentTeamPreset({
            name: input.name,
            description: input.description,
            created_by: 'deck-ui',
            slots: [],
          }, token))
      setPresets((current) => [created, ...current])
      setSelectedPresetId(created.id)
      toast.success('Team created')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to create team')
      throw error
    }
  }

  const duplicatePreset = async (): Promise<boolean> => {
    if (!selectedPreset) return false
    try {
      const created = await withOperatorToken((token) => duplicateAgentTeamPreset(selectedPreset.id, {
        name: `${selectedPreset.name} copy`,
      }, token))
      setPresets((current) => [created, ...current])
      setSelectedPresetId(created.id)
      toast.success('Team duplicated')
      return true
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to duplicate team')
      return false
    }
  }

  const removePreset = async (): Promise<boolean> => {
    if (!selectedPreset) return false
    try {
      await withOperatorToken((token) => deleteAgentTeamPreset(selectedPreset.id, token))
      setPresets((current) => current.filter((preset) => preset.id !== selectedPreset.id))
      setSelectedPresetId((current) => {
        const remaining = presets.filter((preset) => preset.id !== current)
        return remaining[0]?.id ?? null
      })
      toast.success('Team deleted')
      return true
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to delete team')
      return false
    }
  }

  const saveSlot = async (input: AgentTeamSlotInput) => {
    if (!selectedPreset || !slotDialog) return
    const normalizedInput = {
      ...input,
      position: input.position ?? undefined,
    }
    const saved = await withOperatorToken((token) => slotDialog.mode === 'edit' && slotDialog.slot
      ? updateAgentTeamSlot(slotDialog.slot.id, normalizedInput, token)
      : addAgentTeamSlot(selectedPreset.id, normalizedInput, token))
    replacePreset(saved)
    toast.success('Slot saved')
  }

  // The switch, its confirmation and the Director key stay in the Autonomy tab. The header button opens it there.
  const openAutonomySwitch = () => {
    setAutonomyTab('autonomy')
    window.setTimeout(() => document.getElementById('autonomy-enabled')?.focus(), 50)
  }

  const refreshAutonomy = async () => {
    if (!selectedPreset) return
    await loadAutonomy(selectedPreset.id, false, true)
  }

  const toggleAutonomy = async (enabled: boolean, operatorToken: string) => {
    if (!selectedPreset) return
    try {
      const updated = await updateAgentTeamPreset(selectedPreset.id, {
        autonomy_enabled: enabled,
      }, operatorToken)
      replacePreset(updated)
      toast.success(enabled ? 'Autonomy enabled' : 'Autonomy disabled')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to update autonomy')
      throw error
    }
  }

  const removeSlot = async (slot: AgentTeamSlot) => {
    try {
      const updated = await withOperatorToken((token) => deleteAgentTeamSlot(slot.id, token))
      replacePreset(updated)
      toast.success('Slot deleted')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to delete slot')
    }
  }

  const moveSlot = async (slot: AgentTeamSlot, direction: -1 | 1) => {
    if (!selectedPreset) return
    const currentIndex = selectedPreset.slots.findIndex((item) => item.id === slot.id)
    const nextIndex = currentIndex + direction
    if (currentIndex < 0 || nextIndex < 0 || nextIndex >= selectedPreset.slots.length) return
    const nextSlots = [...selectedPreset.slots]
    const [moved] = nextSlots.splice(currentIndex, 1)
    nextSlots.splice(nextIndex, 0, moved)
    try {
      const updated = await withOperatorToken((token) => reorderAgentTeamSlots(
        selectedPreset.id,
        nextSlots.map((item) => item.id),
        token
      ))
      replacePreset(updated)
      toast.success('Slot reordered')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to reorder slots')
    }
  }

  const assignLeader = async (slot: AgentTeamSlot) => {
    if (!selectedPreset || !slot.enabled || selectedPreset.autonomy_enabled) return
    try {
      const updated = await withOperatorToken((token) => updateAgentTeamLeader(selectedPreset.id, {
        leader_slot_id: slot.id,
        expected_leader_slot_id: selectedPreset.leader_slot_id ?? null,
        expected_updated_at: selectedPreset.updated_at,
        reason: 'Operator selected the Leader in the team roster.',
      }, token))
      replacePreset(updated)
      toast.success('Leader assignment saved')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to assign Leader')
    }
  }

  const openPlan = async (
    slotIds: number[] | null = null,
    adoptUnbound: boolean = false,
    reuseExisting: boolean = true
  ) => {
    if (!selectedPreset) return
    const requestId = presetRequestIdRef.current
    setPlanLoading(true)
    setPlan(null)
    setLaunchResult(null)
    setPlannedSlotIds(slotIds)
    setAdoptUnboundSessions(adoptUnbound)
    setReuseExistingSessions(reuseExisting)
    try {
      const request: AgentTeamLaunchRequest = {
        slot_ids: slotIds,
        adopt_unbound_sessions: adoptUnbound,
        reuse_existing: reuseExisting,
      }
      const nextPlan = await withOperatorToken((token) => {
        if (requestId !== presetRequestIdRef.current) throw new Error('Team context changed. Review the current team again.')
        return planAgentTeamLaunch(selectedPreset.id, request, token)
      }, 'to plan a launch')
      if (requestId === presetRequestIdRef.current) setPlan(nextPlan)
    } catch (error) {
      if (requestId === presetRequestIdRef.current) toast.error(error instanceof Error ? error.message : 'Failed to plan launch')
    } finally {
      if (requestId === presetRequestIdRef.current) setPlanLoading(false)
    }
  }

  const runLaunch = async () => {
    if (!selectedPreset || !plan || plan.preset_id !== selectedPreset.id) return
    const generation = teamContextGenerationRef.current
    const targetId = selectedPreset.id
    const isCurrentTarget = () => generation === teamContextGenerationRef.current && targetId === currentTeamIdRef.current
    setLaunching(true)
    try {
      const request: AgentTeamLaunchRequest = {
        requested_by: 'deck-ui',
        slot_ids: plannedSlotIds,
        adopt_unbound_sessions: adoptUnboundSessions,
        reuse_existing: reuseExistingSessions,
        confirm_plan_hash: plan.plan_hash,
      }
      const result = await withOperatorToken((token) => {
        if (!isCurrentTarget()) throw new Error('Team context changed. Review the current team again.')
        return launchAgentTeam(targetId, request, token)
      })
      if (!isCurrentTarget()) return
      setLaunchResult(result)
      await loadPresets()
      if (isCurrentTarget()) toast.success('Launch complete')
    } catch (error) {
      if (isCurrentTarget()) toast.error(error instanceof Error ? error.message : 'Failed to launch team')
    } finally {
      if (isCurrentTarget()) setLaunching(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-bold">
            <UsersRound className="h-8 w-8" />
            Agent Teams
          </h1>
          <p className="mt-1 text-muted-foreground">
            Teams of agents that work on your repositories.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={loadPresets} disabled={loading}>
            <RefreshCw className={cn('mr-2 h-4 w-4', loading && 'animate-spin')} />
            Refresh
          </Button>
          <Button variant="outline" onClick={() => setHelpOpen(true)}>
            <BookOpen className="mr-2 h-4 w-4" />
            How it works
          </Button>
          <Button variant="outline" onClick={() => setPresetDialog('from-mail')}>
            <GitBranch className="mr-2 h-4 w-4" />
            From Mail
          </Button>
          <Button variant="outline" onClick={() => setPresetDialog('from-bridge')}>
            <MonitorPlay className="mr-2 h-4 w-4" />
            From Bridge
          </Button>
          <Button onClick={() => setPresetDialog('new')}>
            <Plus className="mr-2 h-4 w-4" />
            New team
          </Button>
        </div>
      </div>

      <div className="space-y-4">
        <nav aria-label="Saved teams" className="flex flex-wrap items-center gap-2">
          {presets.length === 0 && <span className="text-sm text-muted-foreground">No teams saved.</span>}
          {presets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => { setEditTeamOpen(false); setSelectedPresetId(preset.id); navigate(`/teams/${preset.id}`) }}
              aria-current={selectedPresetId === preset.id ? 'page' : undefined}
              title={`Updated ${formatDate(preset.updated_at)}`}
              className={cn(
                'flex items-center gap-2 rounded-full border px-3 py-1 text-sm transition-colors hover:bg-accent',
                selectedPresetId === preset.id && 'border-primary bg-accent font-medium'
              )}
            >
              {preset.name}
              <Badge variant="secondary">{preset.slots.length}</Badge>
              {preset.autonomy_enabled && <span className="text-xs text-primary">⚡ Autonomy</span>}
            </button>
          ))}
        </nav>

        <div className="min-w-0 rounded-lg border">
          {!selectedPreset ? (
            <div className="p-8 text-sm text-muted-foreground">
              {teamId ? 'This team does not exist. Select a team from the list.' : 'Select or create a team.'}
            </div>
          ) : (
            <div className="space-y-6 p-5">
              {contextParams.get('review_launch') === '1' && <section className="space-y-2 rounded border p-3"><h3 className="font-semibold">Review selected slot launch</h3><p>{selectedPreset.slots.find(slot => slot.id === requestedSlotId)?.display_name ?? 'Selected slot not found'} · slot {requestedSlotId ?? 'unknown'}. Opening this page does not launch or approve work.</p><Button className="h-auto whitespace-normal text-left" variant="outline" disabled={!selectedPreset.slots.some(slot => slot.id === requestedSlotId)} onClick={() => void openPlan(requestedSlotId ? [requestedSlotId] : null)}>Review current authenticated launch plan</Button></section>}

              <TeamHeader
                key={`header-${selectedPreset.id}`}
                preset={selectedPreset}
                onEdit={() => setEditTeamOpen(true)}
                onPlan={() => void openPlan(null)}
                planDisabled={selectedPreset.slots.every((slot) => !slot.enabled) || planLoading}
                onAutonomy={openAutonomySwitch}
              />
              <EditTeamPanel
                open={editTeamOpen}
                onOpenChange={setEditTeamOpen}
                name={name}
                onNameChange={setName}
                description={description}
                onDescriptionChange={setDescription}
                saving={saving}
                onSave={savePreset}
                onDuplicate={duplicatePreset}
                onDelete={removePreset}
              />

              <HumanActionSummary key={selectedPreset.id} presetId={selectedPreset.id} onInspectAutonomy={() => setAutonomyTab('autonomy')} />
              <Tabs value={autonomyTab} onValueChange={(value) => setAutonomyTab(value as 'roster' | 'autonomy')} className="border-t pt-5">
                <TabsList>
                  <TabsTrigger value="roster">Members</TabsTrigger>
                  <TabsTrigger value="autonomy">Autonomy</TabsTrigger>
                </TabsList>
                <TabsContent value="roster" className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="text-lg font-semibold">
                      Members <span className="text-sm font-normal text-muted-foreground">{selectedPreset.slots.length}</span>
                    </h3>
                    <Button variant="outline" onClick={() => setSlotDialog({ mode: 'add' })}>
                      <Plus className="mr-2 h-4 w-4" />
                      Add member
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    For a planner and a reviewer in the same repository, add separate members with different names. Each gets its own Agent Mail inbox.
                  </p>
                  {selectedPreset.slots.length === 0 && (
                    <div className="rounded-lg border p-5 text-sm text-muted-foreground">No members in this team.</div>
                  )}
                  <ul className="space-y-2">
                    {selectedPreset.slots.map((slot, index) => {
                      const isLeader = slot.id === autonomousLeaderSlotId(selectedPreset.leader_slot_id ?? null, selectedPreset.slots)
                      return (
                        <TeamMemberRow
                          key={slot.id}
                          slot={slot}
                          isLeader={isLeader}
                          first={index === 0}
                          last={index === selectedPreset.slots.length - 1}
                          status={agentActivity.get(slot.id)?.agent_status}
                          actions={{
                            onLaunch: () => void openPlan([slot.id]),
                            onEdit: () => setSlotDialog({ mode: 'edit', slot }),
                            onSetLeader: !isLeader && slot.enabled && !selectedPreset.autonomy_enabled ? () => void assignLeader(slot) : null,
                            onMove: (direction) => void moveSlot(slot, direction),
                            onDelete: () => void removeSlot(slot),
                          }}
                        />
                      )
                    })}
                  </ul>
                    <TeamProgress key={`progress-${selectedPreset.id}`} preset={selectedPreset} />
                    <details className="rounded-lg border">
                      <summary className="cursor-pointer px-4 py-2 text-sm font-medium">Team status</summary>
                      <div className="p-3">
                        <TeamSummaryCard
                          key={`summary-${selectedPreset.id}`}
                          presetId={selectedPreset.id}
                          slotNames={Object.fromEntries(selectedPreset.slots.map((slot) => [slot.id, slot.display_name]))}
                        />
                      </div>
                    </details>
                </TabsContent>
                <TabsContent value="autonomy" className="mt-5">
                  <AutonomyPanel
                    key={selectedPreset.id}
                    preset={selectedPreset}
                    scopes={autonomyDataPresetId === selectedPreset.id ? githubScopes : []}
                    workItems={autonomyDataPresetId === selectedPreset.id ? githubWorkItems : []}
                    loading={autonomyLoading || autonomyDataPresetId !== selectedPreset.id}
                    refreshing={autonomyDataPresetId === selectedPreset.id && autonomyRefreshing}
                    lastRefreshedAt={autonomyDataPresetId === selectedPreset.id ? autonomyLastRefreshedAt : null}
                    loadError={autonomyDataPresetId === selectedPreset.id ? autonomyLoadError : null}
                    onRefresh={refreshAutonomy}
                    onToggleAutonomy={toggleAutonomy}
                  />
                </TabsContent>
              </Tabs>
            </div>
          )}
        </div>
      </div>

      <NewPresetDialog mode={presetDialog} onOpenChange={setPresetDialog} onCreate={createPreset} />
      <SlotDialog
        state={slotDialog}
        onOpenChange={setSlotDialog}
        onSave={saveSlot}
        launchOptionsByProvider={launchOptionsByProvider}
      />
      <AgentTeamsHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
      <OperatorTokenDialog
        open={tokenDialogOpen}
        value={tokenInput}
        error={tokenError}
        reason={tokenReason}
        onValueChange={setTokenInput}
        onSubmit={() => {
          const token = tokenInput.trim()
          if (!token) return
          setOperatorToken(token)
          settleOperatorToken(token)
        }}
        onCancel={() => settleOperatorToken(null)}
      />
      {!tokenDialogOpen && (
        <LaunchPlanDialog
          plan={plan?.preset_id === selectedPreset?.id ? plan : null}
          result={launchResult?.preset_id === selectedPreset?.id ? launchResult : null}
          loading={planLoading}
          launching={launching}
          onOpenChange={(open) => {
            if (!open) {
              setPlan(null)
              setLaunchResult(null)
              setPlanLoading(false)
            }
          }}
          onLaunch={runLaunch}
          onReviewAdoption={() => openPlan(plannedSlotIds, true)}
          onReviewFreshSpawn={() => openPlan(plannedSlotIds, false, false)}
        />
      )}
    </div>
  )
}
