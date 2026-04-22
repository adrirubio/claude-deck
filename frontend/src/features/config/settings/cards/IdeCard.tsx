import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SelectSetting, SwitchSetting } from '../field-components'
import { EDITOR_MODE_OPTIONS } from '../constants'
import type { SettingsCardProps } from '../types'

export function IdeCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>IDE & Editor</CardTitle>
        <CardDescription>Editor input mode and IDE extension preferences</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SelectSetting
          id="editorMode"
          label="Editor Mode"
          description="Input handling in the prompt editor — normal or vim motions."
          value={getSetting<string>('editorMode', '')}
          onValueChange={(v) => updateSetting('editorMode', v)}
          placeholder="Normal"
          options={EDITOR_MODE_OPTIONS}
        />

        <SwitchSetting
          label="Auto Connect IDE"
          description="Automatically connect to a running IDE when Claude Code starts"
          checked={getSetting<boolean>('autoConnectIde', false)}
          onCheckedChange={(v) => updateSetting('autoConnectIde', v)}
        />

        <SwitchSetting
          label="Auto Install IDE Extension"
          description="Install the Claude Code IDE extension on first launch"
          checked={getSetting<boolean>('autoInstallIdeExtension', true)}
          onCheckedChange={(v) => updateSetting('autoInstallIdeExtension', v)}
        />

        <SwitchSetting
          label="Auto Scroll"
          description="Automatically scroll to new output as it streams"
          checked={getSetting<boolean>('autoScrollEnabled', true)}
          onCheckedChange={(v) => updateSetting('autoScrollEnabled', v)}
        />

        <SwitchSetting
          label="External Editor Context"
          description="Include the active IDE file as context when opening an external editor"
          checked={getSetting<boolean>('externalEditorContext', false)}
          onCheckedChange={(v) => updateSetting('externalEditorContext', v)}
        />
      </CardContent>
    </Card>
  )
}
