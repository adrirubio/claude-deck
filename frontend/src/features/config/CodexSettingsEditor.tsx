import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { HelpCircle, Plus, RotateCcw, Save } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { updateCodexConfig } from '@/hooks/useProviders'
import type {
  CodexConfigResponse,
  CodexConfigUpdateRequest,
  CodexFeatureInventoryResponse,
  CodexFeatureInventoryRow,
} from '@/types/providers'

interface CodexSettingsEditorProps {
  config: CodexConfigResponse | null
  featureInventory: CodexFeatureInventoryResponse | null
  featureInventoryError: string | null
  onSaved: () => Promise<void> | void
}

const FEATURE_NAME_PATTERN = /^[A-Za-z0-9_-]+$/
const DEFAULT_SELECT_VALUE = '__default__'
const REASONING_EFFORT_OPTIONS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'xhigh', label: 'Extra High' },
]
const SANDBOX_MODE_OPTIONS = [
  { value: 'read-only', label: 'Read Only' },
  { value: 'workspace-write', label: 'Workspace Write' },
  { value: 'danger-full-access', label: 'Danger Full Access' },
]
const APPROVAL_POLICY_OPTIONS = [
  { value: 'untrusted', label: 'Untrusted' },
  { value: 'on-request', label: 'On Request' },
  { value: 'never', label: 'Never' },
  { value: 'on-failure', label: 'On Failure (deprecated)' },
]
const SETTING_HELP = {
  model: 'Model the agent should use. This is open-ended; enter any Codex-supported model id.',
  reasoning: 'Controls reasoning depth for models that support it.',
  profile: 'Layers a named Codex profile config on top of the base user config.',
  sandboxMode: 'Sandbox policy for filesystem and network access during command execution.',
  approvalPolicy: 'Controls when Codex requires human approval before executing a command.',
  search: 'Enables live web search. Codex can use the native web search tool without per-call approval.',
  strictConfig: 'Errors out when config.toml contains fields this Codex version does not recognize.',
  noAltScreen: 'Runs the TUI inline instead of in an alternate screen, preserving terminal scrollback history.',
} satisfies Record<string, string>
const FEATURE_HELP: Record<string, string> = {
  apps: 'Enable ChatGPT Apps/connectors support.',
  enable_request_compression: 'Compress streaming request bodies with zstd when supported.',
  fast_mode: 'Enable model-catalog service tier selection in the TUI, including Fast-tier commands when the active model advertises them.',
  goals: 'Enable persistent objectives that keep a Codex thread working toward a defined outcome across turns.',
  hooks: 'Enable lifecycle hooks loaded from hooks.json or inline hooks config.',
  memories: 'Enable Codex Memories.',
  multi_agent: 'Enable multi-agent collaboration tools such as spawn_agent, send_input, resume_agent, wait_agent, and close_agent.',
  network_proxy: 'Enable sandboxed networking. Table-form config can set network policy options such as allowed domains.',
  personality: 'Enable personality selection controls.',
  prevent_idle_sleep: 'Prevent the machine from sleeping while a turn is actively running.',
  shell_snapshot: 'Snapshot the shell environment to speed up repeated commands.',
  shell_tool: 'Enable the default shell tool for running commands.',
  skill_mcp_dependency_install: 'Allow prompting and installing missing MCP dependencies for skills.',
  undo: 'Enable undo support.',
  unified_exec: 'Use the unified PTY-backed exec tool.',
}
const FEATURE_ORDER = [
  'goals',
  'memories',
  'hooks',
  'multi_agent',
  'fast_mode',
  'undo',
  'prevent_idle_sleep',
  'network_proxy',
  'shell_tool',
  'shell_snapshot',
  'personality',
  'unified_exec',
]

function optionalString(value: string): string | null {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function optionalBoolean(current: boolean, original: boolean | undefined): boolean | null {
  if (original !== undefined || current === true) return current
  return null
}

function booleanFeatureOverrides(features: Record<string, unknown> | undefined): Record<string, boolean> {
  if (!features) return {}
  return Object.fromEntries(
    Object.entries(features).filter((entry): entry is [string, boolean] => typeof entry[1] === 'boolean'),
  )
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.map((value) => value?.trim()).filter((value): value is string => Boolean(value))))
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim().length > 0 ? value : undefined
}

