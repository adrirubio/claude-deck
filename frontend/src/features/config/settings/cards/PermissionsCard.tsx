import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { SelectSetting, SwitchSetting, ListEditor } from '../field-components'
import { PERMISSION_MODE_OPTIONS } from '../constants'
import { PermissionRulesEditor } from '../../PermissionRulesEditor'
import type { SettingsCardProps } from '../types'

export function PermissionsCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
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
  )
}
