import { useState, useEffect, useCallback } from 'react'
import { Save, Plus, X, Loader2, AlertTriangle } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { apiClient, buildEndpoint } from '@/lib/api'
import { useProjectContext } from '@/contexts/ProjectContext'
import { toast } from 'sonner'
import type { ConfigValue, SettingsScope, ScopedSettingsResponse } from '@/types/config'
import { PermissionRulesEditor } from './PermissionRulesEditor'
import { findPatternIssues, applyPatternFixes, type PatternIssue } from '@/lib/pattern-utils'

interface SettingsEditorProps {
  onSave?: () => void
}

// Common model options for Claude
const MODEL_OPTIONS = [
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
  { value: 'claude-3-5-haiku-20241022', label: 'Claude 3.5 Haiku' },
]

const PERMISSION_MODE_OPTIONS = [
  { value: 'default', label: 'Default' },
  { value: 'acceptEdits', label: 'Accept Edits' },
  { value: 'dontAsk', label: "Don't Ask" },
  { value: 'plan', label: 'Plan Mode' },
  { value: 'bypassPermissions', label: 'Bypass Permissions' },
  { value: 'delegate', label: 'Delegate' },
]

const UPDATE_CHANNEL_OPTIONS = [
  { value: 'stable', label: 'Stable' },
  { value: 'latest', label: 'Latest' },
]

const TEAMMATE_MODE_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'in-process', label: 'In-Process' },
  { value: 'tmux', label: 'Tmux' },
]

// Reusable setting field components to reduce repetition in the form

function SwitchSetting({ label, description, checked, onCheckedChange }: {
  label: string
  description: string
  checked: boolean
  onCheckedChange: (value: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="space-y-0.5">
        <Label>{label}</Label>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  )
}

function NumberSetting({ id, label, description, value, onChange, placeholder }: {
  id: string
  label: string
  description?: string
  value: string | number
  onChange: (value: number | null) => void
  placeholder?: string
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value ? parseInt(e.target.value) : null)}
        placeholder={placeholder}
      />
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
    </div>
  )
}

function SelectSetting({ id, label, description, value, onValueChange, placeholder, options }: {
  id: string
  label: string
  description?: string
  value: string
  onValueChange: (value: string) => void
  placeholder?: string
  options: { value: string; label: string }[]
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger id={id}>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
    </div>
  )
}

function TextSetting({ id, label, description, value, onChange, placeholder }: {
  id: string
  label: string
  description?: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
    </div>
  )
}

function TextareaSetting({ id, label, description, value, onChange, placeholder, rows }: {
  id: string
  label: string
  description?: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  rows?: number
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Textarea
        id={id}
        className="font-mono text-sm"
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
    </div>
  )
}

