import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SelectSetting, SwitchSetting, TextSetting } from '../field-components'
import { SHELL_OPTIONS, TUI_OPTIONS, VIEW_MODE_OPTIONS } from '../constants'
import type { SettingsCardProps } from '../types'

export function UiCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>UI</CardTitle>
        <CardDescription>User interface preferences</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SelectSetting
          id="tui"
          label="Terminal UI Mode"
          description="Fullscreen takes over the terminal; default inlines with your scrollback."
          value={getSetting<string>('tui', '')}
          onValueChange={(v) => updateSetting('tui', v)}
          placeholder="Default"
          options={TUI_OPTIONS}
        />

        <SelectSetting
          id="viewMode"
          label="View Mode"
          description="Verbose shows full tool output; focus hides ambient UI."
          value={getSetting<string>('viewMode', '')}
          onValueChange={(v) => updateSetting('viewMode', v)}
          placeholder="Default"
          options={VIEW_MODE_OPTIONS}
        />

        <SelectSetting
          id="defaultShell"
          label="Default Shell"
          description="Shell used for Bash tool invocations."
          value={getSetting<string>('defaultShell', '')}
          onValueChange={(v) => updateSetting('defaultShell', v)}
          placeholder="Auto"
          options={SHELL_OPTIONS}
        />

        <SwitchSetting
          label="Always Thinking Enabled"
          description="Always show thinking process in responses"
          checked={getSetting<boolean>('alwaysThinkingEnabled', false)}
          onCheckedChange={(v) => updateSetting('alwaysThinkingEnabled', v)}
        />

        <SwitchSetting
          label="Show Thinking Summaries"
          description="Display short summaries of thinking blocks as they stream"
          checked={getSetting<boolean>('showThinkingSummaries', true)}
          onCheckedChange={(v) => updateSetting('showThinkingSummaries', v)}
        />

        <SwitchSetting
          label="Away Summary"
          description="Surface a summary when you return to an idle session"
          checked={getSetting<boolean>('awaySummaryEnabled', false)}
          onCheckedChange={(v) => updateSetting('awaySummaryEnabled', v)}
        />

        <SwitchSetting
          label="Show Clear-Context Prompt on Plan Accept"
          description="After accepting a plan, prompt to clear conversation context before execution"
          checked={getSetting<boolean>('showClearContextOnPlanAccept', false)}
          onCheckedChange={(v) => updateSetting('showClearContextOnPlanAccept', v)}
        />

        <SwitchSetting
          label="Use Auto Mode During Plan"
          description="Allow auto mode to run while planning"
          checked={getSetting<boolean>('useAutoModeDuringPlan', false)}
          onCheckedChange={(v) => updateSetting('useAutoModeDuringPlan', v)}
        />

        <SwitchSetting
          label="Fast Mode Per-Session Opt-In"
          description="Require opting into fast mode per session rather than using the last-selected value"
          checked={getSetting<boolean>('fastModePerSessionOptIn', false)}
          onCheckedChange={(v) => updateSetting('fastModePerSessionOptIn', v)}
        />

        <SwitchSetting
          label="Voice Enabled"
          description="Enable voice input/output features"
          checked={getSetting<boolean>('voiceEnabled', false)}
          onCheckedChange={(v) => updateSetting('voiceEnabled', v)}
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
          id="feedbackSurveyRate"
          label="Feedback Survey Rate"
          description="Fraction of sessions (0 to 1) that see the feedback survey. 0 disables it."
          value={String(getSetting<string | number>('feedbackSurveyRate', ''))}
          onChange={(v) => {
            if (v === '') {
              updateSetting('feedbackSurveyRate', null)
              return
            }
            const num = parseFloat(v)
            updateSetting('feedbackSurveyRate', Number.isFinite(num) ? num : v)
          }}
          placeholder="0"
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
