import { useState, useEffect, useCallback } from 'react'
import { Save, Loader2, AlertTriangle, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
import { findPatternIssues, applyPatternFixes, type PatternIssue } from '@/lib/pattern-utils'

import { AuthenticationCard } from './cards/AuthenticationCard'
import { GeneralCard } from './cards/GeneralCard'
import { MemoryCard } from './cards/MemoryCard'
import { SandboxCard } from './cards/SandboxCard'
import { PermissionsCard } from './cards/PermissionsCard'
import { AutoModeCard } from './cards/AutoModeCard'
import { McpServersCard } from './cards/McpServersCard'
import { PluginManagementCard } from './cards/PluginManagementCard'
import { AttributionCard } from './cards/AttributionCard'
import { UiCard } from './cards/UiCard'
import { EnvVarsCard } from './cards/EnvVarsCard'
import { HooksSecurityCard } from './cards/HooksSecurityCard'
import { HookEventEditorCard } from './cards/HookEventEditorCard'
import { AdvancedCard } from './cards/AdvancedCard'

interface SettingsEditorProps {
  onSave?: () => void
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
    const UNSAFE_KEYS = new Set(['__proto__', 'constructor', 'prototype'])
    const keys = path.split('.')
    if (keys.some((k) => UNSAFE_KEYS.has(k))) return
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

  const getSettingRaw = (path: string): ConfigValue | undefined => {
    const keys = path.split('.')
    let current: ConfigValue = settings
    for (const key of keys) {
      if (current === undefined || current === null || typeof current !== 'object' || Array.isArray(current)) return undefined
      current = (current as Record<string, ConfigValue>)[key]
    }
    return current
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

  const hasProject = !!activeProject?.path
  const isManaged = scope === 'managed'
  const cardProps = { getSetting, getSettingRaw, updateSetting, scope }

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
            <TabsTrigger value="managed">Managed</TabsTrigger>
          </TabsList>
        </Tabs>

        {isManaged ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Lock className="h-4 w-4" />
            Read-only
          </div>
        ) : (
          <Button onClick={saveSettings} disabled={!hasChanges || saving}>
            {saving ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-2" />
            )}
            Save Changes
          </Button>
        )}
      </div>

      {isManaged && (
        <div className="text-sm text-muted-foreground bg-muted p-3 rounded flex items-center gap-2">
          <Lock className="h-4 w-4 shrink-0" />
          Managed settings are controlled by your organization and cannot be edited here.
        </div>
      )}

      {!hasProject && (scope === 'project' || scope === 'local') && (
        <div className="text-sm text-muted-foreground bg-muted p-3 rounded">
          Select an active project to edit project-level settings.
        </div>
      )}

      <div className="grid gap-6">
        <AuthenticationCard {...cardProps} />
        <GeneralCard {...cardProps} />
        <MemoryCard {...cardProps} />
        <SandboxCard {...cardProps} />
        <PermissionsCard {...cardProps} />
        <AutoModeCard {...cardProps} />
        <McpServersCard {...cardProps} />
        <PluginManagementCard {...cardProps} />
        <AttributionCard {...cardProps} />
        <UiCard {...cardProps} />
        <EnvVarsCard {...cardProps} />
        <HookEventEditorCard {...cardProps} />
        <HooksSecurityCard {...cardProps} />
        <AdvancedCard {...cardProps} />
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
