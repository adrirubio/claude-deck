import { useState, useEffect, useCallback } from 'react'
import { Save, Plus, X, Loader2 } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { apiClient, buildEndpoint } from '@/lib/api'
import { useProjectContext } from '@/contexts/ProjectContext'
import { toast } from 'sonner'
import type { ConfigValue, SettingsScope, ScopedSettingsResponse } from '@/types/config'

interface SettingsEditorProps {
  onSave?: () => void
}

// Common model options for Claude
const MODEL_OPTIONS = [
  { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
  { value: 'claude-opus-4-20250514', label: 'Claude Opus 4' },
  { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
  { value: 'claude-3-5-haiku-20241022', label: 'Claude 3.5 Haiku' },
  { value: 'claude-3-opus-20240229', label: 'Claude 3 Opus' },
]

const PERMISSION_MODE_OPTIONS = [
  { value: 'default', label: 'Default' },
  { value: 'acceptEdits', label: 'Accept Edits' },
  { value: 'dontAsk', label: "Don't Ask" },
  { value: 'plan', label: 'Plan Mode' },
]

const UPDATE_CHANNEL_OPTIONS = [
  { value: 'stable', label: 'Stable' },
  { value: 'latest', label: 'Latest' },
]

export function SettingsEditor({ onSave }: SettingsEditorProps) {
  const { activeProject } = useProjectContext()
  const [scope, setScope] = useState<SettingsScope>('user')
  const [settings, setSettings] = useState<Record<string, ConfigValue>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)

  const fetchSettings = useCallback(async () => {
    setLoading(true)
    try {
      const endpoint = buildEndpoint(`config/settings/${scope}`, {
        project_path: activeProject?.path,
      })
      const response = await apiClient<ScopedSettingsResponse>(endpoint)
      setSettings(response.settings || {})
      setHasChanges(false)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load settings'
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }, [scope, activeProject?.path])

  useEffect(() => {
    fetchSettings()
  }, [fetchSettings])

  const updateSetting = (path: string, value: ConfigValue) => {
    const keys = path.split('.')
    setSettings((prev) => {
      const updated = { ...prev }
      let current: Record<string, ConfigValue> = updated
      for (let i = 0; i < keys.length - 1; i++) {
        const existing = current[keys[i]]
        if (!existing || typeof existing !== 'object' || Array.isArray(existing)) {
          current[keys[i]] = {}
        } else {
          current[keys[i]] = { ...existing }
        }
        current = current[keys[i]] as Record<string, ConfigValue>
      }
      current[keys[keys.length - 1]] = value
      return updated
    })
    setHasChanges(true)
  }

  const getSetting = (path: string, defaultValue: ConfigValue = null): ConfigValue => {
    const keys = path.split('.')
    let current: ConfigValue = settings
    for (const key of keys) {
      if (current === undefined || current === null || typeof current !== 'object' || Array.isArray(current)) return defaultValue
      current = (current as Record<string, ConfigValue>)[key]
    }
    return current ?? defaultValue
  }

  const saveSettings = async () => {
    setSaving(true)
    try {
      await apiClient('config/settings', {
        method: 'PUT',
        body: JSON.stringify({
          scope,
          settings,
          project_path: activeProject?.path,
        }),
      })
      toast.success('Settings saved successfully')
      setHasChanges(false)
      onSave?.()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save settings'
      toast.error(message)
    } finally {
      setSaving(false)
    }
  }

  // List editors for array values
  const ListEditor = ({
    value,
    onChange,
    placeholder,
  }: {
    value: string[]
    onChange: (value: string[]) => void
    placeholder?: string
  }) => {
    const [newItem, setNewItem] = useState('')

    const addItem = () => {
      if (newItem.trim() && !value.includes(newItem.trim())) {
        onChange([...value, newItem.trim()])
        setNewItem('')
      }
    }

    const removeItem = (index: number) => {
      onChange(value.filter((_, i) => i !== index))
    }

    return (
      <div className="space-y-2">
        <div className="flex gap-2">
          <Input
            value={newItem}
            onChange={(e) => setNewItem(e.target.value)}
            placeholder={placeholder}
            onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addItem())}
          />
          <Button type="button" size="icon" variant="outline" onClick={addItem}>
            <Plus className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {value.map((item, index) => (
            <div
              key={index}
              className="flex items-center gap-1 bg-muted px-2 py-1 rounded text-sm"
            >
              <span>{item}</span>
              <button
                type="button"
                onClick={() => removeItem(index)}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Key-value editor for env variables
  const KeyValueEditor = ({
    value,
    onChange,
  }: {
    value: Record<string, string>
    onChange: (value: Record<string, string>) => void
  }) => {
    const [newKey, setNewKey] = useState('')
    const [newValue, setNewValue] = useState('')

    const addItem = () => {
      if (newKey.trim()) {
        onChange({ ...value, [newKey.trim()]: newValue })
        setNewKey('')
        setNewValue('')
      }
    }

    const removeItem = (key: string) => {
      const updated = { ...value }
      delete updated[key]
      onChange(updated)
    }

    return (
      <div className="space-y-2">
        <div className="flex gap-2">
          <Input
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            placeholder="Key"
            className="flex-1"
          />
          <Input
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            placeholder="Value"
            className="flex-1"
          />
          <Button type="button" size="icon" variant="outline" onClick={addItem}>
            <Plus className="h-4 w-4" />
          </Button>
        </div>
        <div className="space-y-1">
          {Object.entries(value).map(([k, v]) => (
            <div key={k} className="flex items-center gap-2 bg-muted px-2 py-1 rounded text-sm">
              <span className="font-mono">{k}</span>
              <span className="text-muted-foreground">=</span>
              <span className="font-mono flex-1 truncate">{v}</span>
              <button
                type="button"
                onClick={() => removeItem(k)}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Determine if project scopes should be available
  const hasProject = !!activeProject?.path

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Scope Selector */}
      <div className="flex items-center justify-between">
        <Tabs value={scope} onValueChange={(v) => setScope(v as SettingsScope)}>
          <TabsList>
            <TabsTrigger value="user">User</TabsTrigger>
            <TabsTrigger value="user_local">User Local</TabsTrigger>
            <TabsTrigger value="project" disabled={!hasProject}>
              Project
            </TabsTrigger>
            <TabsTrigger value="local" disabled={!hasProject}>
              Project Local
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <Button onClick={saveSettings} disabled={!hasChanges || saving}>
          {saving ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Save className="h-4 w-4 mr-2" />
          )}
          Save Changes
        </Button>
      </div>

      {!hasProject && (scope === 'project' || scope === 'local') && (
        <div className="text-sm text-muted-foreground bg-muted p-3 rounded">
          Select an active project to edit project-level settings.
        </div>
      )}

      <div className="grid gap-6">
        {/* General Settings */}
        <Card>
          <CardHeader>
            <CardTitle>General</CardTitle>
            <CardDescription>Basic configuration options</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2">
              <Label htmlFor="model">Model</Label>
              <Select
                value={getSetting('model', '') as string}
                onValueChange={(v) => updateSetting('model', v)}
              >
                <SelectTrigger id="model">
                  <SelectValue placeholder="Select a model" />
                </SelectTrigger>
                <SelectContent>
                  {MODEL_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="language">Language</Label>
              <Input
                id="language"
                value={getSetting('language', '') as string}
                onChange={(e) => updateSetting('language', e.target.value)}
                placeholder="e.g., en, es, de"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="autoUpdatesChannel">Auto Updates Channel</Label>
              <Select
                value={getSetting('autoUpdatesChannel', 'stable') as string}
                onValueChange={(v) => updateSetting('autoUpdatesChannel', v)}
              >
                <SelectTrigger id="autoUpdatesChannel">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {UPDATE_CHANNEL_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Sandbox Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Sandbox</CardTitle>
            <CardDescription>Sandbox and security settings</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Enable Sandbox</Label>
                <p className="text-sm text-muted-foreground">
                  Run commands in an isolated environment
                </p>
              </div>
              <Switch
                checked={getSetting('sandbox.enabled', false) as boolean}
                onCheckedChange={(v) => updateSetting('sandbox.enabled', v)}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Auto-Allow Bash if Sandboxed</Label>
                <p className="text-sm text-muted-foreground">
                  Automatically allow bash commands when sandbox is enabled
                </p>
              </div>
              <Switch
                checked={getSetting('sandbox.autoAllowBashIfSandboxed', false) as boolean}
                onCheckedChange={(v) => updateSetting('sandbox.autoAllowBashIfSandboxed', v)}
              />
            </div>

            <div className="grid gap-2">
              <Label>Excluded Commands</Label>
              <p className="text-sm text-muted-foreground">
                Commands that bypass sandbox isolation
              </p>
              <ListEditor
                value={getSetting('sandbox.excludedCommands', []) as string[]}
                onChange={(v) => updateSetting('sandbox.excludedCommands', v)}
                placeholder="Add command..."
              />
            </div>

            <div className="grid gap-2">
              <Label>Allowed Domains</Label>
              <p className="text-sm text-muted-foreground">
                Network domains accessible from sandbox
              </p>
              <ListEditor
                value={getSetting('sandbox.network.allowedDomains', []) as string[]}
                onChange={(v) => updateSetting('sandbox.network.allowedDomains', v)}
                placeholder="Add domain..."
              />
            </div>
          </CardContent>
        </Card>

        {/* Permissions Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Permissions</CardTitle>
            <CardDescription>Control permission prompts and defaults</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2">
              <Label htmlFor="permissionsMode">Default Permission Mode</Label>
              <Select
                value={getSetting('permissions.defaultMode', 'default') as string}
                onValueChange={(v) => updateSetting('permissions.defaultMode', v)}
              >
                <SelectTrigger id="permissionsMode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PERMISSION_MODE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* UI Settings */}
        <Card>
          <CardHeader>
            <CardTitle>UI</CardTitle>
            <CardDescription>User interface preferences</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Always Thinking Enabled</Label>
                <p className="text-sm text-muted-foreground">
                  Always show thinking process in responses
                </p>
              </div>
              <Switch
                checked={getSetting('alwaysThinkingEnabled', false) as boolean}
                onCheckedChange={(v) => updateSetting('alwaysThinkingEnabled', v)}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Show Turn Duration</Label>
                <p className="text-sm text-muted-foreground">
                  Display how long each turn took
                </p>
              </div>
              <Switch
                checked={getSetting('showTurnDuration', false) as boolean}
                onCheckedChange={(v) => updateSetting('showTurnDuration', v)}
              />
            </div>
          </CardContent>
        </Card>

        {/* Environment Variables */}
        <Card>
          <CardHeader>
            <CardTitle>Environment Variables</CardTitle>
            <CardDescription>Custom environment variables for Claude sessions</CardDescription>
          </CardHeader>
          <CardContent>
            <KeyValueEditor
              value={getSetting('env', {}) as Record<string, string>}
              onChange={(v) => updateSetting('env', v)}
            />
          </CardContent>
        </Card>

        {/* Advanced Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Advanced</CardTitle>
            <CardDescription>Advanced configuration options</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2">
              <Label htmlFor="contextWindow">Context Window</Label>
              <Input
                id="contextWindow"
                type="number"
                value={getSetting('contextWindow', '') as string | number}
                onChange={(e) =>
                  updateSetting('contextWindow', e.target.value ? parseInt(e.target.value) : null)
                }
                placeholder="Default context window size"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="maxTokens">Max Tokens</Label>
              <Input
                id="maxTokens"
                type="number"
                value={getSetting('maxTokens', '') as string | number}
                onChange={(e) =>
                  updateSetting('maxTokens', e.target.value ? parseInt(e.target.value) : null)
                }
                placeholder="Maximum tokens per response"
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