function withCurrentOption(
  options: { value: string; label: string }[],
  current: string,
): { value: string; label: string }[] {
  if (!current || options.some((option) => option.value === current)) return options
  return [...options, { value: current, label: `${current} (custom)` }]
}

function formatKnownValues(values: string[], emptyMessage: string): string {
  if (values.length === 0) return emptyMessage
  return `Known in this config: ${values.join(', ')}.`
}

function featureHelp(feature: CodexFeatureInventoryRow): string {
  return FEATURE_HELP[feature.name]
    ?? (
      `No official description found. Codex reports this flag as ${feature.stage || 'unknown stage'} `
      + `and currently ${feature.enabled ? 'enabled' : 'disabled'}.`
    )
}

function HelpIcon({ text }: { text: string }) {
  return (
    <span
      className="inline-flex cursor-help text-muted-foreground"
      title={text}
      aria-label={text}
      tabIndex={0}
    >
      <HelpCircle className="h-3.5 w-3.5" />
    </span>
  )
}

function LabelWithHelp({
  htmlFor,
  children,
  help,
  className,
}: {
  htmlFor?: string
  children: ReactNode
  help?: string
  className?: string
}) {
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Label htmlFor={htmlFor} className={className}>
        {children}
      </Label>
      {help && <HelpIcon text={help} />}
    </div>
  )
}

function Field({
  id,
  label,
  value,
  placeholder,
  onChange,
  description,
  help,
}: {
  id: string
  label: string
  value: string
  placeholder?: string
  onChange: (value: string) => void
  description?: string
  help?: string
}) {
  return (
    <div className="space-y-1.5">
      <LabelWithHelp htmlFor={id} help={help}>
        {label}
      </LabelWithHelp>
      <Input
        id={id}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      {description && <p className="text-xs text-muted-foreground">{description}</p>}
    </div>
  )
}

