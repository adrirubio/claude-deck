import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { TextSetting, NumberSetting, SelectSetting, SwitchSetting, ListEditor } from '../field-components'
import { SPINNER_VERBS_MODE_OPTIONS, TEAMMATE_MODE_OPTIONS } from '../constants'
import type { SettingsCardProps } from '../types'

export function AdvancedCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Advanced</CardTitle>
        <CardDescription>Advanced configuration options</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <TextSetting
          id="outputStyle"
          label="Output Style"
          description="Controls the style of Claude's responses"
          value={getSetting<string>('outputStyle', '')}
          onChange={(v) => updateSetting('outputStyle', v)}
          placeholder="e.g., Explanatory, Concise"
        />

        <TextSetting
          id="plansDirectory"
          label="Plans Directory"
          description="Where plan files are stored (relative to project root)"
          value={getSetting<string>('plansDirectory', '')}
          onChange={(v) => updateSetting('plansDirectory', v)}
          placeholder="~/.claude/plans"
        />

        <SelectSetting
          id="teammateMode"
          label="Teammate Mode"
          description="How agent teammates are displayed"
          value={getSetting<string>('teammateMode', '')}
          onValueChange={(v) => updateSetting('teammateMode', v)}
          placeholder="Select mode"
          options={TEAMMATE_MODE_OPTIONS}
        />

        <SwitchSetting
          label="Disable All Hooks"
          description="Disable all hooks and custom status line"
          checked={getSetting<boolean>('disableAllHooks', false)}
          onCheckedChange={(v) => updateSetting('disableAllHooks', v)}
        />

        <NumberSetting
          id="cleanupPeriodDays"
          label="Cleanup Period (days)"
          description="Number of days before old sessions are cleaned up"
          value={getSetting<string | number>('cleanupPeriodDays', '')}
          onChange={(v) => updateSetting('cleanupPeriodDays', v)}
          placeholder="30"
        />

        <SwitchSetting
          label="Include Git Instructions"
          description="Include built-in commit and PR workflow instructions in the system prompt. Set to false if using your own git workflow skills."
          checked={getSetting<boolean>('includeGitInstructions', true)}
          onCheckedChange={(v) => updateSetting('includeGitInstructions', v)}
        />

        <TextSetting
          id="apiKeyHelper"
          label="API Key Helper"
          description="Custom script (run via /bin/sh) to generate an auth value sent as X-Api-Key and Authorization: Bearer headers."
          value={getSetting<string>('apiKeyHelper', '')}
          onChange={(v) => updateSetting('apiKeyHelper', v)}
          placeholder="/bin/generate_temp_api_key.sh"
        />

        <div className="grid gap-2">
          <Label>Company Announcements</Label>
          <p className="text-sm text-muted-foreground">
            Messages displayed to users at startup, cycled through at random.
          </p>
          <ListEditor
            value={getSetting<string[]>('companyAnnouncements', [])}
            onChange={(v) => updateSetting('companyAnnouncements', v)}
            placeholder="Add announcement..."
          />
        </div>

        <TextSetting
          id="agent"
          label="Default Agent"
          description="Run the main thread as a named subagent. Applies that subagent's system prompt, tool restrictions, and model."
          value={getSetting<string>('agent', '')}
          onChange={(v) => updateSetting('agent', v)}
          placeholder="e.g., my-custom-agent"
        />

        <TextSetting
          id="minimumVersion"
          label="Minimum Version"
          description="Refuse to run if the Claude Code binary is older than this semver."
          value={getSetting<string>('minimumVersion', '')}
          onChange={(v) => updateSetting('minimumVersion', v)}
          placeholder="e.g., 1.5.0"
        />

        <SwitchSetting
          label="Disable Deep Link Registration"
          description="Skip registering the claude:// URL scheme handler"
          checked={getSetting<boolean>('disableDeepLinkRegistration', false)}
          onCheckedChange={(v) => updateSetting('disableDeepLinkRegistration', v)}
        />

        <div className="grid gap-2 rounded border p-3">
          <Label>Spinner Tips Override</Label>
          <p className="text-sm text-muted-foreground">
            Replace or extend the default loading-spinner tips.
          </p>
          <SwitchSetting
            label="Exclude Default Tips"
            description="Only show the tips listed below"
            checked={getSetting<boolean>('spinnerTipsOverride.excludeDefault', false)}
            onCheckedChange={(v) => updateSetting('spinnerTipsOverride.excludeDefault', v)}
          />
          <div className="grid gap-2">
            <Label>Custom Tips</Label>
            <ListEditor
              value={getSetting<string[]>('spinnerTipsOverride.tips', [])}
              onChange={(v) => updateSetting('spinnerTipsOverride.tips', v)}
              placeholder="Add a tip..."
            />
          </div>
        </div>

        <div className="grid gap-2 rounded border p-3">
          <Label>Spinner Verbs</Label>
          <p className="text-sm text-muted-foreground">
            Customize the verbs shown next to the spinner (e.g., "Thinking...", "Cooking...").
          </p>
          <SelectSetting
            id="spinnerVerbsMode"
            label="Mode"
            value={getSetting<string>('spinnerVerbs.mode', '')}
            onValueChange={(v) => updateSetting('spinnerVerbs.mode', v)}
            placeholder="Default"
            options={SPINNER_VERBS_MODE_OPTIONS}
          />
          <div className="grid gap-2">
            <Label>Verbs</Label>
            <ListEditor
              value={getSetting<string[]>('spinnerVerbs.verbs', [])}
              onChange={(v) => updateSetting('spinnerVerbs.verbs', v)}
              placeholder="e.g., Pondering"
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
