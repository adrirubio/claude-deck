import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SwitchSetting, TextSetting } from '../field-components'
import type { SettingsCardProps } from '../types'

export function MemoryCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Memory</CardTitle>
        <CardDescription>Auto memory lets Claude accumulate learnings between sessions</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SwitchSetting
          label="Auto Memory"
          description="Claude automatically takes notes on your project — build commands, preferences, architectural decisions — and loads them at the start of every session. Enabled by default; turn off to stop reading from and writing to the auto memory directory."
          checked={getSetting<boolean>('autoMemoryEnabled', true)}
          onCheckedChange={(v) => updateSetting('autoMemoryEnabled', v)}
        />
        <TextSetting
          id="autoMemoryDirectory"
          label="Memory Directory"
          description="Custom directory for auto memory storage. Accepts ~ paths. Only available in user/local settings (not project settings)."
          value={getSetting<string>('autoMemoryDirectory', '')}
          onChange={(v) => updateSetting('autoMemoryDirectory', v)}
          placeholder="~/.claude/memory"
        />
      </CardContent>
    </Card>
  )
}
