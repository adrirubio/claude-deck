import { useMemo, useState } from 'react'
import { Plus, Save } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { updateCodexConfig } from '@/hooks/useProviders'
import type { CodexConfigResponse, CodexConfigUpdateRequest } from '@/types/providers'

interface CodexSettingsEditorProps {
  config: CodexConfigResponse | null
  onSaved: () => Promise<void> | void
}

const FEATURE_NAME_PATTERN = /^[A-Za-z0-9_-]+$/

function optionalString(value: string): string | null {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function optionalBoolean(current: boolean, original: boolean | undefined): boolean | null {
  if (original !== undefined || current === true) return current
  return null
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
}: {
  id: string
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
      <Label htmlFor={id} className="text-sm font-medium">
        {label}
      </Label>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  )
}

export function CodexSettingsEditor({ config, onSaved }: CodexSettingsEditorProps) {
  const summary = config?.summary
  const initialFeatures = useMemo(() => summary?.features ?? {}, [summary?.features])
  const [model, setModel] = useState(summary?.model ?? '')
  const [reasoning, setReasoning] = useState(summary?.model_reasoning_effort ?? '')
  const [profile, setProfile] = useState(summary?.profile ?? '')
  const [sandboxMode, setSandboxMode] = useState(summary?.sandbox_mode ?? '')
  const [approvalPolicy, setApprovalPolicy] = useState(summary?.approval_policy ?? '')
  const [search, setSearch] = useState(summary?.search ?? false)
  const [strictConfig, setStrictConfig] = useState(summary?.strict_config ?? false)
  const [noAltScreen, setNoAltScreen] = useState(summary?.no_alt_screen ?? false)
  const [features, setFeatures] = useState<Record<string, boolean>>(initialFeatures)
  const [newFeature, setNewFeature] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const featureEntries = Object.entries(features).sort(([a], [b]) => a.localeCompare(b))
  const canAddFeature = FEATURE_NAME_PATTERN.test(newFeature.trim()) && !(newFeature.trim() in features)

  function setFeature(name: string, value: boolean) {
    setFeatures((current) => ({ ...current, [name]: value }))
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
    setNewFeature('')
  }

  async function handleSave() {
    setSubmitting(true)
    try {
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
        features,
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
              {featureEntries.length === 0 ? (
                <p className="rounded-md border p-3 text-sm text-muted-foreground">No feature flags configured.</p>
              ) : (
                featureEntries.map(([name, enabled]) => (
                  <ToggleRow
                    key={name}
                    id={`codex-feature-${name}`}
                    label={name}
                    checked={enabled}
                    onChange={(checked) => setFeature(name, checked)}
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
