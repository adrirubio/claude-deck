import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SelectSetting, TextSetting } from '../field-components'
import { LOGIN_METHOD_OPTIONS } from '../constants'
import type { SettingsCardProps } from '../types'

export function AuthenticationCard({ getSetting, updateSetting, scope }: SettingsCardProps) {
  if (scope !== 'managed') return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Authentication</CardTitle>
        <CardDescription>Restrict login method and organization (managed settings only)</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SelectSetting
          id="forceLoginMethod"
          label="Force Login Method"
          description="Restrict which authentication method users must use."
          value={getSetting<string>('forceLoginMethod', '')}
          onValueChange={(v) => updateSetting('forceLoginMethod', v)}
          placeholder="Select login method"
          options={LOGIN_METHOD_OPTIONS}
        />
        <TextSetting
          id="forceLoginOrgUUID"
          label="Force Login Org UUID"
          description="Restrict login to a specific organization UUID."
          value={getSetting<string>('forceLoginOrgUUID', '')}
          onChange={(v) => updateSetting('forceLoginOrgUUID', v)}
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        />
      </CardContent>
    </Card>
  )
}
