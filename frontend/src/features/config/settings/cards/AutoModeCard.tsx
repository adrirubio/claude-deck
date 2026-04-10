import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { SwitchSetting, ListEditor } from '../field-components'
import type { SettingsCardProps } from '../types'

export function AutoModeCard({ getSetting, updateSetting, scope }: SettingsCardProps) {
  // Auto mode config lives in user/local/managed only, not shared project settings
  if (scope === 'project') return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Auto Mode</CardTitle>
        <CardDescription>
          Configure the AI safety classifier for auto mode (requires Team/Enterprise + Sonnet 4.6+/Opus 4.6+)
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SwitchSetting
          label="Disable Auto Mode"
          description="Prevent auto mode from being used"
          checked={getSetting<string>('permissions.disableAutoMode', '') === 'disable'}
          onCheckedChange={(v) => updateSetting('permissions.disableAutoMode', v ? 'disable' : '')}
        />

        <div className="grid gap-2">
          <Label>Trusted Environment</Label>
          <p className="text-sm text-muted-foreground">
            Describe your trusted infrastructure so the classifier can make better safety decisions.
          </p>
          <ListEditor
            value={getSetting<string[]>('autoMode.environment', [])}
            onChange={(v) => updateSetting('autoMode.environment', v)}
            placeholder="e.g., This repo is deployed to a sandboxed staging environment"
          />
        </div>

        <div className="grid gap-2">
          <Label>Allow Rules</Label>
          <p className="text-sm text-muted-foreground">
            Whitelist exceptions — override default block rules for specific actions.
          </p>
          <ListEditor
            value={getSetting<string[]>('autoMode.allow', [])}
            onChange={(v) => updateSetting('autoMode.allow', v)}
            placeholder="e.g., Bash(git *)"
          />
        </div>

        <div className="grid gap-2">
          <Label>Soft Deny Rules</Label>
          <p className="text-sm text-muted-foreground">
            Block rules for the classifier — actions matching these descriptions will be denied.
          </p>
          <ListEditor
            value={getSetting<string[]>('autoMode.soft_deny', [])}
            onChange={(v) => updateSetting('autoMode.soft_deny', v)}
            placeholder="e.g., Bash(rm -rf *)"
          />
        </div>
      </CardContent>
    </Card>
  )
}
