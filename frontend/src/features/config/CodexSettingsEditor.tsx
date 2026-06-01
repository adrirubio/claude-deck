import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Plus, RotateCcw, Save } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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

function Field({
  id,
  label,
  value,
  placeholder,
  onChange,
}: {
  id: string
  label: string
  value: string
  placeholder?: string
  onChange: (value: string) => void
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}

function ToggleRow({
  id,
  label,
  checked,
  onChange,
  trailing,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  trailing?: ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
      <Label htmlFor={id} className="text-sm font-medium">
        {label}
      </Label>
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
}: {
  feature: CodexFeatureInventoryRow
  checked: boolean
  explicit: boolean
  onChange: (checked: boolean) => void
  onReset: () => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
      <div className="min-w-0">
        <Label htmlFor={`codex-feature-${feature.name}`} className="block truncate text-sm font-medium">
          {feature.name}
        </Label>
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
            <Field id="codex-model" label="Model" value={model} placeholder="default" onChange={setModel} />
            <Field
              id="codex-reasoning"
              label="Reasoning Effort"
              value={reasoning}
              placeholder="default"
              onChange={setReasoning}
            />
            <Field id="codex-profile" label="Profile" value={profile} placeholder="default" onChange={setProfile} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Runtime</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Field
              id="codex-sandbox"
              label="Sandbox Mode"
              value={sandboxMode}
              placeholder="default"
              onChange={setSandboxMode}
            />
            <Field
              id="codex-approval"
              label="Approval Policy"
              value={approvalPolicy}
              placeholder="default"
              onChange={setApprovalPolicy}
            />
            <ToggleRow id="codex-search" label="Search" checked={search} onChange={setSearch} />
            <ToggleRow id="codex-strict-config" label="Strict Config" checked={strictConfig} onChange={setStrictConfig} />
            <ToggleRow id="codex-no-alt-screen" label="No Alt Screen" checked={noAltScreen} onChange={setNoAltScreen} />
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
