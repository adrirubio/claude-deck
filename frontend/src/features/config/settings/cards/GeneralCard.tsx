import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { SelectSetting, TextSetting, ListEditor, KeyValueEditor, SwitchSetting } from '../field-components'
import { MODEL_OPTIONS, UPDATE_CHANNEL_OPTIONS, EFFORT_LEVEL_OPTIONS } from '../constants'
import type { SettingsCardProps } from '../types'

export function GeneralCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>General</CardTitle>
        <CardDescription>Basic configuration options</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SelectSetting
          id="model"
          label="Model"
          value={getSetting<string>('model', '')}
          onValueChange={(v) => updateSetting('model', v)}
          placeholder="Select a model"
          options={MODEL_OPTIONS}
        />

        <TextSetting
          id="advisorModel"
          label="Advisor Model"
          description="Optional model alias or full model ID for the advisor tool. Leave empty to disable the advisor."
          value={getSetting<string>('advisorModel', '')}
          onChange={(v) => updateSetting('advisorModel', v.trim() ? v : null)}
          placeholder="opus, sonnet, fable, or a full model ID"
        />

        <div className="grid gap-2">
          <Label>Fallback Models</Label>
          <p className="text-sm text-muted-foreground">
            Ordered models to try when the primary model is overloaded or unavailable. Claude Code uses up to three.
          </p>
          <ListEditor
            value={getSetting<string[]>('fallbackModel', [])}
            onChange={(v) => updateSetting('fallbackModel', v)}
            placeholder="e.g., claude-sonnet-5 or claude-fable-5"
          />
        </div>

        <TextSetting
          id="language"
          label="Language"
          value={getSetting<string>('language', '')}
          onChange={(v) => updateSetting('language', v)}
          placeholder="e.g., en, es, de"
        />

        <SelectSetting
          id="autoUpdatesChannel"
          label="Auto Updates Channel"
          value={getSetting<string>('autoUpdatesChannel', 'latest')}
          onValueChange={(v) => updateSetting('autoUpdatesChannel', v)}
          options={UPDATE_CHANNEL_OPTIONS}
        />

        <SelectSetting
          id="effortLevel"
          label="Effort Level"
          description="Persist the effort level across sessions. Supported on current Sonnet, Opus, and Fable models where Claude Code exposes effort controls."
          value={getSetting<string>('effortLevel', '')}
          onValueChange={(v) => updateSetting('effortLevel', v)}
          placeholder="Select effort level"
          options={EFFORT_LEVEL_OPTIONS}
        />

        <SwitchSetting
          label="Auto-Compact"
          description="Automatically compact the conversation when context approaches the limit."
          checked={getSetting<boolean>('autoCompactEnabled', true)}
          onCheckedChange={(v) => updateSetting('autoCompactEnabled', v)}
        />

        <SwitchSetting
          label="File Checkpointing"
          description="Snapshot files before edits so /rewind can restore them."
          checked={getSetting<boolean>('fileCheckpointingEnabled', true)}
          onCheckedChange={(v) => updateSetting('fileCheckpointingEnabled', v)}
        />

        <div className="grid gap-2">
          <Label>Available Models</Label>
          <p className="text-sm text-muted-foreground">
            Restrict which models users can select via /model. Does not affect the Default option.
          </p>
          <ListEditor
            value={getSetting<string[]>('availableModels', [])}
            onChange={(v) => updateSetting('availableModels', v)}
            placeholder="e.g., claude-sonnet-5"
          />
        </div>

        <div className="grid gap-2">
          <Label>Model Overrides</Label>
          <p className="text-sm text-muted-foreground">
            Map Anthropic model IDs to provider-specific IDs (e.g., Bedrock ARNs).
          </p>
          <KeyValueEditor
            value={getSetting<Record<string, string>>('modelOverrides', {})}
            onChange={(v) => updateSetting('modelOverrides', v)}
          />
        </div>
      </CardContent>
    </Card>
  )
}
