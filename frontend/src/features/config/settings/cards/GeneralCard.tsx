import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { SelectSetting, TextSetting, ListEditor, KeyValueEditor } from '../field-components'
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
          id="language"
          label="Language"
          value={getSetting<string>('language', '')}
          onChange={(v) => updateSetting('language', v)}
          placeholder="e.g., en, es, de"
        />

        <SelectSetting
          id="autoUpdatesChannel"
          label="Auto Updates Channel"
          value={getSetting<string>('autoUpdatesChannel', 'stable')}
          onValueChange={(v) => updateSetting('autoUpdatesChannel', v)}
          options={UPDATE_CHANNEL_OPTIONS}
        />

        <SelectSetting
          id="effortLevel"
          label="Effort Level"
          description="Persist the effort level across sessions. Supported on Opus 4.6+ and Sonnet 4.6. Note: Opus 4.8 defaults to high."
          value={getSetting<string>('effortLevel', '')}
          onValueChange={(v) => updateSetting('effortLevel', v)}
          placeholder="Select effort level"
          options={EFFORT_LEVEL_OPTIONS}
        />

        <div className="grid gap-2">
          <Label>Available Models</Label>
          <p className="text-sm text-muted-foreground">
            Restrict which models users can select via /model. Does not affect the Default option.
          </p>
          <ListEditor
            value={getSetting<string[]>('availableModels', [])}
            onChange={(v) => updateSetting('availableModels', v)}
            placeholder="e.g., claude-sonnet-4-6"
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
