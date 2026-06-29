import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  ChevronDown,
  Copy,
  Edit,
  GitBranch,
  MonitorPlay,
  Plus,
  Play,
  RefreshCw,
  Rocket,
  Save,
  Trash2,
  UsersRound,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Textarea } from '@/components/ui/textarea'
import { TEAM_SLOT_COLOR_OPTIONS, getTeamSlotColorClasses } from '@/lib/agentTeamColors'
import { cn } from '@/lib/utils'
import type {
  AgentTeamLaunchPlan,
  AgentTeamLaunchPlanItem,
  AgentTeamLaunchRequest,
  AgentTeamLaunchResult,
  AgentTeamPreset,
  AgentTeamSlot,
  AgentTeamSlotInput,
  SlotLaunchOptions,
} from '@/types/agentTeams'
import type { AgentProviderId, ProviderLaunchOptionsResponse } from '@/types/providers'
import {
  addAgentTeamSlot,
  createAgentTeamFromBridge,
  createAgentTeamFromMail,
  createAgentTeamPreset,
  deleteAgentTeamPreset,
  deleteAgentTeamSlot,
  duplicateAgentTeamPreset,
  fetchAgentTeamPresets,
  launchAgentTeam,
  planAgentTeamLaunch,
  reorderAgentTeamSlots,
  updateAgentTeamPreset,
  updateAgentTeamSlot,
} from './api'
import { fetchAgentMailTeam } from '@/features/agent-mail/api'
import { fetchProviderLaunchOptions } from '@/hooks/useProviders'
import type { MailMemberResponse } from '@/types/agentMail'
import { AgentTeamsHelpDialog } from './AgentTeamsHelpDialog'
import { ProviderLaunchOptionsFields } from '@/features/providers/ProviderLaunchOptionsFields'

type PresetDialogState = 'new' | 'from-mail' | 'from-bridge' | null
type SlotDialogState = { mode: 'add' | 'edit'; slot?: AgentTeamSlot } | null
type LaunchOptionsByProvider = Partial<Record<AgentProviderId, ProviderLaunchOptionsResponse>>

const PROVIDER_IDS: AgentProviderId[] = ['codex-cli', 'claude-code', 'copilot-cli', 'opencode-cli']
const DEFAULT_SLOT_COLOR_VALUE = 'default'

