import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { KeyValueEditor } from '../field-components'
import type { SettingsCardProps } from '../types'

export function EnvVarsCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
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
  )
}
