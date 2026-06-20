import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { NumberSetting, SelectSetting, SwitchSetting, TextSetting } from '../field-components'
import { SHELL_OPTIONS, THEME_OPTIONS, TUI_OPTIONS, VIEW_MODE_OPTIONS } from '../constants'
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
          id="theme"
          label="Theme"
          description="Claude Code terminal color theme."
          value={getSetting<string>('theme', '')}
          onValueChange={(v) => updateSetting('theme', v)}
          placeholder="Default"
          options={THEME_OPTIONS}
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
          description="Shell used for input-box ! commands."
          value={getSetting<string>('defaultShell', '')}
          onValueChange={(v) => updateSetting('defaultShell', v)}
          placeholder="Auto"
          options={SHELL_OPTIONS}
        />

        <SwitchSetting
          label="Screen Reader Mode"
          description="Render flat text without decorative borders or animations."
          checked={getSetting<boolean>('axScreenReader', false)}
          onCheckedChange={(v) => updateSetting('axScreenReader', v)}
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
          checked={getSetting<boolean>('showThinkingSummaries', false)}
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
          checked={getSetting<boolean>('useAutoModeDuringPlan', true)}
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
          checked={getSetting<boolean>('showTurnDuration', true)}
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

        <SwitchSetting
          label="Disable Syntax Highlighting"
          description="Disable syntax highlighting in diffs, code blocks, and file previews."
          checked={getSetting<boolean>('syntaxHighlightingDisabled', false)}
          onCheckedChange={(v) => updateSetting('syntaxHighlightingDisabled', v)}
        />

        <SwitchSetting
          label="Wheel Scroll Acceleration"
          description="Accelerate mouse-wheel scrolling during fast scrolls in fullscreen rendering."
          checked={getSetting<boolean>('wheelScrollAccelerationEnabled', true)}
          onCheckedChange={(v) => updateSetting('wheelScrollAccelerationEnabled', v)}
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

        <div className="grid gap-2">
          <Label>File Suggestion</Label>
          <p className="text-xs text-muted-foreground">
            Custom command for @-file autocomplete. Leave command empty to use the default.
          </p>
          <div className="grid gap-3 md:grid-cols-[1fr_140px]">
            <TextSetting
              id="fileSuggestionCommand"
              label="Command"
              value={getSetting<string>('fileSuggestion.command', '')}
              onChange={(v) => {
                updateSetting('fileSuggestion.command', v || null)
                updateSetting('fileSuggestion.type', v ? 'command' : null)
              }}
              placeholder="fd --type f --hidden --exclude .git"
            />
            <NumberSetting
              id="fileSuggestionTimeout"
              label="Timeout (ms)"
              value={getSetting<string | number>('fileSuggestion.timeout', '')}
              onChange={(v) => updateSetting('fileSuggestion.timeout', v)}
              placeholder="5000"
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
