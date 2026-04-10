import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { ListEditor } from '../field-components'
import type { SettingsCardProps } from '../types'

export function HooksSecurityCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Hooks Security</CardTitle>
        <CardDescription>Restrict HTTP hooks to approved destinations</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2">
          <Label>Allowed HTTP Hook URLs</Label>
          <p className="text-sm text-muted-foreground">
            Only these URL patterns can be called by HTTP hooks.
          </p>
          <ListEditor
            value={getSetting<string[]>('allowedHttpHookUrls', [])}
            onChange={(v) => updateSetting('allowedHttpHookUrls', v)}
            placeholder="https://hooks.example.com/*"
          />
        </div>

        <div className="grid gap-2">
          <Label>Allowed Hook Environment Variables</Label>
          <p className="text-sm text-muted-foreground">
            Environment variables that HTTP hooks are allowed to access.
          </p>
          <ListEditor
            value={getSetting<string[]>('httpHookAllowedEnvVars', [])}
            onChange={(v) => updateSetting('httpHookAllowedEnvVars', v)}
            placeholder="MY_TOKEN"
          />
        </div>
      </CardContent>
    </Card>
  )
}