const emptySlot: AgentTeamSlotInput = {
  display_name: '',
  provider: 'codex-cli',
  repo_path: '',
  role: '',
  charter: '',
  ui_color: '',
  bootstrap_prompt: '',
  launch_mode: 'plain',
  launch_options: {},
  enabled: true,
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function actionBadgeClass(action: AgentTeamLaunchPlanItem['action']) {
  if (action === 'spawn') return 'border-emerald-500/70 text-emerald-400'
  if (action === 'reuse') return 'border-sky-500/70 text-sky-400'
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
    launch_mode: slot.launch_mode,
    launch_options: slot.launch_options ?? {},
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
  }) => Promise<void>
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [includeOffline, setIncludeOffline] = useState(true)
  const [mailMembers, setMailMembers] = useState<MailMemberResponse[]>([])
  const [selectedMemberIds, setSelectedMemberIds] = useState<number[]>([])
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
        setIncludeOffline(true)
        setMailMembers([])
        setSelectedMemberIds([])
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
        const preferred = members.filter((member) => member.status !== 'offline')
        setMailMembers(members)
        setSelectedMemberIds((preferred.length ? preferred : members).map((member) => member.id))
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
        includeOffline,
        memberIds: mode === 'from-mail' ? selectedMemberIds : undefined,
      })
      onOpenChange(null)
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
                  checked={includeOffline}
                  onCheckedChange={(checked) => {
                    const next = checked === true
                    setIncludeOffline(next)
                    if (!next) {
                      setSelectedMemberIds((current) =>
                        current.filter((memberId) =>
                          mailMembers.some((member) => member.id === memberId && member.status !== 'offline')
                        )
                      )
                    }
                  }}
                />
                Include offline members
              </label>
              <div className="max-h-56 overflow-y-auto rounded-md border p-2">
                {loadingMembers && (
                  <div className="p-3 text-sm text-muted-foreground">Loading members...</div>
                )}
                {!loadingMembers && mailMembers.length === 0 && (
                  <div className="p-3 text-sm text-muted-foreground">No Agent Mail members found.</div>
                )}
                {!loadingMembers && mailMembers.map((member) => {
                  const disabled = !includeOffline && member.status === 'offline'
                  return (
                    <label
                      key={member.id}
                      className={cn(
                        'flex items-center gap-3 rounded-md px-2 py-2 text-sm',
                        disabled && 'text-muted-foreground'
                      )}
                    >
                      <Checkbox
                        checked={selectedMemberIds.includes(member.id)}
                        disabled={disabled}
                        onCheckedChange={(checked) => {
                          setSelectedMemberIds((current) => {
                            if (checked === true) return [...new Set([...current, member.id])]
                            return current.filter((memberId) => memberId !== member.id)
                          })
                        }}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{member.display_name}</span>
                        <span className="block truncate text-xs text-muted-foreground">{member.repo_path}</span>
                      </span>
                      <Badge variant={member.status === 'offline' ? 'secondary' : 'outline'}>
                        {member.status}
                      </Badge>
                    </label>
                  )
                })}
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(null)}>Cancel</Button>
          <Button
            onClick={submit}
            disabled={saving || !name.trim() || (mode === 'from-mail' && selectedMemberIds.length === 0)}
          >
            {saving ? 'Creating' : 'Create'}
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
      <DialogContent className="max-w-3xl">
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
              onValueChange={(provider) => update({
                provider,
                launch_mode: normalizeModeForProvider(provider, form.launch_mode, launchOptionsByProvider),
              })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="codex-cli">Codex CLI</SelectItem>
                <SelectItem value="claude-code">Claude Code</SelectItem>
                <SelectItem value="copilot-cli">GitHub Copilot CLI</SelectItem>
                <SelectItem value="opencode-cli">OpenCode CLI</SelectItem>
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
}: {
  plan: AgentTeamLaunchPlan | null
  result: AgentTeamLaunchResult | null
  loading: boolean
  launching: boolean
  onOpenChange: (open: boolean) => void
  onLaunch: () => Promise<void>
}) {
  const open = Boolean(plan || loading || result)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>Launch Plan</DialogTitle>
          {plan && (
            <DialogDescription>
              {plan.reuse_count} reuse, {plan.spawn_count} spawn, {plan.skipped_count} skipped, {plan.blocked_count} blocked
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
                {item.warnings && item.warnings.length > 0 && (
                  <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-sm text-amber-300">
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
                </div>
                <Badge variant={item.status === 'failed' ? 'destructive' : 'outline'}>
                  {item.status}
                </Badge>
              </div>
            ))}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          {plan && (
            <Button onClick={onLaunch} disabled={launching || !plan.can_launch || plan.spawn_count + plan.reuse_count === 0}>
              <Rocket className="mr-2 h-4 w-4" />
              {launching ? 'Launching' : 'Launch'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function AgentTeamsPage() {
  const [presets, setPresets] = useState<AgentTeamPreset[]>([])
  const [selectedPresetId, setSelectedPresetId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [presetDialog, setPresetDialog] = useState<PresetDialogState>(null)
  const [slotDialog, setSlotDialog] = useState<SlotDialogState>(null)
  const [plan, setPlan] = useState<AgentTeamLaunchPlan | null>(null)
  const [launchResult, setLaunchResult] = useState<AgentTeamLaunchResult | null>(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [plannedSlotIds, setPlannedSlotIds] = useState<number[] | null>(null)
  const [helpOpen, setHelpOpen] = useState(false)
  const [launchOptionsByProvider, setLaunchOptionsByProvider] = useState<LaunchOptionsByProvider>({})

  const selectedPreset = useMemo(
    () => presets.find((preset) => preset.id === selectedPresetId),
    [presets, selectedPresetId]
  )
  const { name, setName, description, setDescription } = usePresetForm(selectedPreset)

  const loadPresets = useCallback(async () => {
    setLoading(true)
    try {
      const response = await fetchAgentTeamPresets()
      setPresets(response.presets)
      setSelectedPresetId((current) => {
        if (current && response.presets.some((preset) => preset.id === current)) return current
        return response.presets[0]?.id ?? null
      })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to load Agent Teams')
    } finally {
      setLoading(false)
    }
  }, [])

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

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) {
        void loadPresets()
        void loadProviderLaunchOptions()
      }
    })
    return () => {
      cancelled = true
    }
  }, [loadPresets, loadProviderLaunchOptions])

  const stats = useMemo(() => {
    const slots = presets.reduce((count, preset) => count + preset.slots.length, 0)
    const enabled = presets.reduce(
      (count, preset) => count + preset.slots.filter((slot) => slot.enabled).length,
      0
    )
    return { slots, enabled }
  }, [presets])

  const replacePreset = (preset: AgentTeamPreset) => {
    setPresets((current) => current.map((item) => (item.id === preset.id ? preset : item)))
    setSelectedPresetId(preset.id)
  }

  const savePreset = async () => {
    if (!selectedPreset) return
    setSaving(true)
    try {
      const updated = await updateAgentTeamPreset(selectedPreset.id, {
        name,
        description,
      })
      replacePreset(updated)
      toast.success('Team saved')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save team')
    } finally {
      setSaving(false)
    }
  }

  const createPreset = async (input: {
    name: string
    description: string
    includeOffline?: boolean
    memberIds?: number[]
  }) => {
    try {
      const created = presetDialog === 'from-mail'
        ? await createAgentTeamFromMail({
          name: input.name,
          description: input.description,
          member_ids: input.memberIds,
          include_offline: input.includeOffline,
        })
        : presetDialog === 'from-bridge'
          ? await createAgentTeamFromBridge({
            name: input.name,
            description: input.description,
          })
          : await createAgentTeamPreset({
            name: input.name,
            description: input.description,
            created_by: 'deck-ui',
            slots: [],
          })
      setPresets((current) => [created, ...current])
      setSelectedPresetId(created.id)
      toast.success('Team created')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to create team')
      throw error
    }
  }

  const duplicatePreset = async () => {
    if (!selectedPreset) return
    try {
      const created = await duplicateAgentTeamPreset(selectedPreset.id, {
        name: `${selectedPreset.name} copy`,
      })
      setPresets((current) => [created, ...current])
      setSelectedPresetId(created.id)
      toast.success('Team duplicated')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to duplicate team')
    }
  }

  const removePreset = async () => {
    if (!selectedPreset) return
    try {
      await deleteAgentTeamPreset(selectedPreset.id)
      setPresets((current) => current.filter((preset) => preset.id !== selectedPreset.id))
      setSelectedPresetId((current) => {
        const remaining = presets.filter((preset) => preset.id !== current)
        return remaining[0]?.id ?? null
      })
      toast.success('Team deleted')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to delete team')
    }
  }

  const saveSlot = async (input: AgentTeamSlotInput) => {
    if (!selectedPreset || !slotDialog) return
    const normalizedInput = {
      ...input,
      position: input.position ?? undefined,
    }
    const saved = slotDialog.mode === 'edit' && slotDialog.slot
      ? await updateAgentTeamSlot(slotDialog.slot.id, normalizedInput)
      : await addAgentTeamSlot(selectedPreset.id, normalizedInput)
    replacePreset(saved)
    toast.success('Slot saved')
  }

  const removeSlot = async (slot: AgentTeamSlot) => {
    try {
      const updated = await deleteAgentTeamSlot(slot.id)
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
      const updated = await reorderAgentTeamSlots(
        selectedPreset.id,
        nextSlots.map((item) => item.id)
      )
      replacePreset(updated)
      toast.success('Slot reordered')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to reorder slots')
    }
  }

  const openPlan = async (slotIds: number[] | null = null) => {
    if (!selectedPreset) return
    setPlanLoading(true)
    setPlan(null)
    setLaunchResult(null)
    setPlannedSlotIds(slotIds)
    try {
      const request: AgentTeamLaunchRequest = slotIds ? { slot_ids: slotIds } : {}
      setPlan(await planAgentTeamLaunch(selectedPreset.id, request))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to plan launch')
    } finally {
      setPlanLoading(false)
    }
  }

  const runLaunch = async () => {
    if (!selectedPreset || !plan) return
    setLaunching(true)
    try {
      const request: AgentTeamLaunchRequest = {
        requested_by: 'deck-ui',
        slot_ids: plannedSlotIds,
        confirm_plan_hash: plan.plan_hash,
      }
      const result = await launchAgentTeam(selectedPreset.id, request)
      setLaunchResult(result)
      await loadPresets()
      toast.success('Launch complete')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to launch team')
    } finally {
      setLaunching(false)
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
            Saved agent rosters with launch plans for local Claude Code, Codex, and Copilot sessions.
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

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Teams</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{presets.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Slots</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{stats.slots}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Enabled</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{stats.enabled}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <div className="rounded-lg border">
          <div className="border-b p-3 text-sm font-medium">Saved Teams</div>
          <div className="max-h-[620px] overflow-y-auto p-2">
            {presets.length === 0 && (
              <div className="p-4 text-sm text-muted-foreground">No teams saved.</div>
            )}
            {presets.map((preset) => (
              <button
                key={preset.id}
                type="button"
                onClick={() => setSelectedPresetId(preset.id)}
                className={cn(
                  'mb-2 w-full rounded-md border p-3 text-left transition-colors hover:bg-accent',
                  selectedPresetId === preset.id && 'border-primary bg-accent'
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium">{preset.name}</p>
                  <Badge variant="secondary">{preset.slots.length}</Badge>
                </div>
                <p className="mt-1 truncate text-xs text-muted-foreground">
                  Updated {formatDate(preset.updated_at)}
                </p>
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-lg border">
          {!selectedPreset ? (
            <div className="p-8 text-sm text-muted-foreground">
              Select or create a team.
            </div>
          ) : (
            <div className="space-y-6 p-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                <div className="grid flex-1 gap-3">
                  <div className="grid gap-2">
                    <Label htmlFor="preset-name">Name</Label>
                    <Input id="preset-name" value={name} onChange={(event) => setName(event.target.value)} />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="preset-description">Description</Label>
                    <Textarea
                      id="preset-description"
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                    />
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" onClick={savePreset} disabled={saving || !name.trim()}>
                    <Save className="mr-2 h-4 w-4" />
                    Save
                  </Button>
                  <Button variant="outline" onClick={duplicatePreset}>
                    <Copy className="mr-2 h-4 w-4" />
                    Duplicate
                  </Button>
                  <Button variant="destructive" onClick={removePreset}>
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </Button>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-5">
                <div>
                  <h2 className="text-lg font-semibold">Roster</h2>
                  <p className="text-sm text-muted-foreground">{selectedPreset.slots.length} slots</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" onClick={() => setSlotDialog({ mode: 'add' })}>
                    <Plus className="mr-2 h-4 w-4" />
                    Add slot
                  </Button>
                  <Button
                    onClick={() => openPlan(null)}
                    disabled={selectedPreset.slots.every((slot) => !slot.enabled) || planLoading}
                  >
                    <Play className="mr-2 h-4 w-4" />
                    Plan launch
                  </Button>
                </div>
              </div>

              <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 text-sm text-muted-foreground">
                <p>
                  For same-repo planner/reviewer workflows, create separate slots with distinct
                  names and launch them from this team. That gives Agent Mail separate inboxes and
                  reliable routing for each role.
                </p>
              </div>

              <div className="space-y-3">
                {selectedPreset.slots.length === 0 && (
                  <div className="rounded-lg border p-5 text-sm text-muted-foreground">
                    No slots in this team.
                  </div>
                )}
                {selectedPreset.slots.map((slot, index) => {
                  const colorClasses = getTeamSlotColorClasses(slot.ui_color)
                  return (
                    <div key={slot.id} className={cn('rounded-lg border p-4', colorClasses.card)}>
                      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="font-semibold">{slot.display_name}</p>
                            <Badge variant={slot.enabled ? 'outline' : 'secondary'}>
                              {slot.enabled ? 'Enabled' : 'Disabled'}
                            </Badge>
                            <Badge variant="secondary">{slot.provider}</Badge>
                            <Badge variant="secondary">{slot.launch_mode}</Badge>
                            {slot.ui_color && (
                              <Badge variant="outline" className={colorClasses.badge}>
                                {slot.ui_color}
                              </Badge>
                            )}
                          </div>
                          <p className="mt-1 truncate text-sm text-muted-foreground">{slot.repo_path}</p>
                          <div className="mt-3 grid gap-3 text-sm md:grid-cols-2">
                            <div>
                              <p className="text-xs uppercase text-muted-foreground">Repo</p>
                              <p>{slot.repo_name}</p>
                            </div>
                            <div>
                              <p className="text-xs uppercase text-muted-foreground">Role</p>
                              <p>{slot.role || 'Unassigned'}</p>
                            </div>
                          </div>
                          {slot.warnings && slot.warnings.length > 0 && (
                            <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-sm text-amber-300">
                              {slot.warnings.join('; ')}
                            </div>
                          )}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => moveSlot(slot, -1)}
                            disabled={index === 0}
                          >
                            <ArrowUp className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => moveSlot(slot, 1)}
                            disabled={index === selectedPreset.slots.length - 1}
                          >
                            <ArrowDown className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => openPlan([slot.id])}
                            disabled={!slot.enabled}
                          >
                            <Play className="mr-2 h-4 w-4" />
                            Launch
                          </Button>
                          <Button variant="outline" size="sm" onClick={() => setSlotDialog({ mode: 'edit', slot })}>
                            <Edit className="mr-2 h-4 w-4" />
                            Edit
                          </Button>
                          <Button variant="outline" size="sm" onClick={() => removeSlot(slot)}>
                            <Trash2 className="mr-2 h-4 w-4" />
                            Delete
                          </Button>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
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
      <LaunchPlanDialog
        plan={plan}
        result={launchResult}
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
      />
    </div>
  )
}
