import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SwitchSetting, TextSetting } from '../field-components'
import type { SettingsCardProps } from '../types'

export function UiCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
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

        <TextSetting
          id="fileSuggestion"
          label="File Suggestion Script"
          description="Custom script for @ file autocomplete suggestions."
          value={getSetting<string>('fileSuggestion', '')}
          onChange={(v) => updateSetting('fileSuggestion', v)}
          placeholder="e.g., ./scripts/suggest-files.sh"
        />
      </CardContent>
    </Card>
  )
}