function SelectField({
  id,
  label,
  value,
  options,
  onChange,
  help,
}: {
  id: string
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
  help?: string
}) {
  return (
    <div className="space-y-1.5">
      <LabelWithHelp htmlFor={id} help={help}>
        {label}
      </LabelWithHelp>
      <Select
        value={value || DEFAULT_SELECT_VALUE}
        onValueChange={(nextValue) => onChange(nextValue === DEFAULT_SELECT_VALUE ? '' : nextValue)}
      >
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={DEFAULT_SELECT_VALUE}>Default</SelectItem>
          {withCurrentOption(options, value).map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function ToggleRow({
  id,
  label,
  checked,
  onChange,
  trailing,
  help,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  trailing?: ReactNode
  help?: string
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
      <LabelWithHelp htmlFor={id} help={help} className="text-sm font-medium">
        {label}
      </LabelWithHelp>
      <div className="flex items-center gap-2">
        {trailing}
        <Switch id={id} checked={checked} onCheckedChange={onChange} />
      </div>
    </div>
  )
}

function FeatureToggleRow({
  feature,
  checked,
  explicit,
  onChange,
  onReset,
  help,
}: {
  feature: CodexFeatureInventoryRow
  checked: boolean
  explicit: boolean
  onChange: (checked: boolean) => void
  onReset: () => void
  help: string
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
      <div className="min-w-0">
        <LabelWithHelp htmlFor={`codex-feature-${feature.name}`} help={help} className="block truncate text-sm font-medium">
          {feature.name}
        </LabelWithHelp>
        <div className="mt-1 flex flex-wrap gap-1.5">
          <Badge variant="outline" className="text-xs">
            {feature.stage || 'unknown'}
          </Badge>
          {explicit && (
            <Badge variant="secondary" className="text-xs">
              configured
            </Badge>
          )}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {explicit && (
          <Button type="button" variant="ghost" size="icon" onClick={onReset} title="Use Codex default">
            <RotateCcw className="h-4 w-4" />
          </Button>
        )}
        <Switch id={`codex-feature-${feature.name}`} checked={checked} onCheckedChange={onChange} />
      </div>
    </div>
  )
}

function sortFeatures(features: CodexFeatureInventoryRow[]): CodexFeatureInventoryRow[] {
  const rank = new Map(FEATURE_ORDER.map((name, index) => [name, index]))
  return [...features].sort((a, b) => {
    const aRank = rank.get(a.name) ?? Number.MAX_SAFE_INTEGER
    const bRank = rank.get(b.name) ?? Number.MAX_SAFE_INTEGER
    if (aRank !== bRank) return aRank - bRank
    return a.name.localeCompare(b.name)
  })
}

function isVisibleKnownFeature(feature: CodexFeatureInventoryRow): boolean {
  return !['removed', 'deprecated'].includes(feature.stage)
}

export function CodexSettingsEditor({
  config,
  featureInventory,
  featureInventoryError,
  onSaved,
}: CodexSettingsEditorProps) {
  const summary = config?.summary
  const initialFeatures = useMemo(() => booleanFeatureOverrides(summary?.features), [summary?.features])
  const knownFeatures = useMemo(
    () => sortFeatures((featureInventory?.features ?? []).filter(isVisibleKnownFeature)),
    [featureInventory?.features],
  )
  const knownFeatureNames = useMemo(
    () => new Set(knownFeatures.map((feature) => feature.name)),
    [knownFeatures],
  )
  const [model, setModel] = useState(summary?.model ?? '')
  const [reasoning, setReasoning] = useState(summary?.model_reasoning_effort ?? '')
  const [profile, setProfile] = useState(summary?.profile ?? '')
  const [sandboxMode, setSandboxMode] = useState(summary?.sandbox_mode ?? '')
  const [approvalPolicy, setApprovalPolicy] = useState(summary?.approval_policy ?? '')
  const [search, setSearch] = useState(summary?.search ?? false)
  const [strictConfig, setStrictConfig] = useState(summary?.strict_config ?? false)
  const [noAltScreen, setNoAltScreen] = useState(summary?.no_alt_screen ?? false)
  const [features, setFeatures] = useState<Record<string, boolean>>(initialFeatures)
  const [deletedFeatures, setDeletedFeatures] = useState<Set<string>>(() => new Set())
  const [newFeature, setNewFeature] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const knownModels = uniqueStrings([
    summary?.model,
    stringValue(config?.profile_resolution?.base_summary.model),
    stringValue(config?.profile_resolution?.effective_summary.model),
    ...(config?.profile_resolution?.profiles ?? []).map((profile) => stringValue(profile.summary.model)),
  ])
  const knownProfiles = uniqueStrings([
    summary?.profile,
    summary?.profile_v2,
    ...Object.keys(summary?.profiles ?? {}),
    ...(config?.profile_resolution?.profiles ?? []).map((profile) => profile.name),
  ])
  const featureEntries = Object.entries(features).sort(([a], [b]) => a.localeCompare(b))
  const unknownFeatureEntries = featureEntries.filter(([name]) => !knownFeatureNames.has(name))
  const canAddFeature = FEATURE_NAME_PATTERN.test(newFeature.trim()) && !(newFeature.trim() in features)

  function setFeature(name: string, value: boolean) {
    setFeatures((current) => ({ ...current, [name]: value }))
    setDeletedFeatures((current) => {
      if (!current.has(name)) return current
      const next = new Set(current)
      next.delete(name)
      return next
    })
  }

  function resetFeature(name: string) {
    setFeatures((current) => {
      const next = { ...current }
      delete next[name]
      return next
    })
    setDeletedFeatures((current) => {
      if (!(name in initialFeatures)) return current
      const next = new Set(current)
      next.add(name)
      return next
    })
  }

  function addFeature() {
    const name = newFeature.trim()
    if (!FEATURE_NAME_PATTERN.test(name)) {
      toast.error('Feature names can only contain letters, numbers, underscores, and hyphens')
      return
    }
    if (name in features) {
      toast.error(`Feature "${name}" already exists`)
      return
    }
    setFeatures((current) => ({ ...current, [name]: true }))
    setDeletedFeatures((current) => {
      if (!current.has(name)) return current
      const next = new Set(current)
      next.delete(name)
      return next
    })
    setNewFeature('')
  }

  async function handleSave() {
    setSubmitting(true)
    try {
      const featureUpdates: Record<string, boolean | null> = { ...features }
      deletedFeatures.forEach((name) => {
        featureUpdates[name] = null
      })
      const request: CodexConfigUpdateRequest = {
        settings: {
          model: optionalString(model),
          model_reasoning_effort: optionalString(reasoning),
          profile: optionalString(profile),
          sandbox_mode: optionalString(sandboxMode),
          approval_policy: optionalString(approvalPolicy),
          search: optionalBoolean(search, summary?.search),
          strict_config: optionalBoolean(strictConfig, summary?.strict_config),
          no_alt_screen: optionalBoolean(noAltScreen, summary?.no_alt_screen),
        },
        features: featureUpdates,
      }
      await updateCodexConfig(request)
      toast.success('Codex config saved')
      await onSaved()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save Codex config')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      {config?.parse_error && (
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-sm text-destructive">{config.parse_error}</p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>General</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Field
              id="codex-model"
              label="Model"
              value={model}
              placeholder="default"
              onChange={setModel}
              help={SETTING_HELP.model}
              description={`${formatKnownValues(knownModels, 'No model ids detected in this config.')} You can enter any Codex-supported model id.`}
            />
            <SelectField
              id="codex-reasoning"
              label="Reasoning Effort"
              value={reasoning}
              options={REASONING_EFFORT_OPTIONS}
              onChange={setReasoning}
              help={SETTING_HELP.reasoning}
            />
            <Field
              id="codex-profile"
              label="Profile"
              value={profile}
              placeholder="default"
              onChange={setProfile}
              help={SETTING_HELP.profile}
              description={`${formatKnownValues(knownProfiles, 'No named profiles detected in this config.')} You can enter any Codex profile name.`}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Runtime</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <SelectField
              id="codex-sandbox"
              label="Sandbox Mode"
              value={sandboxMode}
              options={SANDBOX_MODE_OPTIONS}
              onChange={setSandboxMode}
              help={SETTING_HELP.sandboxMode}
            />
            <SelectField
              id="codex-approval"
              label="Approval Policy"
              value={approvalPolicy}
              options={APPROVAL_POLICY_OPTIONS}
              onChange={setApprovalPolicy}
              help={SETTING_HELP.approvalPolicy}
            />
            <ToggleRow
              id="codex-search"
              label="Search"
              checked={search}
              onChange={setSearch}
              help={SETTING_HELP.search}
            />
            <ToggleRow
              id="codex-strict-config"
              label="Strict Config"
              checked={strictConfig}
              onChange={setStrictConfig}
              help={SETTING_HELP.strictConfig}
            />
            <ToggleRow
              id="codex-no-alt-screen"
              label="No Alt Screen"
              checked={noAltScreen}
              onChange={setNoAltScreen}
              help={SETTING_HELP.noAltScreen}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Features</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {featureInventoryError && (
              <p className="rounded-md border border-destructive/50 p-3 text-sm text-destructive">
                {featureInventoryError}
              </p>
            )}
            <div className="flex gap-2">
              <Input
                value={newFeature}
                placeholder="feature_name"
                onChange={(event) => setNewFeature(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    addFeature()
                  }
                }}
              />
              <Button type="button" variant="outline" size="icon" onClick={addFeature} disabled={!canAddFeature}>
                <Plus className="h-4 w-4" />
              </Button>
            </div>
            <div className="max-h-72 space-y-2 overflow-auto pr-1">
              {knownFeatures.map((feature) => {
                const explicit = feature.name in features
                return (
                  <FeatureToggleRow
                    key={feature.name}
                    feature={feature}
                    checked={features[feature.name] ?? feature.enabled}
                    explicit={explicit}
                    onChange={(checked) => setFeature(feature.name, checked)}
                    onReset={() => resetFeature(feature.name)}
                    help={featureHelp(feature)}
                  />
                )
              })}
              {unknownFeatureEntries.length === 0 && knownFeatures.length === 0 ? (
                <p className="rounded-md border p-3 text-sm text-muted-foreground">No feature flags configured.</p>
              ) : (
                unknownFeatureEntries.map(([name, enabled]) => (
                  <ToggleRow
                    key={name}
                    id={`codex-feature-${name}`}
                    label={name}
                    checked={enabled}
                    onChange={(checked) => setFeature(name, checked)}
                    help="This feature flag is configured in config.toml but is not present in the active Codex feature inventory."
                    trailing={
                      <Button type="button" variant="ghost" size="icon" onClick={() => resetFeature(name)} title="Use Codex default">
                        <RotateCcw className="h-4 w-4" />
                      </Button>
                    }
                  />
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={submitting || Boolean(config?.parse_error)} className="gap-2">
          <Save className="h-4 w-4" />
          {submitting ? 'Saving...' : 'Save Codex Config'}
        </Button>
      </div>
    </div>
  )
}