function ListEditor({ value, onChange, placeholder }: {
  value: string[]
  onChange: (value: string[]) => void
  placeholder?: string
}) {
  const [newItem, setNewItem] = useState('')

  function addItem() {
    if (newItem.trim() && !value.includes(newItem.trim())) {
      onChange([...value, newItem.trim()])
      setNewItem('')
    }
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
              onClick={() => onChange(value.filter((_, i) => i !== index))}
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

function KeyValueEditor({ value, onChange }: {
  value: Record<string, string>
  onChange: (value: Record<string, string>) => void
}) {
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')

  function addItem() {
    if (newKey.trim()) {
      onChange({ ...value, [newKey.trim()]: newValue })
      setNewKey('')
      setNewValue('')
    }
  }

  function removeItem(key: string) {
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

export function SettingsEditor({ onSave }: SettingsEditorProps) {
  const { activeProject } = useProjectContext()
  const [scope, setScope] = useState<SettingsScope>('user')
  const [settings, setSettings] = useState<Record<string, ConfigValue>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [patternIssues, setPatternIssues] = useState<PatternIssue[]>([])
  const [showFixDialog, setShowFixDialog] = useState(false)

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

  const getSetting = <T extends ConfigValue = ConfigValue>(path: string, defaultValue: T): T => {
    const keys = path.split('.')
    let current: ConfigValue = settings
    for (const key of keys) {
      if (current === undefined || current === null || typeof current !== 'object' || Array.isArray(current)) return defaultValue
      current = (current as Record<string, ConfigValue>)[key]
    }
    return (current ?? defaultValue) as T
  }

  const doSave = async (settingsToSave: Record<string, ConfigValue>) => {
    setSaving(true)
    try {
      const result = await apiClient<{
        success: boolean
        message: string
        migrated_patterns?: { original: string; migrated: string; category: string }[]
        removed_patterns?: { pattern: string; category: string; reason: string }[]
      }>('config/settings', {
        method: 'PUT',
        body: JSON.stringify({
          scope,
          settings: settingsToSave,
          project_path: activeProject?.path,
        }),
      })
      if (result.migrated_patterns?.length || result.removed_patterns?.length) {
        toast.success(result.message)
        // Reload settings to reflect sanitized state
        fetchSettings()
      } else {
        toast.success('Settings saved successfully')
        setHasChanges(false)
      }
      onSave?.()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save settings'
      toast.error(message)
    } finally {
      setSaving(false)
    }
  }

  const saveSettings = async () => {
    // Check for invalid permission patterns before saving
    const issues = findPatternIssues(settings as Record<string, unknown>)
    if (issues.length > 0) {
      setPatternIssues(issues)
      setShowFixDialog(true)
      return
    }
    await doSave(settings)
  }

  const handleFixAndSave = async () => {
    setShowFixDialog(false)
    const fixed = applyPatternFixes(settings as Record<string, unknown>) as Record<string, ConfigValue>
    setSettings(fixed)
    await doSave(fixed)
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
            <SelectSetting
              id="model"
              label="Model"
              value={getSetting<string>('model', '')}
              onValueChange={(v) => updateSetting('model', v)}
              placeholder="Select a model"
              options={MODEL_OPTIONS}
            />

            <TextSetting
              id="language"
              label="Language"
              value={getSetting<string>('language', '')}
              onChange={(v) => updateSetting('language', v)}
              placeholder="e.g., en, es, de"
            />

            <SelectSetting
              id="autoUpdatesChannel"
              label="Auto Updates Channel"
              value={getSetting<string>('autoUpdatesChannel', 'stable')}
              onValueChange={(v) => updateSetting('autoUpdatesChannel', v)}
              options={UPDATE_CHANNEL_OPTIONS}
            />
          </CardContent>
        </Card>

        {/* Sandbox Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Sandbox</CardTitle>
            <CardDescription>Sandbox and security settings</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <SwitchSetting
              label="Enable Sandbox"
              description="Run commands in an isolated environment"
              checked={getSetting<boolean>('sandbox.enabled', false)}
              onCheckedChange={(v) => updateSetting('sandbox.enabled', v)}
            />

            <SwitchSetting
              label="Auto-Allow Bash if Sandboxed"
              description="Automatically allow bash commands when sandbox is enabled"
              checked={getSetting<boolean>('sandbox.autoAllowBashIfSandboxed', false)}
              onCheckedChange={(v) => updateSetting('sandbox.autoAllowBashIfSandboxed', v)}
            />

            <SwitchSetting
              label="Allow Unsandboxed Commands"
              description="Allow the dangerouslyDisableSandbox escape hatch"
              checked={getSetting<boolean>('sandbox.allowUnsandboxedCommands', true)}
              onCheckedChange={(v) => updateSetting('sandbox.allowUnsandboxedCommands', v)}
            />

            <SwitchSetting
              label="Weaker Nested Sandbox"
              description="Use weaker sandbox for unprivileged Docker containers"
              checked={getSetting<boolean>('sandbox.enableWeakerNestedSandbox', false)}
              onCheckedChange={(v) => updateSetting('sandbox.enableWeakerNestedSandbox', v)}
            />

            <div className="grid gap-2">
              <Label>Excluded Commands</Label>
              <p className="text-sm text-muted-foreground">
                Commands that bypass sandbox isolation
              </p>
              <ListEditor
                value={getSetting<string[]>('sandbox.excludedCommands', [])}
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
                value={getSetting<string[]>('sandbox.network.allowedDomains', [])}
                onChange={(v) => updateSetting('sandbox.network.allowedDomains', v)}
                placeholder="Add domain..."
              />
            </div>

            <div className="grid gap-2">
              <Label>Allowed Unix Sockets</Label>
              <p className="text-sm text-muted-foreground">
                Unix socket paths accessible in sandbox
              </p>
              <ListEditor
                value={getSetting<string[]>('sandbox.network.allowUnixSockets', [])}
                onChange={(v) => updateSetting('sandbox.network.allowUnixSockets', v)}
                placeholder="e.g., ~/.ssh/agent-socket"
              />
            </div>

            <SwitchSetting
              label="Allow All Unix Sockets"
              description="Allow all Unix socket connections in sandbox"
              checked={getSetting<boolean>('sandbox.network.allowAllUnixSockets', false)}
              onCheckedChange={(v) => updateSetting('sandbox.network.allowAllUnixSockets', v)}
            />

            <SwitchSetting
              label="Allow Local Binding"
              description="Allow localhost binding in sandbox (macOS only)"
              checked={getSetting<boolean>('sandbox.network.allowLocalBinding', false)}
              onCheckedChange={(v) => updateSetting('sandbox.network.allowLocalBinding', v)}
            />

            <div className="grid grid-cols-2 gap-4">
              <NumberSetting
                id="httpProxyPort"
                label="HTTP Proxy Port"
                value={getSetting<string | number>('sandbox.network.httpProxyPort', '')}
                onChange={(v) => updateSetting('sandbox.network.httpProxyPort', v)}
                placeholder="8080"
              />
              <NumberSetting
                id="socksProxyPort"
                label="SOCKS5 Proxy Port"
                value={getSetting<string | number>('sandbox.network.socksProxyPort', '')}
                onChange={(v) => updateSetting('sandbox.network.socksProxyPort', v)}
                placeholder="8081"
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
            <SelectSetting
              id="permissionsMode"
              label="Default Permission Mode"
              value={getSetting<string>('permissions.defaultMode', 'default')}
              onValueChange={(v) => updateSetting('permissions.defaultMode', v)}
              options={PERMISSION_MODE_OPTIONS}
            />

            <SwitchSetting
              label="Disable Bypass Permissions Mode"
              description="Prevent users from enabling bypassPermissions mode"
              checked={getSetting<string>('permissions.disableBypassPermissionsMode', '') === 'disable'}
              onCheckedChange={(v) => updateSetting('permissions.disableBypassPermissionsMode', v ? 'disable' : '')}
            />

            <div className="grid gap-2">
              <Label>Additional Directories</Label>
              <p className="text-sm text-muted-foreground">
                Extra working directories Claude can access
              </p>
              <ListEditor
                value={getSetting<string[]>('permissions.additionalDirectories', [])}
                onChange={(v) => updateSetting('permissions.additionalDirectories', v)}
                placeholder="e.g., ../docs/"
              />
            </div>

            <PermissionRulesEditor
              allowRules={getSetting<string[]>('permissions.allow', [])}
              denyRules={getSetting<string[]>('permissions.deny', [])}
              askRules={getSetting<string[]>('permissions.ask', [])}
              onAllowChange={(rules) => updateSetting('permissions.allow', rules)}
              onDenyChange={(rules) => updateSetting('permissions.deny', rules)}
              onAskChange={(rules) => updateSetting('permissions.ask', rules)}
            />
          </CardContent>
        </Card>

        {/* Attribution Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Attribution</CardTitle>
            <CardDescription>Configure commit and PR attribution text</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <TextareaSetting
              id="attributionCommit"
              label="Commit Attribution"
              description="Text appended to commit messages"
              value={getSetting<string>('attribution.commit', '')}
              onChange={(v) => updateSetting('attribution.commit', v)}
              placeholder="Co-Authored-By: Claude <noreply@anthropic.com>"
              rows={3}
            />

            <TextareaSetting
              id="attributionPr"
              label="PR Attribution"
              description="Text appended to pull request descriptions"
              value={getSetting<string>('attribution.pr', '')}
              onChange={(v) => updateSetting('attribution.pr', v)}
              placeholder="Generated by Claude"
              rows={2}
            />
          </CardContent>
        </Card>

        {/* UI Settings */}
        <Card>
          <CardHeader>
            <CardTitle>UI</CardTitle>
            <CardDescription>User interface preferences</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <SwitchSetting
              label="Always Thinking Enabled"
              description="Always show thinking process in responses"
              checked={getSetting<boolean>('alwaysThinkingEnabled', false)}
              onCheckedChange={(v) => updateSetting('alwaysThinkingEnabled', v)}
            />

            <SwitchSetting
              label="Show Turn Duration"
              description="Display how long each turn took"
              checked={getSetting<boolean>('showTurnDuration', false)}
              onCheckedChange={(v) => updateSetting('showTurnDuration', v)}
            />

            <SwitchSetting
              label="Respect .gitignore"
              description="Respect .gitignore in the @ file picker"
              checked={getSetting<boolean>('respectGitignore', true)}
              onCheckedChange={(v) => updateSetting('respectGitignore', v)}
            />

            <SwitchSetting
              label="Spinner Tips"
              description="Show tips in the loading spinner"
              checked={getSetting<boolean>('spinnerTipsEnabled', true)}
              onCheckedChange={(v) => updateSetting('spinnerTipsEnabled', v)}
            />

            <SwitchSetting
              label="Terminal Progress Bar"
              description="Show progress bar in the terminal"
              checked={getSetting<boolean>('terminalProgressBarEnabled', true)}
              onCheckedChange={(v) => updateSetting('terminalProgressBarEnabled', v)}
            />

            <SwitchSetting
              label="Reduced Motion"
              description="Reduce UI animations for accessibility"
              checked={getSetting<boolean>('prefersReducedMotion', false)}
              onCheckedChange={(v) => updateSetting('prefersReducedMotion', v)}
            />
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
              value={getSetting<Record<string, string>>('env', {})}
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
            <TextSetting
              id="outputStyle"
              label="Output Style"
              description="Controls the style of Claude's responses"
              value={getSetting<string>('outputStyle', '')}
              onChange={(v) => updateSetting('outputStyle', v)}
              placeholder="e.g., Explanatory, Concise"
            />

            <TextSetting
              id="plansDirectory"
              label="Plans Directory"
              description="Where plan files are stored (relative to project root)"
              value={getSetting<string>('plansDirectory', '')}
              onChange={(v) => updateSetting('plansDirectory', v)}
              placeholder="~/.claude/plans"
            />

            <SelectSetting
              id="teammateMode"
              label="Teammate Mode"
              description="How agent teammates are displayed"
              value={getSetting<string>('teammateMode', '')}
              onValueChange={(v) => updateSetting('teammateMode', v)}
              placeholder="Select mode"
              options={TEAMMATE_MODE_OPTIONS}
            />

            <SwitchSetting
              label="Disable All Hooks"
              description="Disable all hooks and custom status line"
              checked={getSetting<boolean>('disableAllHooks', false)}
              onCheckedChange={(v) => updateSetting('disableAllHooks', v)}
            />

            <NumberSetting
              id="cleanupPeriodDays"
              label="Cleanup Period (days)"
              description="Number of days before old sessions are cleaned up"
              value={getSetting<string | number>('cleanupPeriodDays', '')}
              onChange={(v) => updateSetting('cleanupPeriodDays', v)}
              placeholder="30"
            />
          </CardContent>
        </Card>
      </div>

      {/* Pattern Fix Confirmation Dialog */}
      <AlertDialog open={showFixDialog} onOpenChange={setShowFixDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
              Invalid Permission Patterns Found
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3">
                <p>
                  {patternIssues.length} pattern{patternIssues.length !== 1 ? 's' : ''} would
                  be rejected by Claude Code. Fix them before saving?
                </p>
                <div className="max-h-48 overflow-y-auto space-y-2 text-sm">
                  {patternIssues.map((issue, i) => (
                    <div key={i} className="rounded border p-2 bg-muted">
                      <code className="text-xs break-all block">
                        {issue.pattern.length > 100
                          ? issue.pattern.slice(0, 100) + '...'
                          : issue.pattern}
                      </code>
                      <p className="text-xs text-muted-foreground mt-1">{issue.error}</p>
                      {issue.suggestion && (
                        <p className="text-xs text-green-600 mt-1">
                          Fix: {issue.suggestion}
                        </p>
                      )}
                      {!issue.suggestion && (
                        <p className="text-xs text-red-600 mt-1">
                          Will be removed (cannot auto-fix)
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleFixAndSave}>
              Fix & Save
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
